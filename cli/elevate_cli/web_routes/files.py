"""File preview and upload routes for the dashboard."""

import logging
import mimetypes
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from elevate_cli.config import get_elevate_home


_PREVIEWABLE_SUFFIXES = {
    ".csv",
    ".docx",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".log",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".svg",
    ".txt",
    ".webp",
    ".xlsx",
    ".yaml",
    ".yml",
}
_MAX_PREVIEW_BYTES = 100 * 1024 * 1024
_DENIED_PREVIEW_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "license.json",
}
_UPLOAD_MAX_PER_FILE = 500 * 1024 * 1024
_UPLOAD_DIRNAME_SANITIZE = re.compile(r"[^A-Za-z0-9._-]")


def create_files_router(
    *,
    project_root: Path,
    get_elevate_home_func=get_elevate_home,
    upload_max_per_file_func=lambda: _UPLOAD_MAX_PER_FILE,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build routes for file preview and chat uploads."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _preview_roots() -> list[Path]:
        elevate_home = get_elevate_home_func()
        roots = [
            project_root,
            elevate_home / "uploads",
            elevate_home / "tools" / "data" / "sources",
            Path(tempfile.gettempdir()),
            Path("/tmp"),
        ]
        resolved: list[Path] = []
        for root in roots:
            try:
                resolved.append(root.expanduser().resolve())
            except OSError:
                continue
        return resolved

    def _resolve_preview_file(raw_path: str) -> Path:
        if not raw_path or not raw_path.strip():
            raise HTTPException(status_code=400, detail="Missing file path")

        candidate = Path(os.path.expandvars(raw_path.strip())).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate

        try:
            path = candidate.resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid file path: {exc}")

        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        if path.name.lower() in _DENIED_PREVIEW_FILENAMES:
            raise HTTPException(status_code=403, detail="File path is not previewable")

        if path.suffix.lower() not in _PREVIEWABLE_SUFFIXES:
            raise HTTPException(status_code=415, detail="File type is not previewable")

        try:
            size = path.stat().st_size
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Could not inspect file: {exc}")
        if size > _MAX_PREVIEW_BYTES:
            raise HTTPException(status_code=413, detail="File is too large to preview")

        if not any(_is_relative_to(path, root) for root in _preview_roots()):
            raise HTTPException(status_code=403, detail="File path is outside preview roots")

        return path

    def _sanitize_upload_filename(raw: str) -> str:
        name = (raw or "").strip().split("/")[-1].split("\\")[-1] or "file"
        clean = _UPLOAD_DIRNAME_SANITIZE.sub("_", name)
        if clean.startswith("."):
            clean = "_" + clean.lstrip(".")
        return clean[:120] or "file"

    @router.get("/api/files/preview")
    async def preview_file(path: str):
        target = _resolve_preview_file(path)
        media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return FileResponse(
            target,
            filename=target.name,
            media_type=media_type,
            content_disposition_type="inline",
            headers={
                "X-Elevate-File-Name": target.name,
                "X-Elevate-File-Size": str(target.stat().st_size),
            },
        )

    @router.post("/api/uploads/{session_id}")
    async def upload_attachment(session_id: str, file: UploadFile = File(...)):
        """Accept a chat attachment and stash it under ~/.elevate/uploads/<sid>/."""
        sid_clean = _sanitize_upload_filename(session_id) or "anon"
        upload_dir = get_elevate_home_func() / "uploads" / sid_clean
        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            _log.warning("Could not create upload dir", exc_info=True)
            raise HTTPException(status_code=500, detail="Could not create upload directory")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = _sanitize_upload_filename(file.filename or "file")
        dest = upload_dir / f"{ts}_{safe_name}"

        total = 0
        try:
            with dest.open("wb") as handle:
                while True:
                    chunk = await file.read(1 << 20)
                    if not chunk:
                        break
                    total += len(chunk)
                    upload_max_per_file = upload_max_per_file_func()
                    if total > upload_max_per_file:
                        handle.close()
                        try:
                            dest.unlink()
                        except OSError:
                            pass
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds {upload_max_per_file // (1024 * 1024)} MB cap",
                        )
                    handle.write(chunk)
        except HTTPException:
            raise
        except Exception:
            try:
                dest.unlink()
            except OSError:
                pass
            _log.warning("Upload failed", exc_info=True)
            raise HTTPException(status_code=500, detail="Upload failed")

        media_type = file.content_type or mimetypes.guess_type(str(dest))[0] or "application/octet-stream"
        return JSONResponse(
            {
                "path": str(dest),
                "name": safe_name,
                "size": total,
                "media_type": media_type,
            }
        )

    return router
