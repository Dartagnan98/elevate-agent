"""Tests for Elevate gateway launchd start reliability."""

from types import SimpleNamespace

import pytest

import elevate_cli.gateway as gateway_cli


def test_launchd_start_retries_when_verification_does_not_show_running(tmp_path, monkeypatch):
    plist_path = tmp_path / "ai.elevate.gateway.plist"
    plist_path.write_text(gateway_cli.generate_launchd_plist(), encoding="utf-8")
    label = gateway_cli.get_launchd_label()
    domain = gateway_cli._launchd_domain()
    target = f"{domain}/{label}"
    calls = []
    print_count = 0

    def fake_run(cmd, check=False, **kwargs):
        nonlocal print_count
        calls.append(cmd)
        if cmd == ["launchctl", "print", target]:
            print_count += 1
            if print_count == 1:
                return SimpleNamespace(returncode=0, stdout="state = waiting\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="state = running\n\tpid = 123\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gateway_cli, "get_launchd_plist_path", lambda: plist_path)
    monkeypatch.setattr(gateway_cli.subprocess, "run", fake_run)

    gateway_cli.launchd_start()

    assert calls == [
        ["launchctl", "kickstart", target],
        ["launchctl", "print", target],
        ["launchctl", "list", label],
        ["launchctl", "bootstrap", domain, str(plist_path)],
        ["launchctl", "kickstart", target],
        ["launchctl", "print", target],
    ]


def test_launchd_start_exits_when_verification_still_fails(tmp_path, monkeypatch):
    plist_path = tmp_path / "ai.elevate.gateway.plist"
    plist_path.write_text(gateway_cli.generate_launchd_plist(), encoding="utf-8")
    label = gateway_cli.get_launchd_label()
    target = f"{gateway_cli._launchd_domain()}/{label}"

    def fake_run(cmd, check=False, **kwargs):
        if cmd == ["launchctl", "print", target]:
            return SimpleNamespace(returncode=0, stdout="state = waiting\n", stderr="")
        if cmd == ["launchctl", "list", label]:
            return SimpleNamespace(returncode=1, stdout="", stderr="Could not find service")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gateway_cli, "get_launchd_plist_path", lambda: plist_path)
    monkeypatch.setattr(gateway_cli.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        gateway_cli.launchd_start()

    assert exc.value.code == 1


def test_launchd_install_rebootstraps_unloaded_current_plist(tmp_path, monkeypatch):
    """Current plist on disk but job booted out of launchd must re-bootstrap.

    Reproduces the desktop auto-update incident: Squirrel ShipIt SIGTERM'd the
    gateway and the launchd job ended up fully unloaded ("Could not find
    service") while the plist file survived. The old `gateway install` printed
    "Service already installed" and returned — leaving Telegram/cron dead.
    """
    plist_path = tmp_path / "ai.elevate.gateway.plist"
    plist_path.write_text(gateway_cli.generate_launchd_plist(), encoding="utf-8")
    label = gateway_cli.get_launchd_label()
    domain = gateway_cli._launchd_domain()
    target = f"{domain}/{label}"
    calls = []
    bootstrapped = False

    def fake_run(cmd, check=False, **kwargs):
        nonlocal bootstrapped
        calls.append(cmd)
        if cmd[:2] == ["launchctl", "bootstrap"]:
            bootstrapped = True
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd == ["launchctl", "print", target]:
            if bootstrapped:
                return SimpleNamespace(
                    returncode=0, stdout="state = running\n\tpid = 99\n", stderr=""
                )
            return SimpleNamespace(returncode=113, stdout="", stderr="Could not find service")
        if cmd == ["launchctl", "list", label]:
            return SimpleNamespace(returncode=113, stdout="", stderr="Could not find service")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gateway_cli, "get_launchd_plist_path", lambda: plist_path)
    monkeypatch.setattr(gateway_cli.subprocess, "run", fake_run)

    gateway_cli.launchd_install()

    assert ["launchctl", "bootstrap", domain, str(plist_path)] in calls
    assert ["launchctl", "kickstart", target] in calls
    # The plist itself was current — it must not be rewritten or booted out.
    assert ["launchctl", "bootout", target] not in calls


def test_launchd_install_silent_noop_when_current_and_running(tmp_path, monkeypatch):
    """Healthy service (current plist + loaded + running) must not be touched."""
    plist_path = tmp_path / "ai.elevate.gateway.plist"
    plist_path.write_text(gateway_cli.generate_launchd_plist(), encoding="utf-8")
    label = gateway_cli.get_launchd_label()
    target = f"{gateway_cli._launchd_domain()}/{label}"
    calls = []

    def fake_run(cmd, check=False, **kwargs):
        calls.append(cmd)
        if cmd == ["launchctl", "print", target]:
            return SimpleNamespace(
                returncode=0, stdout="state = running\n\tpid = 4242\n", stderr=""
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gateway_cli, "get_launchd_plist_path", lambda: plist_path)
    monkeypatch.setattr(gateway_cli.subprocess, "run", fake_run)

    gateway_cli.launchd_install()

    mutating = [c for c in calls if c[1] in ("bootstrap", "kickstart", "bootout")]
    assert mutating == []
