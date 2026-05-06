import pytest

from elevate_cli.harness.browser_cdp import BrowserCDPWorker, BrowserTab, BrowserWorkerError


def test_select_tab_by_url(monkeypatch):
    worker = BrowserCDPWorker()
    monkeypatch.setattr(
        worker,
        "list_tabs",
        lambda: [
            BrowserTab(id="1", title="Chrome", url="chrome://intro", type="page"),
            BrowserTab(id="2", title="Agent Centre", url="https://www.expagentcentre.ca/", type="page"),
        ],
    )

    tab = worker.select_tab("expagentcentre.ca")
    assert tab is not None
    assert tab.id == "2"


def test_allowlist_rejects_other_domains():
    worker = BrowserCDPWorker(allowed_domains=["expagentcentre.ca"])
    with pytest.raises(BrowserWorkerError):
        worker._assert_allowed("https://accounts.google.com/signin")


def test_allowlist_accepts_subdomains():
    worker = BrowserCDPWorker(allowed_domains=["example.com"])
    worker._assert_allowed("https://docs.example.com/page")
