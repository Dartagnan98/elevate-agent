from __future__ import annotations


def test_repeated_warning_throttle_summarizes_suppressed_logs(monkeypatch):
    from elevate_cli import composio_inbound

    calls = []
    times = iter([0.0, 1.0, 2.0, 601.0])

    composio_inbound._warning_state.clear()
    monkeypatch.setattr(composio_inbound.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        composio_inbound._log,
        "warning",
        lambda template, *args: calls.append((template, args)),
    )

    key = ("execute_tool", "gmail", "acct", "slug", "HTTP 422")
    for _ in range(4):
        composio_inbound._warn_repeating(key, "failed %s", "HTTP 422")

    assert calls == [
        ("failed %s", ("HTTP 422",)),
        (
            "failed %s (suppressed %d repeats over %.0fs)",
            ("HTTP 422", 2, 601.0),
        ),
    ]


def test_repeated_warning_throttle_omits_empty_suppression_summary(monkeypatch):
    from elevate_cli import composio_inbound

    calls = []
    times = iter([0.0, 601.0])

    composio_inbound._warning_state.clear()
    monkeypatch.setattr(composio_inbound.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        composio_inbound._log,
        "warning",
        lambda template, *args: calls.append((template, args)),
    )

    key = ("execute_tool", "gmail", "acct", "slug", "HTTP 422")
    for _ in range(2):
        composio_inbound._warn_repeating(key, "failed %s", "HTTP 422")

    assert calls == [
        ("failed %s", ("HTTP 422",)),
        ("failed %s", ("HTTP 422",)),
    ]
