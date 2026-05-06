from elevate_cli.harness.browser_use_harness import BrowserUseHarness


def test_page_info_parses_last_json_line(monkeypatch):
    monkeypatch.setattr(BrowserUseHarness, "available", lambda self: True)
    monkeypatch.setattr(
        BrowserUseHarness,
        "run_code",
        lambda self, code: '[browser-harness] update available\n{"url":"https://example.com","title":"Example"}',
    )

    assert BrowserUseHarness().page_info() == {"url": "https://example.com", "title": "Example"}
