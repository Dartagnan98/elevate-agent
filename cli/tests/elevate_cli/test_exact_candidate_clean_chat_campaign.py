from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "cli/scripts/exact_candidate_clean_chat_campaign.py"


def _load_campaign_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "exact_candidate_clean_chat_campaign",
        SCRIPT_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeRpc:
    def __init__(
        self,
        *,
        final_override: str | None = None,
        include_delta: bool = True,
        terminal_status: str = "complete",
        completed: bool = True,
        include_usage: bool = True,
        duplicate_terminal_status: str = "complete",
        tool_activity: bool = False,
        wrong_resumed_user_text: bool = False,
        duplicate_tool_activity: bool = False,
        extra_activity_type: str | None = None,
        assistant_message_id_override: str | None = None,
        close_confirmed: bool = True,
        resume_persisted_id_override: str | None = None,
        duplicate_identity_mismatch: bool = False,
    ) -> None:
        self.events: list[dict[str, Any]] = []
        self.final_override = final_override
        self.include_delta = include_delta
        self.terminal_status = terminal_status
        self.completed = completed
        self.include_usage = include_usage
        self.duplicate_terminal_status = duplicate_terminal_status
        self.tool_activity = tool_activity
        self.wrong_resumed_user_text = wrong_resumed_user_text
        self.duplicate_tool_activity = duplicate_tool_activity
        self.extra_activity_type = extra_activity_type
        self.assistant_message_id_override = assistant_message_id_override
        self.close_confirmed = close_confirmed
        self.resume_persisted_id_override = resume_persisted_id_override
        self.duplicate_identity_mismatch = duplicate_identity_mismatch
        self.create_count = 0
        self.config_values: list[str] = []
        self.persisted: dict[str, dict[str, str]] = {}
        self.resumed: dict[str, str] = {}
        self.prompts: list[str] = []

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        _timeout: float,
    ) -> dict[str, Any]:
        if method == "session.create":
            self.create_count += 1
            return {
                "session_id": f"live-{self.create_count}",
                "persisted_session_id": f"persisted-{self.create_count}",
            }
        if method == "config.set":
            self.config_values.append(str(params.get("value") or ""))
            return {"key": params.get("key"), "value": params.get("value")}
        if method == "session.close":
            return {"closed": self.close_confirmed}
        if method == "session.resume":
            persisted_id = str(params["session_id"])
            item = self.persisted[persisted_id]
            resumed_id = persisted_id.replace("persisted-", "resumed-")
            self.resumed[resumed_id] = persisted_id
            messages: list[dict[str, Any]] = [
                {
                    "role": "user",
                    "message_id": item["user_message_id"],
                    "text": (
                        "wrong fixture user input"
                        if self.wrong_resumed_user_text
                        else item["user_text"]
                    ),
                },
                {
                    "role": "assistant",
                    "message_id": item["assistant_message_id"],
                    "status": self.terminal_status,
                    "text": item["final_text"],
                },
            ]
            if self.tool_activity:
                messages.append({"role": "tool", "text": "fixture tool output"})
            return {
                "session_id": resumed_id,
                "persisted_session_id": (
                    self.resume_persisted_id_override or persisted_id
                ),
                "messages": messages,
            }
        if method != "prompt.submit":
            raise AssertionError(f"unexpected method: {method}")

        session_id = str(params["session_id"])
        if session_id in self.resumed:
            if self.duplicate_tool_activity:
                self.events.append(
                    {
                        "type": "tool.start",
                        "session_id": session_id,
                        "payload": {"tool_call_id": "duplicate-tool"},
                    }
                )
            if self.duplicate_terminal_status == "complete":
                persisted_id = self.resumed[session_id]
                item = self.persisted[persisted_id]
                return {
                    "status": "duplicate",
                    "duplicate": True,
                    "terminal_status": "complete",
                    "correlation_id": (
                        "wrong-id"
                        if self.duplicate_identity_mismatch
                        else item["user_message_id"]
                    ),
                    "user_message_id": item["user_message_id"],
                    "message_id": item["assistant_message_id"],
                }
            return {
                "status": "duplicate",
                "terminal_status": self.duplicate_terminal_status,
            }

        prompt = str(params["text"])
        self.prompts.append(prompt)
        expected = prompt.split("Reply exactly: ", 1)[1]
        final_text = expected if self.final_override is None else self.final_override
        number = session_id.rsplit("-", 1)[1]
        persisted_id = f"persisted-{number}"
        user_message_id = str(params["user_message_id"])
        assistant_message_id = (
            self.assistant_message_id_override or f"assistant-{number}"
        )
        self.persisted[persisted_id] = {
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "user_text": prompt,
            "final_text": final_text,
        }
        for event_type in ("message.start", "message.delta", "message.complete"):
            if event_type == "message.delta" and not self.include_delta:
                continue
            payload: dict[str, Any] = {"message_id": assistant_message_id}
            if event_type == "message.complete":
                payload.update(
                    {
                        "status": self.terminal_status,
                        "completed": self.completed,
                        "text": final_text,
                    }
                )
                if self.include_usage:
                    payload["usage"] = {"input_tokens": 1, "output_tokens": 1}
            self.events.append(
                {"type": event_type, "session_id": session_id, "payload": payload}
            )
        if self.tool_activity:
            self.events.append(
                {
                    "type": "tool.start",
                    "session_id": session_id,
                    "payload": {"tool_call_id": "fixture-tool"},
                }
            )
        if self.extra_activity_type:
            self.events.append(
                {
                    "type": self.extra_activity_type,
                    "session_id": session_id,
                    "payload": {},
                }
            )
        return {
            "status": "streaming",
            "user_message_id": user_message_id,
            "message_id": assistant_message_id,
        }

    async def wait_for_event(
        self,
        event_type: str,
        session_id: str,
        cursor: int,
        _timeout: float,
    ) -> dict[str, Any]:
        return next(
            event
            for event in self.events[cursor:]
            if event.get("type") == event_type and event.get("session_id") == session_id
        )

    def events_since(self, cursor: int, session_id: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events[cursor:]
            if not session_id or event.get("session_id") == session_id
        ]


def _binding(campaign: ModuleType):
    return campaign.CandidateBinding(
        candidate_id="c" * 64,
        source_receipt_id="d" * 64,
        architecture="arm64",
        receipt_sha256="a" * 64,
        app_version="1.2.67",
        app_bundle_manifest_sha256="b" * 64,
    )


def _run(campaign: ModuleType, rpc: FakeRpc, *, count: int = 1) -> dict[str, Any]:
    return asyncio.run(
        campaign.run_campaign_with_rpc(
            rpc=rpc,
            binding=_binding(campaign),
            release_metadata={"channel": "beta", "app_bundle_name": "Elevate Beta.app"},
            installed_app_name="Elevate Beta.app",
            campaign_id="fixture-campaign",
            dashboard_port=5174,
            count=count,
            timeout=1.0,
            runtime_binding={
                "method": "installed-dashboard-asset-parity-v1",
                "served_assets_match_installed": True,
                "index_asset_bytes_sha256": "e" * 64,
                "chat_asset_bytes_sha256": "f" * 64,
            },
        )
    )


def test_default_is_twenty_bounded_chats() -> None:
    campaign = _load_campaign_script()

    args = campaign.parse_args(
        [
            "--candidate-receipt",
            "receipt.json",
            "--installed-app",
            "Elevate Beta.app",
            "--candidate-architecture",
            "arm64",
        ]
    )

    assert args.count == 20
    with pytest.raises(SystemExit):
        campaign.parse_args(
            [
                "--candidate-receipt",
                "receipt.json",
                "--installed-app",
                "Elevate Beta.app",
                "--candidate-architecture",
                "arm64",
                "--count",
                "101",
            ]
        )
    for timeout in ("nan", "inf", "-inf"):
        with pytest.raises(SystemExit):
            campaign.parse_args(
                [
                    "--candidate-receipt",
                    "receipt.json",
                    "--installed-app",
                    "Elevate Beta.app",
                    "--candidate-architecture",
                    "arm64",
                    "--timeout",
                    timeout,
                ]
            )


def test_candidate_binding_invokes_exact_verifier_once(monkeypatch, tmp_path) -> None:
    campaign = _load_campaign_script()
    repo = tmp_path / "repo"
    verifier = repo / "desktop/scripts/candidate-receipt.js"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("", encoding="utf-8")
    receipt = tmp_path / "candidate-receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    app = tmp_path / "Elevate Beta.app"
    app.mkdir()
    calls: list[list[str]] = []
    payload = {
        "candidate_id": "c" * 64,
        "source_receipt_id": "d" * 64,
        "candidate_architecture": "arm64",
        "receipt_sha256": "a" * 64,
        "app_version": "1.2.67",
        "app_bundle_manifest_sha256": "b" * 64,
    }

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(campaign.subprocess, "run", fake_run)

    binding = campaign.verify_candidate_binding(
        repo_root=repo,
        receipt_path=receipt,
        installed_app=app,
        architecture="arm64",
    )

    assert binding.candidate_id == "c" * 64
    assert len(calls) == 1
    assert calls[0][2] == "verify-app"
    assert calls[0][-2:] == ["--arch", "arm64"]


def test_release_metadata_rejects_receipt_changed_after_binding(tmp_path) -> None:
    campaign = _load_campaign_script()
    receipt = tmp_path / "candidate-receipt.json"
    receipt.write_text(json.dumps({"candidate_id": "c" * 64}), encoding="utf-8")

    with pytest.raises(campaign.CampaignFailure, match="candidate_receipt_changed"):
        campaign.load_release_metadata(
            receipt,
            campaign.CandidateBinding(
                candidate_id="c" * 64,
                source_receipt_id="d" * 64,
                architecture="arm64",
                receipt_sha256="0" * 64,
                app_version="1.2.67",
                app_bundle_manifest_sha256="b" * 64,
            ),
        )


def test_runtime_binding_matches_served_assets_to_verified_app(
    monkeypatch, tmp_path
) -> None:
    campaign = _load_campaign_script()
    app = tmp_path / "Elevate Beta.app"
    web_dist = app / "Contents/Resources/cli/elevate_cli/web_dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    index_asset = "index-fixture123.js"
    chat_asset = "ChatPage-fixture456.js"
    chat_asset_body = "fixture chat chunk bytes"
    (web_dist / "index.html").write_text(
        f'<script type="module" src="/assets/{index_asset}"></script>',
        encoding="utf-8",
    )
    (assets / index_asset).write_text(chat_asset, encoding="utf-8")
    (assets / chat_asset).write_text(chat_asset_body, encoding="utf-8")

    class FakeResponse:
        def __init__(self, body: str):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args) -> bytes:
            return self.body.encode("utf-8")

    def fake_urlopen(request, **_kwargs):
        if "/chat?" in request.full_url:
            return FakeResponse(
                f'__ELEVATE_SESSION_TOKEN__="fixture-token" '
                f'<script type="module" src="/assets/{index_asset}"></script>'
            )
        if request.full_url.endswith(index_asset):
            return FakeResponse(chat_asset)
        return FakeResponse(chat_asset_body)

    monkeypatch.setattr(campaign.urllib.request, "urlopen", fake_urlopen)

    token, binding = campaign.verify_runtime_binding(
        port=5174,
        timeout=1.0,
        campaign_id="fixture-campaign",
        installed_app=app,
    )

    assert token == "fixture-token"
    assert binding == {
        "method": "installed-dashboard-asset-parity-v1",
        "served_assets_match_installed": True,
        "index_asset_bytes_sha256": campaign.sha256_text(chat_asset),
        "chat_asset_bytes_sha256": campaign.sha256_text(chat_asset_body),
    }

    def mismatched_urlopen(request, **kwargs):
        if request.full_url.endswith(chat_asset):
            return FakeResponse("same name, wrong served bytes")
        return fake_urlopen(request, **kwargs)

    monkeypatch.setattr(campaign.urllib.request, "urlopen", mismatched_urlopen)
    with pytest.raises(
        campaign.CampaignFailure, match="candidate_runtime_asset_mismatch"
    ):
        campaign.verify_runtime_binding(
            port=5174,
            timeout=1.0,
            campaign_id="fixture-campaign",
            installed_app=app,
        )


def test_two_turn_campaign_is_fresh_read_only_and_content_free() -> None:
    campaign = _load_campaign_script()
    rpc = FakeRpc()

    evidence = _run(campaign, rpc, count=2)

    assert evidence["ok"] is True
    assert evidence["summary"] == {
        "attempted": 2,
        "passed": 2,
        "failed": 0,
        "failure_codes": {},
    }
    assert rpc.create_count == 2
    assert rpc.config_values == ["plan", "plan"]
    assert evidence["configuration"]["profile_cleanliness"] == "unverified_by_runner"
    assert evidence["runtime_binding"]["served_assets_match_installed"] is True
    assert len({turn["persisted_session_id"] for turn in evidence["turns"]}) == 2
    assert all(
        turn["duplicate_terminal_status"] == "complete" for turn in evidence["turns"]
    )
    assert all(turn["event_counts"]["message.delta"] == 1 for turn in evidence["turns"])
    assert (
        campaign.evidence_integrity(evidence) == evidence["evidence_integrity_sha256"]
    )
    campaign.assert_content_free_evidence(evidence)
    serialized = json.dumps(evidence)
    assert "Reply exactly:" not in serialized
    assert "clean chat 01 ok" not in serialized


@pytest.mark.parametrize(
    ("rpc", "failure_code"),
    [
        (FakeRpc(final_override="(empty)"), "empty_output"),
        (FakeRpc(completed=False), "terminal_not_complete"),
        (FakeRpc(include_usage=False), "terminal_usage_missing"),
        (FakeRpc(include_delta=False), "streaming_missing"),
        (
            FakeRpc(duplicate_terminal_status="pending"),
            "duplicate_terminal_receipt_missing",
        ),
        (FakeRpc(tool_activity=True), "read_only_activity_detected"),
        (
            FakeRpc(extra_activity_type="delegate.start"),
            "read_only_activity_detected",
        ),
        (FakeRpc(wrong_resumed_user_text=True), "resumed_transcript_mismatch"),
        (FakeRpc(duplicate_tool_activity=True), "duplicate_prompt_reexecuted"),
        (FakeRpc(close_confirmed=False), "session_close_not_confirmed"),
        (
            FakeRpc(resume_persisted_id_override="wrong-persisted"),
            "resume_persisted_identity_mismatch",
        ),
        (
            FakeRpc(duplicate_identity_mismatch=True),
            "duplicate_receipt_identity_mismatch",
        ),
    ],
)
def test_campaign_rejects_false_success_paths(rpc: FakeRpc, failure_code: str) -> None:
    campaign = _load_campaign_script()

    evidence = _run(campaign, rpc)

    assert evidence["ok"] is False
    assert evidence["summary"]["failure_codes"] == {failure_code: 1}
    assert evidence["turns"][0]["ok"] is False
    assert evidence["turns"][0]["failure_code"] == failure_code


def test_untrusted_terminal_status_is_not_copied_into_evidence() -> None:
    campaign = _load_campaign_script()
    untrusted_status = "complete raw-client-content"

    evidence = _run(campaign, FakeRpc(terminal_status=untrusted_status))

    assert evidence["ok"] is False
    assert evidence["turns"][0]["terminal_status"] is None
    assert untrusted_status not in json.dumps(evidence)


def test_untrusted_gateway_id_is_rejected_without_evidence_leak() -> None:
    campaign = _load_campaign_script()
    untrusted_id = "assistant raw-client-content"

    evidence = _run(
        campaign,
        FakeRpc(assistant_message_id_override=untrusted_id),
    )

    assert evidence["ok"] is False
    assert evidence["turns"][0]["failure_code"] == "assistant_message_id_invalid"
    assert evidence["turns"][0]["assistant_message_id"] is None
    assert untrusted_id not in json.dumps(evidence)


def test_binding_hashes_must_be_sha256_values() -> None:
    campaign = _load_campaign_script()
    binding = _binding(campaign)
    invalid = campaign.CandidateBinding(
        **{**binding.__dict__, "receipt_sha256": "not-a-hash"}
    )

    with pytest.raises(
        campaign.CampaignFailure, match="candidate_receipt_hash_invalid"
    ):
        campaign.validate_binding(invalid)


def test_evidence_write_is_integrity_hashed_owner_only_and_immutable(tmp_path) -> None:
    campaign = _load_campaign_script()
    evidence = _run(campaign, FakeRpc())
    output = tmp_path / "evidence.json"

    campaign.write_evidence(output, evidence)

    document = json.loads(output.read_text(encoding="utf-8"))
    assert (
        campaign.evidence_integrity(document) == document["evidence_integrity_sha256"]
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "Reply exactly:" not in output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        campaign.write_evidence(output, evidence)


def test_failed_evidence_write_never_exposes_partial_destination(
    monkeypatch,
    tmp_path,
) -> None:
    campaign = _load_campaign_script()
    evidence = _run(campaign, FakeRpc())
    output = tmp_path / "evidence.json"
    real_write = campaign.os.write
    calls = 0

    def failing_write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:7])
        raise OSError("fixture interrupted write")

    monkeypatch.setattr(campaign.os, "write", failing_write)

    with pytest.raises(OSError, match="fixture interrupted write"):
        campaign.write_evidence(output, evidence)

    assert not output.exists()
    assert list(tmp_path.glob(".evidence.json.*.tmp")) == []


def test_release_metadata_accepts_verified_receipt(tmp_path) -> None:
    campaign = _load_campaign_script()
    payload = {
        "candidate_id": "c" * 64,
        "release": {
            "channel": "beta",
            "profile": {"appBundleName": "Elevate Beta.app", "preferredPort": 5174},
        },
    }
    receipt = tmp_path / "candidate-receipt.json"
    receipt_bytes = json.dumps(payload).encode("utf-8")
    receipt.write_bytes(receipt_bytes)
    binding = _binding(campaign)
    binding = campaign.CandidateBinding(
        **{
            **binding.__dict__,
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        }
    )

    metadata = campaign.load_release_metadata(receipt, binding)

    assert metadata == {
        "channel": "beta",
        "app_bundle_name": "Elevate Beta.app",
        "preferred_port": 5174,
    }
