"""Persisted draft inventories and explicit, versioned publishing approval.

No background jobs or asset bytes are kept in the inventory. Files are hashed
only when preparing, approving or claiming an external action.
"""
import hashlib
import json
import time
from pathlib import Path


def registered_artifacts(db, identity):
    key = "session_artifacts:" + str(identity.get("lineage_root_id") or identity["active_session_id"])
    try:
        value = json.loads(db.get_meta(key) or "[]")
    except (ValueError, TypeError):
        value = []
    return value if isinstance(value, list) else []


def register_artifacts(db, identity, artifacts):
    if not isinstance(artifacts, list) or len(artifacts) > 80:
        raise ValueError("Provide at most 80 artifacts")
    entries = {x["path"]: x for x in registered_artifacts(db, identity) if isinstance(x, dict) and x.get("path")}
    for item in artifacts:
        path = Path(item["path"]).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("Artifact must be an existing file")
        entries[str(path)] = {"path": str(path), "name": str(item.get("name") or path.name)[:200], "registeredAt": time.time()}
    result = list(entries.values())[-200:]
    key = "session_artifacts:" + str(identity.get("lineage_root_id") or identity["active_session_id"])
    db.set_meta(key, json.dumps(result))
    return result


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def freeze_review(manifest_path):
    path = Path(manifest_path).expanduser().resolve(strict=True)
    manifest = json.loads(path.read_text())
    run_dir = path.parent
    if manifest.get("version") != 1:
        raise ValueError("Unsupported review manifest version")
    if manifest.get("mode", "publish") not in ("publish", "prepare"):
        raise ValueError("Review mode must be publish or prepare")
    if manifest.get("mode", "publish") == "publish" and manifest.get("requiredFields"):
        raise ValueError("Collect missing inputs before presenting publishing approval")
    actions = manifest.get("actions", [])
    allowed = {"publish_landing", "schedule_buffer", "schedule_mailjet"}
    ids = [a.get("id") for a in actions]
    if len(set(ids)) != len(ids) or any(i not in allowed for i in ids):
        raise ValueError("Review actions must have unique supported IDs")
    for action in actions:
        if not action.get("label") or not action.get("details"):
            raise ValueError("Every action needs a readable label and destination/timing details")
        if action["id"].startswith("schedule_"):
            if not action.get("schedule") or not action.get("destinations"):
                raise ValueError("Scheduling approval requires exact times, timezone and destinations")
            from datetime import datetime
            for schedule in action["schedule"]:
                if schedule == "immediate":
                    continue
                when = datetime.fromisoformat(schedule.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    raise ValueError("Schedule timestamps require a timezone offset")
    files = {str(path)}
    artifacts = []
    for item in manifest.get("artifacts", []):
        target = (run_dir / item["path"]).resolve(strict=True)
        target.relative_to(run_dir)
        files.add(str(target))
        artifacts.append({"path": str(target), "name": item.get("name") or target.name})
    trees = []
    for raw in manifest.get("trees", []):
        target = (run_dir / raw).resolve(strict=True)
        target.relative_to(run_dir)
        if not target.is_dir():
            raise ValueError("Review tree must be a directory")
        trees.append(str(target))
        for file in target.rglob("*"):
            if file.is_file():
                file.resolve().relative_to(run_dir)
                files.add(str(file.resolve()))
    for raw in manifest.get("files", []):
        target = (run_dir / raw).resolve(strict=True)
        target.relative_to(run_dir)
        files.add(str(target))
    if not artifacts or len(files) > 1000:
        raise ValueError("A review needs artifacts and at most 1000 files")
    if "publish_landing" in ids and str(run_dir / "landing") not in trees:
        raise ValueError("Landing approval must include the complete landing directory")
    if any(i.startswith("schedule_") for i in ids):
        if str(run_dir / "posts.json") not in files or str(run_dir / "inputs.json") not in files:
            raise ValueError("Scheduling approval must include posts.json and inputs.json")
    snapshot = {"manifestPath": str(path), "runDir": str(run_dir), "actions": actions,
                "artifacts": artifacts, "trees": trees,
                "files": {file: file_hash(file) for file in sorted(files)},
                "notes": manifest.get("notes", []), "mode": manifest.get("mode", "publish")}
    snapshot["versionHash"] = digest(snapshot)
    return snapshot


def validate_review(review, *, publishing=False):
    try:
        current = freeze_review(review["manifestPath"])
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError("A reviewed file is missing or invalid. Prepare a fresh review.") from exc
    if current["versionHash"] != review["versionHash"]:
        raise ValueError("The assets or launch plan changed. Prepare a fresh review before approving.")
    if publishing and (not review.get("actions") or review.get("mode") != "publish"):
        raise ValueError("This is a draft review, not permission to publish or schedule")
    from datetime import datetime, timezone
    for action in review.get("actions", []):
        for schedule in action.get("schedule", []):
            if schedule == "immediate":
                continue
            if datetime.fromisoformat(schedule.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                raise ValueError("A scheduled time has passed. Prepare a fresh launch plan.")
    return current


def apply_recorded_review_authorization(conn, run_id, manifest_path, approved_actions, source_text, *, actor="human:recorded-answer"):
    """Apply explicit authorization already supplied with an earlier review.

    The caller interprets the user's words; a time field alone is never inferred
    to be approval. Require the exact recorded answer and unchanged reviewed
    artifacts. This keeps consent separate from replaceable worker result prompts.
    """
    from elevate_cli.data.dispatch import _run_lookup, _decode_json, _encode_json, now_iso
    conn.execute("SELECT id FROM admin_action_runs WHERE id=? FOR UPDATE", (run_id,)).fetchone()
    row = _run_lookup(conn, run_id)
    if row["status"] not in ("waiting_human", "running", "queued"):
        raise ValueError("Authorization must belong to an active review run")
    payload = _decode_json(row["payload_json"]) or {}
    prior = payload.get("resumeExistingArtifacts", {})
    answers = prior.get("providedAnswers", {})
    normalize = lambda text: " ".join(str(text).split())
    if not source_text or normalize(source_text) not in [normalize(v) for v in answers.values()]:
        raise ValueError("Authorization must cite the exact recorded human answer")
    review = freeze_review(manifest_path)
    validate_review(review, publishing=True)
    if not approved_actions or set(approved_actions) != {a["id"] for a in review["actions"]}:
        raise ValueError("Only the explicitly authorized actions may be in this package")
    original_files = (prior.get("reviewPackage") or {}).get("files", {})
    for artifact in review["artifacts"]:
        path = artifact["path"]
        if path in original_files and review["files"][path] != original_files[path]:
            raise ValueError("A reviewed asset changed; existing consent does not cover it")
    old_prompt = _decode_json(row["human_prompt_json"]) or {}
    if old_prompt.get("actionClaims"):
        raise ValueError("An action already started; reconcile its provider result before retrying")
    now = now_iso()
    decision = {"approved": True, "actor": actor, "decidedAt": now,
                "versionHash": review["versionHash"], "actions": list(approved_actions),
                "sourceText": source_text, "source": "previously-submitted-human-answer"}
    ledger = payload.setdefault("reviewAuthorizations", [])
    if not any(x.get("versionHash") == review["versionHash"] for x in ledger):
        ledger.append({**decision, "reviewPackage": review})
    payload["resumeExistingArtifacts"] = {
        "instruction": "The human already authorized the listed non-video actions. Execute these existing assets without asking again. Video is a separate review. Technical/provider failures are execution blockers, not missing approval.",
        "reviewPackage": review, "decision": decision, "providedAnswers": answers, "runId": run_id}
    prompt = {"reviewPackage": review, "decision": decision, "sessionId": payload.get("reviewSessionId"),
              "title": "Approved marketing launch", "requiredFields": []}
    conn.execute("""UPDATE admin_action_runs SET status='running', payload_json=?, human_prompt_json=?,
                    result_idempotency_key=NULL, result_json=NULL, error_message=NULL,
                    completed_at=NULL, updated_at=? WHERE id=?""",
                 (_encode_json(payload), _encode_json(prompt), now, run_id))
    return {"runId": run_id, "status": "running", "reviewPackage": review, "decision": decision}


def preserve_review_consent(payload, existing_prompt, incoming_prompt, status):
    """Keep recorded consent when a worker replaces its result/human prompt."""
    resume = payload.get("resumeExistingArtifacts") or {}
    review = (existing_prompt or {}).get("reviewPackage") or resume.get("reviewPackage")
    decision = (existing_prompt or {}).get("decision") or resume.get("decision") or {}
    if not review or not decision.get("approved"):
        return incoming_prompt, status
    ledger = payload.setdefault("reviewAuthorizations", [])
    if not any(item.get("versionHash") == decision.get("versionHash") for item in ledger):
        ledger.append({**decision, "reviewPackage": review})
    if status != "waiting_human":
        return incoming_prompt, status
    incoming = dict(incoming_prompt or {})
    candidate = incoming.get("reviewPackage")
    # A new concrete version can still need approval. A generic repeat ask
    # cannot erase an existing launch authorization or reopen its popup.
    if review.get("mode") == "publish" and decision.get("actions"):
        same = candidate and candidate.get("versionHash") == review.get("versionHash")
        generic = not candidate and not incoming.get("requiredFields")
        if same or generic:
            incoming.update(reviewPackage=review, decision=decision)
            incoming["message"] = "Approval is already recorded. Continue the authorized actions or reconcile the provider blocker."
            return incoming, "waiting_external"
    return incoming_prompt, status
