from run_agent import _is_compression_threshold_pinned


def test_missing_threshold_uses_unpinned_default_policy():
    assert _is_compression_threshold_pinned({}) is False


def test_platform_default_threshold_is_not_user_pinned():
    assert _is_compression_threshold_pinned({"threshold": 0.85}) is False
    assert _is_compression_threshold_pinned({"threshold": "0.85"}) is False


def test_custom_threshold_is_user_pinned():
    assert _is_compression_threshold_pinned({"threshold": 0.7}) is True
    assert _is_compression_threshold_pinned({"threshold": 0.9}) is True
