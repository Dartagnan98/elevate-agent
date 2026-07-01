"""WhatsApp channel bridge routes."""

import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from elevate_constants import get_elevate_home
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from elevate_cli.config import get_env_value, load_config, save_env_value

RequireToken = Callable[[Request], None]


def _strip(value: Any) -> str:
    return str(value or "").strip()


def _whatsapp_enabled() -> bool:
    env_value = (get_env_value("WHATSAPP_ENABLED") or "").strip().lower()
    if env_value in {"true", "1", "yes"}:
        return True
    try:
        platforms = load_config().get("platforms", {})
        whatsapp = platforms.get("whatsapp", {}) if isinstance(platforms, dict) else {}
        if not isinstance(whatsapp, dict):
            return False
        enabled = whatsapp.get("enabled")
        if isinstance(enabled, str):
            return enabled.strip().lower() in {"true", "1", "yes"}
        return bool(enabled)
    except Exception:
        return False


def register_whatsapp_routes(
    router: APIRouter,
    *,
    require_token: RequireToken,
    elevate_repo_root_func: Callable[[], Path],
) -> None:
    @router.post("/api/channels/whatsapp/configure")
    async def configure_whatsapp(request: Request):
        """Save WhatsApp mode + allowlist. Pairing streams separately."""
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        mode = _strip(body.get("mode"))  # "bot" or "self-chat"
        allowed = _strip(body.get("allowed_users"))
        if mode and mode not in {"bot", "self-chat"}:
            raise HTTPException(status_code=400, detail="mode must be 'bot' or 'self-chat'")
        if mode:
            save_env_value("WHATSAPP_MODE", mode)
            save_env_value("WHATSAPP_ENABLED", "true")
        if allowed:
            save_env_value("WHATSAPP_ALLOWED_USERS", allowed.replace(" ", ""))

        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        has_node_modules = (bridge_dir / "node_modules").exists()
        bridge_present = (bridge_dir / "bridge.js").exists()
        session_dir = get_elevate_home() / "whatsapp" / "session"
        paired = (session_dir / "creds.json").exists()

        return {
            "ok": True,
            "mode": get_env_value("WHATSAPP_MODE") or "",
            "enabled": _whatsapp_enabled(),
            "allowedUsers": get_env_value("WHATSAPP_ALLOWED_USERS") or "",
            "bridgePresent": bridge_present,
            "bridgeInstalled": has_node_modules,
            "paired": paired,
        }

    @router.post("/api/channels/whatsapp/install")
    async def install_whatsapp_bridge(request: Request):
        """Run ``npm install`` inside the WhatsApp bridge directory."""
        require_token(request)
        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        if not (bridge_dir / "bridge.js").exists():
            raise HTTPException(status_code=404, detail=f"bridge.js not found at {bridge_dir}")

        npm = shutil.which("npm")
        if not npm:
            raise HTTPException(
                status_code=400,
                detail="npm not on PATH — install Node.js first (https://nodejs.org/)",
            )

        try:
            # npm install can take minutes — run it off the event loop so the
            # single-worker dashboard stays responsive to every other request.
            proc = await asyncio.to_thread(
                subprocess.run,
                [npm, "install", "--no-fund", "--no-audit", "--progress=false"],
                cwd=str(bridge_dir),
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="npm install timed out after 10 minutes")

        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or "").strip().splitlines()[-30:]) or "(no output)"
            raise HTTPException(status_code=500, detail=f"npm install failed:\n{tail}")

        return {
            "ok": True,
            "installed": (bridge_dir / "node_modules").exists(),
        }

    @router.get("/api/channels/whatsapp/status")
    async def whatsapp_status():
        """Lightweight status: is bridge installed, has session been paired."""
        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        session_dir = get_elevate_home() / "whatsapp" / "session"
        return {
            "bridgePresent": (bridge_dir / "bridge.js").exists(),
            "bridgeInstalled": (bridge_dir / "node_modules").exists(),
            "mode": get_env_value("WHATSAPP_MODE") or "",
            "enabled": _whatsapp_enabled(),
            "paired": (session_dir / "creds.json").exists(),
            "allowedUsers": get_env_value("WHATSAPP_ALLOWED_USERS") or "",
        }

    @router.get("/api/channels/whatsapp/pair/stream")
    async def whatsapp_pair_stream(request: Request):
        """Server-Sent Events stream of WhatsApp pairing progress."""
        require_token(request)
        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        bridge_script = bridge_dir / "bridge.js"
        if not bridge_script.exists():
            raise HTTPException(status_code=404, detail="bridge.js not found")
        if not (bridge_dir / "node_modules").exists():
            raise HTTPException(
                status_code=400,
                detail="WhatsApp bridge dependencies not installed — call /api/channels/whatsapp/install first",
            )
        node = shutil.which("node")
        if not node:
            raise HTTPException(status_code=400, detail="node not on PATH")

        session_dir = get_elevate_home() / "whatsapp" / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        # Re-pairing: clear stale session so Baileys emits a fresh QR.
        creds = session_dir / "creds.json"
        if creds.exists():
            try:
                shutil.rmtree(session_dir, ignore_errors=True)
                session_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        async def event_stream():
            proc = await asyncio.create_subprocess_exec(
                node,
                str(bridge_script),
                "--pair-only",
                "--qr-json",
                "--session",
                str(session_dir),
                cwd=str(bridge_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def kill_if_disconnected():
                while True:
                    if await request.is_disconnected():
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        return
                    await asyncio.sleep(1.0)

            watcher = asyncio.create_task(kill_if_disconnected())
            try:
                assert proc.stdout is not None
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    # Only forward our JSON lines; ignore Baileys chatter.
                    if text.startswith("{") and text.endswith("}"):
                        try:
                            payload = json.loads(text)
                        except Exception:
                            yield f"data: {text}\n\n"
                            continue
                        # When the bridge sends a raw QR string, render it to
                        # a data URL server-side so the browser can drop it
                        # into an <img> tag without a JS QR library.
                        if payload.get("event") == "qr" and payload.get("qr"):
                            try:
                                import qrcode  # type: ignore[import-not-found]

                                img = qrcode.make(payload["qr"], box_size=6, border=2)
                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                payload["dataUrl"] = (
                                    "data:image/png;base64,"
                                    + base64.b64encode(buf.getvalue()).decode("ascii")
                                )
                            except Exception:
                                # Browser can still render the raw QR with its
                                # own library if it ever wants to.
                                pass
                        yield f"data: {json.dumps(payload)}\n\n"
                rc = await proc.wait()
                yield f"data: {json.dumps({'event': 'exit', 'code': rc})}\n\n"
            finally:
                watcher.cancel()
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
