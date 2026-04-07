"""Unit tests for the yum_cache plugin cache_key shared-cache feature."""

from copy import deepcopy
from unittest import mock
from unittest.mock import MagicMock, patch

from mockbuild.plugins import yum_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_CONF = {
    'max_age_days': 30,
    'max_metadata_age_days': 0.5,
}


def make_buildroot(extra_config=None):
    br = MagicMock()
    br.config = {
        'cache_topdir': '/var/cache/mock',
        'online': False,
        'target_arch': 'x86_64',
    }
    if extra_config:
        br.config.update(extra_config)
    br.make_chroot_path.side_effect = lambda p: '/chroot' + p
    return br


# ---------------------------------------------------------------------------
# init() entry point
# ---------------------------------------------------------------------------

@patch('mockbuild.plugins.yum_cache.YumCache')
def test_init(MockYumCache):
    plugins, conf, buildroot = object(), object(), object()
    yum_cache.init(plugins, conf, buildroot)
    MockYumCache.assert_called_once_with(plugins, conf, buildroot)


# ---------------------------------------------------------------------------
# Without cache_key — legacy behaviour unchanged
# ---------------------------------------------------------------------------

@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_no_cache_key_uses_buildroot_cachedir(mock_file_util):
    """Without cache_key, host_cache_path must be buildroot.cachedir/dnf_cache."""
    br = make_buildroot()
    br.cachedir = '/var/cache/mock/my-root'
    conf = deepcopy(DEFAULT_CONF)

    with patch('builtins.open', mock.mock_open()):
        plugin = yum_cache.YumCache(MagicMock(), conf, br)

    dnf_dir = next(d for d in plugin.cache_dirs if d.host_cache_path.endswith('dnf_cache'))
    assert dnf_dir.host_cache_path == '/var/cache/mock/my-root/dnf_cache'


@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_no_cache_key_lock_in_buildroot_cachedir(mock_file_util):
    """Without cache_key, lock file must be in buildroot.cachedir."""
    br = make_buildroot()
    br.cachedir = '/var/cache/mock/my-root'
    conf = deepcopy(DEFAULT_CONF)

    mock_open = mock.mock_open()
    with patch('builtins.open', mock_open):
        yum_cache.YumCache(MagicMock(), conf, br)

    opened_paths = [c.args[0] for c in mock_open.call_args_list]
    assert any('my-root/yumcache.lock' in p for p in opened_paths), \
        f"lock not in cachedir; opened: {opened_paths}"


# ---------------------------------------------------------------------------
# With cache_key — shared cache behaviour
# ---------------------------------------------------------------------------

@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_cache_key_uses_shared_dir(mock_file_util):
    """With cache_key, host_cache_path must be cache_topdir/yum_cache/{key}/dnf_cache."""
    br = make_buildroot({'cache_topdir': '/var/cache/mock'})
    conf = {**DEFAULT_CONF, 'cache_key': 'centos-stream-10-x86_64'}

    with patch('builtins.open', mock.mock_open()):
        plugin = yum_cache.YumCache(MagicMock(), conf, br)

    dnf_dir = next(d for d in plugin.cache_dirs if d.host_cache_path.endswith('dnf_cache'))
    assert dnf_dir.host_cache_path == \
        '/var/cache/mock/yum_cache/centos-stream-10-x86_64/dnf_cache'


@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_cache_key_lock_in_shared_dir(mock_file_util):
    """With cache_key, lock file must be in the shared cache dir, not buildroot.cachedir."""
    br = make_buildroot({'cache_topdir': '/var/cache/mock'})
    br.cachedir = '/var/cache/mock/my-root'
    conf = {**DEFAULT_CONF, 'cache_key': 'centos-stream-10-x86_64'}

    mock_open = mock.mock_open()
    with patch('builtins.open', mock_open):
        yum_cache.YumCache(MagicMock(), conf, br)

    opened_paths = [c.args[0] for c in mock_open.call_args_list]
    assert any('yum_cache/centos-stream-10-x86_64/yumcache.lock' in p
               for p in opened_paths), f"shared lock not found; opened: {opened_paths}"
    assert not any('my-root/yumcache.lock' in p
                   for p in opened_paths), "lock must not be in buildroot.cachedir"


@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_cache_key_shared_dir_created(mock_file_util):
    """With cache_key, the shared directory must be created via mkdirIfAbsent."""
    br = make_buildroot({'cache_topdir': '/var/cache/mock'})
    conf = {**DEFAULT_CONF, 'cache_key': 'centos-stream-10-x86_64'}

    with patch('builtins.open', mock.mock_open()):
        yum_cache.YumCache(MagicMock(), conf, br)

    created_dirs = [c.args[0] for c in mock_file_util.mkdirIfAbsent.call_args_list]
    assert any('yum_cache/centos-stream-10-x86_64' in d for d in created_dirs), \
        f"shared dir not created; mkdirIfAbsent called with: {created_dirs}"


@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_both_dnf_and_yum_cache_dirs_registered(mock_file_util):
    """Both /var/cache/dnf and /var/cache/yum bind mounts must be added."""
    br = make_buildroot()
    conf = {**DEFAULT_CONF, 'cache_key': 'centos-stream-10-x86_64'}

    with patch('builtins.open', mock.mock_open()):
        yum_cache.YumCache(MagicMock(), conf, br)

    added_srcs = [c.args[0].srcpath for c in br.mounts.add.call_args_list]
    assert any('dnf_cache' in p for p in added_srcs), f"dnf_cache not mounted: {added_srcs}"
    assert any('yum_cache' in p for p in added_srcs), f"yum_cache not mounted: {added_srcs}"


# ---------------------------------------------------------------------------
# Hook registration (both modes)
# ---------------------------------------------------------------------------

@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_hooks_registered(mock_file_util):
    """Plugin must always register preyum, postyum, preinit hooks."""
    for conf in [deepcopy(DEFAULT_CONF), {**DEFAULT_CONF, 'cache_key': 'my-key'}]:
        plugins = MagicMock()
        br = make_buildroot()
        br.cachedir = '/var/cache/mock/root'
        with patch('builtins.open', mock.mock_open()):
            yum_cache.YumCache(plugins, conf, br)
        hook_names = [c.args[0] for c in plugins.add_hook.call_args_list]
        assert 'preyum' in hook_names
        assert 'postyum' in hook_names
        assert 'preinit' in hook_names


# ---------------------------------------------------------------------------
# Two configs, same cache_key — both resolve to same path
# ---------------------------------------------------------------------------

@patch('mockbuild.plugins.yum_cache.mockbuild.file_util')
def test_two_roots_same_cache_key_share_path(mock_file_util):
    """Two buildroots with different cachedir but same cache_key must resolve identical paths."""
    conf = {**DEFAULT_CONF, 'cache_key': 'centos-stream-10-x86_64'}

    br1 = make_buildroot({'cache_topdir': '/var/cache/mock'})
    br1.cachedir = '/var/cache/mock/build-root-1'
    br2 = make_buildroot({'cache_topdir': '/var/cache/mock'})
    br2.cachedir = '/var/cache/mock/build-root-2'

    with patch('builtins.open', mock.mock_open()):
        p1 = yum_cache.YumCache(MagicMock(), deepcopy(conf), br1)
        p2 = yum_cache.YumCache(MagicMock(), deepcopy(conf), br2)

    dnf1 = next(d.host_cache_path for d in p1.cache_dirs if d.host_cache_path.endswith('dnf_cache'))
    dnf2 = next(d.host_cache_path for d in p2.cache_dirs if d.host_cache_path.endswith('dnf_cache'))
    assert dnf1 == dnf2, f"paths differ: {dnf1} != {dnf2}"
