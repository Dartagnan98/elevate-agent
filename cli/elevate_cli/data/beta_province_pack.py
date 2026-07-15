"""Signed, sanitized province-pack support for the exact Realtor Beta.

The bundled BC pack contains original workflow guidance and factual catalog
metadata only. It deliberately contains no form bodies, blanks, fill maps,
coordinates, provider URLs, or completed examples. Runtime activation is
fail-closed: the immutable files, SQLite projection, document-search chunks,
and a private durable receipt must all agree before the pack is considered
ready.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from elevate_constants import exact_realtor_beta_active, get_elevate_home
from elevate_cli.data._util import now_iso, sha256


PACK_ID = "bc-residential-resale-reference-v1"
PACK_PROVINCE = "BC"
PACK_SCHEMA_VERSION = 1
PACK_FORM_COUNT = 34
PACK_GUIDE_SLUG = "bc-residential-resale-guide"
PACK_CATALOG_SLUG = "bc-residential-resale-form-catalog"
PACK_SOURCE_PREFIX = f"elevate://province-pack/{PACK_ID}"
PACK_MEMORY_SOURCE_URIS = (
    f"elevate://province-guide/BC/reference/{PACK_GUIDE_SLUG}",
    f"elevate://province-guide/BC/reference/{PACK_CATALOG_SLUG}",
)
PACK_AVAILABILITY = "provider_required"
PACK_NOTICE = (
    "Reference only; current version unverified; licensed blank required "
    "from the configured forms provider."
)

_PACK_HASH_DOMAIN = b"elevate-realtor-beta-province-pack-v1\x00"
_PACK_FILES = ("forms.json", "guide.md", "manifest.json")
_MAX_FILE_BYTES = 256 * 1024
_MAX_TOTAL_BYTES = 512 * 1024
_HEX_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


class BetaProvincePackError(RuntimeError):
    """The exact-Beta province pack could not be trusted or activated."""


@dataclass(frozen=True, slots=True)
class BetaProvinceForm:
    code: str
    title: str
    category: str
    availability: str
    reference_only: bool
    current_version_verified: bool
    licensed_blank_required: bool


@dataclass(frozen=True, slots=True)
class BetaProvincePack:
    root: Path
    pack_id: str
    province: str
    sha256: str
    manifest_sha256: str
    guide_sha256: str
    catalog_sha256: str
    guide_content: str
    catalog_content: str
    catalog_memory_content: str
    forms: tuple[BetaProvinceForm, ...]

    @property
    def catalog_memory_sha256(self) -> str:
        return sha256(self.catalog_memory_content)


def default_exact_beta_bc_pack_root() -> Path:
    return Path(__file__).parent / "province_packs" / "bc_residential_resale"


def exact_beta_bc_pack_receipt_path() -> Path:
    return get_elevate_home() / "province-packs" / f"{PACK_ID}.activation.json"


def _require_plain_dir(path: Path, label: str) -> None:
    try:
        item = os.lstat(path)
    except OSError as exc:
        raise BetaProvincePackError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(item.st_mode):
        raise BetaProvincePackError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(item.st_mode):
        raise BetaProvincePackError(f"{label} must be a directory")


def _read_plain_file(path: Path, label: str) -> bytes:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise BetaProvincePackError(f"required pack file is unavailable: {label}") from exc
    if stat.S_ISLNK(before.st_mode):
        raise BetaProvincePackError(f"pack file must not be a symlink: {label}")
    if not stat.S_ISREG(before.st_mode):
        raise BetaProvincePackError(f"pack entry must be a regular file: {label}")
    if before.st_size <= 0 or before.st_size > _MAX_FILE_BYTES:
        raise BetaProvincePackError(f"pack file has an invalid size: {label}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise BetaProvincePackError(f"pack file could not be opened safely: {label}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise BetaProvincePackError(f"pack entry must be a regular file: {label}")
        if (before.st_dev, before.st_ino, before.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise BetaProvincePackError(f"pack file changed while opening: {label}")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                raise BetaProvincePackError(f"pack file changed while reading: {label}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise BetaProvincePackError(f"pack file changed while reading: {label}")
        after = os.fstat(fd)
        if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BetaProvincePackError(f"pack file changed while reading: {label}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BetaProvincePackError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise BetaProvincePackError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise BetaProvincePackError(
            f"{label} schema mismatch (missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
        )


def _safe_relative_filename(value: Any, label: str) -> str:
    text = str(value or "")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or len(path.parts) != 1 or path.name != text:
        raise BetaProvincePackError(f"{label} must name one file inside the pack")
    return text


def _validate_sha(value: Any, label: str) -> str:
    digest = str(value or "")
    if not _HEX_SHA256_RE.fullmatch(digest):
        raise BetaProvincePackError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _catalog_memory(forms: tuple[BetaProvinceForm, ...]) -> str:
    lines = [
        "# British Columbia residential resale form catalog",
        "",
        PACK_NOTICE,
        "The entries below are factual lookup metadata, not form contents or proof that a form applies.",
        "",
    ]
    for form in forms:
        lines.append(
            f"- {form.code} — {form.title} — category: {form.category}; "
            "availability: provider required; reference only; current version unverified; "
            "licensed blank required."
        )
    return "\n".join(lines).strip() + "\n"


def _pack_hash(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256(_PACK_HASH_DOMAIN)
    for name in sorted(files):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(files[name]).to_bytes(8, "big"))
        digest.update(files[name])
    return digest.hexdigest()


def load_exact_beta_bc_pack(
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | str | None = None,
) -> BetaProvincePack:
    active_environ = os.environ if environ is None else environ
    if not exact_realtor_beta_active(dict(active_environ)):
        raise BetaProvincePackError("province pack is restricted to exact Realtor Beta")

    pack_root = Path(os.path.abspath(os.fspath(root or default_exact_beta_bc_pack_root())))
    _require_plain_dir(pack_root, "province pack root")
    try:
        entries = sorted(os.scandir(pack_root), key=lambda item: item.name)
    except OSError as exc:
        raise BetaProvincePackError("province pack could not be enumerated") from exc
    if tuple(entry.name for entry in entries) != _PACK_FILES:
        raise BetaProvincePackError("province pack must contain exactly manifest.json, guide.md, and forms.json")
    files = {name: _read_plain_file(pack_root / name, name) for name in _PACK_FILES}
    if sum(map(len, files.values())) > _MAX_TOTAL_BYTES:
        raise BetaProvincePackError("province pack exceeds the total size cap")

    manifest = _json_object(files["manifest.json"], "manifest.json")
    _require_exact_keys(
        manifest,
        {
            "schemaVersion", "packId", "province", "scope", "referenceOnly",
            "currentVersionVerified", "licensedBlankRequired", "availability",
            "guide", "catalog",
        },
        "manifest.json",
    )
    expected_policy = (
        manifest.get("schemaVersion") == PACK_SCHEMA_VERSION
        and manifest.get("packId") == PACK_ID
        and manifest.get("province") == PACK_PROVINCE
        and manifest.get("scope") == "residential-resale"
        and manifest.get("referenceOnly") is True
        and manifest.get("currentVersionVerified") is False
        and manifest.get("licensedBlankRequired") is True
        and manifest.get("availability") == PACK_AVAILABILITY
    )
    if not expected_policy:
        raise BetaProvincePackError("manifest policy or identity is invalid")
    guide_spec = manifest.get("guide")
    catalog_spec = manifest.get("catalog")
    if not isinstance(guide_spec, Mapping) or not isinstance(catalog_spec, Mapping):
        raise BetaProvincePackError("manifest file declarations are invalid")
    _require_exact_keys(guide_spec, {"path", "sha256"}, "manifest guide")
    _require_exact_keys(catalog_spec, {"path", "sha256", "formCount"}, "manifest catalog")
    guide_name = _safe_relative_filename(guide_spec.get("path"), "guide path")
    catalog_name = _safe_relative_filename(catalog_spec.get("path"), "catalog path")
    if (guide_name, catalog_name) != ("guide.md", "forms.json"):
        raise BetaProvincePackError("manifest must bind the expected guide and catalog files")
    guide_sha = _validate_sha(guide_spec.get("sha256"), "guide sha256")
    catalog_sha = _validate_sha(catalog_spec.get("sha256"), "catalog sha256")
    if int(catalog_spec.get("formCount") or 0) != PACK_FORM_COUNT:
        raise BetaProvincePackError("manifest form count is invalid")
    if hashlib.sha256(files[guide_name]).hexdigest() != guide_sha:
        raise BetaProvincePackError("guide.md integrity check failed")
    if hashlib.sha256(files[catalog_name]).hexdigest() != catalog_sha:
        raise BetaProvincePackError("forms.json integrity check failed")

    try:
        guide_content = files[guide_name].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BetaProvincePackError("guide.md is not valid UTF-8") from exc
    lowered_guide = guide_content.lower()
    for marker in ("reference only", "current version is unverified", "licensed blank", "provider required"):
        if marker not in lowered_guide:
            raise BetaProvincePackError(f"guide.md is missing safety marker: {marker}")
    if _URL_RE.search(guide_content) or "/Users/" in guide_content or "/home/" in guide_content:
        raise BetaProvincePackError("guide.md contains a prohibited URL or machine path")

    catalog = _json_object(files[catalog_name], "forms.json")
    _require_exact_keys(catalog, {"schemaVersion", "province", "scope", "policy", "forms"}, "forms.json")
    policy = catalog.get("policy")
    if not isinstance(policy, Mapping):
        raise BetaProvincePackError("forms.json policy is invalid")
    _require_exact_keys(
        policy,
        {"referenceOnly", "currentVersionVerified", "licensedBlankRequired", "availability"},
        "forms.json policy",
    )
    if (
        catalog.get("schemaVersion") != PACK_SCHEMA_VERSION
        or catalog.get("province") != PACK_PROVINCE
        or catalog.get("scope") != "residential-resale"
        or dict(policy) != {
            "referenceOnly": True,
            "currentVersionVerified": False,
            "licensedBlankRequired": True,
            "availability": PACK_AVAILABILITY,
        }
    ):
        raise BetaProvincePackError("forms.json policy or identity is invalid")
    raw_forms = catalog.get("forms")
    if not isinstance(raw_forms, list) or len(raw_forms) != PACK_FORM_COUNT:
        raise BetaProvincePackError(f"forms.json must contain exactly {PACK_FORM_COUNT} forms")
    forms: list[BetaProvinceForm] = []
    codes: set[str] = set()
    expected_form_keys = {
        "code", "title", "category", "availability", "referenceOnly",
        "currentVersionVerified", "licensedBlankRequired",
    }
    for index, raw_form in enumerate(raw_forms):
        if not isinstance(raw_form, Mapping):
            raise BetaProvincePackError(f"forms[{index}] must be an object")
        _require_exact_keys(raw_form, expected_form_keys, f"forms[{index}]")
        code = str(raw_form.get("code") or "").strip()
        title = str(raw_form.get("title") or "").strip()
        category = str(raw_form.get("category") or "").strip()
        if not code or not title or not category or code in codes:
            raise BetaProvincePackError(f"forms[{index}] has missing or duplicate identity metadata")
        if _URL_RE.search(" ".join((code, title, category))):
            raise BetaProvincePackError(f"forms[{index}] contains a prohibited URL")
        if (
            raw_form.get("availability") != PACK_AVAILABILITY
            or raw_form.get("referenceOnly") is not True
            or raw_form.get("currentVersionVerified") is not False
            or raw_form.get("licensedBlankRequired") is not True
        ):
            raise BetaProvincePackError(f"forms[{index}] does not enforce provider-required safety")
        codes.add(code)
        forms.append(
            BetaProvinceForm(
                code=code,
                title=title,
                category=category,
                availability=PACK_AVAILABILITY,
                reference_only=True,
                current_version_verified=False,
                licensed_blank_required=True,
            )
        )
    form_tuple = tuple(forms)
    return BetaProvincePack(
        root=pack_root,
        pack_id=PACK_ID,
        province=PACK_PROVINCE,
        sha256=_pack_hash(files),
        manifest_sha256=hashlib.sha256(files["manifest.json"]).hexdigest(),
        guide_sha256=guide_sha,
        catalog_sha256=catalog_sha,
        guide_content=guide_content,
        catalog_content=files[catalog_name].decode("utf-8"),
        catalog_memory_content=_catalog_memory(form_tuple),
        forms=form_tuple,
    )


def import_exact_beta_bc_pack(conn: Any, *, root: Path | str | None = None) -> dict[str, Any]:
    """Project the immutable BC reference pack into the operational store."""
    pack = load_exact_beta_bc_pack(root=root)
    from elevate_cli.data.province_guides import (
        _DEFAULT_CONDITIONAL_DOCS,
        _upsert_conditional_doc,
        _upsert_form,
        _upsert_reference_page,
    )

    # Exact Beta is an isolated product lane. Remove mutable/legacy BC guide
    # material before installing the signed reference-only projection.
    for table in ("province_reference_pages", "province_checklists", "province_forms", "conditional_docs"):
        conn.execute(f"DELETE FROM {table} WHERE province=?", (PACK_PROVINCE,))
    now = now_iso()
    _upsert_reference_page(
        conn,
        province=PACK_PROVINCE,
        slug=PACK_GUIDE_SLUG,
        page_type="transaction_guide",
        title="British Columbia residential resale reference guide",
        source_url=None,
        source_path=f"{PACK_SOURCE_PREFIX}/guide.md",
        content_md=pack.guide_content,
        now=now,
    )
    _upsert_reference_page(
        conn,
        province=PACK_PROVINCE,
        slug=PACK_CATALOG_SLUG,
        page_type="form_catalog",
        title="British Columbia residential resale form catalog",
        source_url=None,
        source_path=f"{PACK_SOURCE_PREFIX}/forms.json",
        content_md=pack.catalog_memory_content,
        now=now,
    )
    for form in pack.forms:
        _upsert_form(
            conn,
            province=PACK_PROVINCE,
            code=form.code,
            form={
                "name": form.title,
                "category": form.category,
                "description": PACK_NOTICE,
                "pageCount": None,
                "annotationCount": None,
                "imageUrls": [],
            },
            local_image_paths=[],
            source_path=f"{PACK_SOURCE_PREFIX}/forms.json",
            now=now,
        )
    for conditional in _DEFAULT_CONDITIONAL_DOCS:
        _upsert_conditional_doc(conn, now=now, **conditional)
    return {
        "ok": True,
        "root": str(pack.root),
        "packId": pack.pack_id,
        "packSha256": pack.sha256,
        "pages": 2,
        "checklists": 0,
        "forms": len(pack.forms),
        "conditionalDocs": len(_DEFAULT_CONDITIONAL_DOCS),
        "provinces": [PACK_PROVINCE],
        "referenceOnly": True,
        "currentVersionVerified": False,
        "licensedBlankRequired": True,
        "availability": PACK_AVAILABILITY,
    }


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {}


def _read_receipt() -> dict[str, Any] | None:
    path = exact_beta_bc_pack_receipt_path()
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BetaProvincePackError("province pack receipt is unreadable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise BetaProvincePackError("province pack receipt must be a private regular file")
    raw = _read_plain_file(path, "activation receipt")
    return _json_object(raw, "activation receipt")


def _write_receipt(data: Mapping[str, Any]) -> None:
    path = exact_beta_bc_pack_receipt_path()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _require_plain_dir(parent, "province pack receipt directory")
    os.chmod(parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=".bc_pack_", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        encoded = (json.dumps(dict(data), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        offset = 0
        while offset < len(encoded):
            written = os.write(fd, encoded[offset:])
            if written <= 0:
                raise OSError("province pack receipt write made no progress")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        if path.exists() and path.is_symlink():
            raise BetaProvincePackError("province pack receipt target must not be a symlink")
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
        dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def exact_beta_bc_pack_readiness(
    conn: Any,
    *,
    pack: BetaProvincePack | None = None,
    require_receipt: bool = True,
    store: Any | None = None,
) -> dict[str, Any]:
    """Derive readiness from immutable files, DB rows, live search, and receipt."""
    try:
        pack = pack or load_exact_beta_bc_pack()
    except Exception as exc:
        return {"ready": False, "province": PACK_PROVINCE, "reason": str(exc)}

    expected_pages = {
        PACK_GUIDE_SLUG: (pack.guide_sha256, f"{PACK_SOURCE_PREFIX}/guide.md"),
        PACK_CATALOG_SLUG: (pack.catalog_memory_sha256, f"{PACK_SOURCE_PREFIX}/forms.json"),
    }
    page_rows = [
        _row_dict(row)
        for row in conn.execute(
            "SELECT slug, content_hash, source_path FROM province_reference_pages WHERE province=? ORDER BY slug",
            (PACK_PROVINCE,),
        ).fetchall()
    ]
    page_map = {str(row.get("slug") or ""): row for row in page_rows}
    pages_ready = len(page_rows) == len(expected_pages) and all(
        page_map.get(slug, {}).get("content_hash") == content_hash
        and page_map.get(slug, {}).get("source_path") == source_path
        for slug, (content_hash, source_path) in expected_pages.items()
    )
    form_rows = [
        _row_dict(row)
        for row in conn.execute(
            "SELECT code, name, category, description, source_path, page_count, annotation_count, image_urls_json, local_image_paths_json "
            "FROM province_forms WHERE province=? ORDER BY code",
            (PACK_PROVINCE,),
        ).fetchall()
    ]
    expected_forms = {form.code: form for form in pack.forms}
    forms_ready = len(form_rows) == PACK_FORM_COUNT
    for row in form_rows:
        form = expected_forms.get(str(row.get("code") or ""))
        if not form or (
            row.get("name") != form.title
            or row.get("category") != form.category
            or row.get("description") != PACK_NOTICE
            or row.get("source_path") != f"{PACK_SOURCE_PREFIX}/forms.json"
            or row.get("page_count") is not None
            or row.get("annotation_count") is not None
            or str(row.get("image_urls_json") or "[]") != "[]"
            or str(row.get("local_image_paths_json") or "[]") != "[]"
        ):
            forms_ready = False
            break
    checklist_count = int(
        conn.execute("SELECT COUNT(*) AS count FROM province_checklists WHERE province=?", (PACK_PROVINCE,)).fetchone()["count"]
    )
    from elevate_cli.data.province_guides import _DEFAULT_CONDITIONAL_DOCS

    conditional_rows = [
        _row_dict(row)
        for row in conn.execute(
            "SELECT province, side, stage, field_key, field_value, doc_code, doc_name, notes "
            "FROM conditional_docs WHERE province=? ORDER BY field_key, field_value, doc_code",
            (PACK_PROVINCE,),
        ).fetchall()
    ]
    conditional_identity = {
        (
            str(row.get("province") or ""),
            row.get("side"),
            row.get("stage"),
            str(row.get("field_key") or ""),
            str(row.get("field_value") or ""),
            str(row.get("doc_code") or ""),
            str(row.get("doc_name") or ""),
            str(row.get("notes") or ""),
        )
        for row in conditional_rows
    }
    expected_conditional_identity = {
        (
            str(item["province"]),
            item.get("side"),
            item.get("stage"),
            str(item["field_key"]),
            str(item["field_value"]),
            str(item["doc_code"]),
            str(item["doc_name"]),
            str(item.get("notes") or ""),
        )
        for item in _DEFAULT_CONDITIONAL_DOCS
    }
    conditionals_ready = conditional_identity == expected_conditional_identity

    memory_rows = [
        _row_dict(row)
        for row in conn.execute(
            """
            SELECT d.source_uri, d.metadata_json, COUNT(c.chunk_id) AS chunks
            FROM memory_documents d
            LEFT JOIN memory_chunks c ON c.document_id=d.document_id
            WHERE d.source_type=? AND d.source_uri LIKE ?
            GROUP BY d.document_id
            ORDER BY d.source_uri
            """,
            ("province_guide", "elevate://province-guide/BC/%"),
        ).fetchall()
    ]
    expected_memory_hashes = {
        PACK_MEMORY_SOURCE_URIS[0]: pack.guide_sha256,
        PACK_MEMORY_SOURCE_URIS[1]: pack.catalog_memory_sha256,
    }
    memory_ready = len(memory_rows) == len(expected_memory_hashes)
    for row in memory_rows:
        uri = str(row.get("source_uri") or "")
        try:
            metadata = json.loads(str(row.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        if (
            uri not in expected_memory_hashes
            or int(row.get("chunks") or 0) <= 0
            or metadata.get("province") != PACK_PROVINCE
            or metadata.get("contentHash") != expected_memory_hashes[uri]
        ):
            memory_ready = False
            break

    search_ready = False
    search_reason: str | None = None
    own_store = store is None
    try:
        if store is None:
            from plugins.memory.holographic.store import MemoryStore

            store = MemoryStore()
        search_results = store.document_search(
            "licensed blank provider required",
            source_type="province_guide",
            limit=40,
        )
        found_uris = {
            str(item.get("source_uri") or "")
            for item in search_results
            if isinstance(item, Mapping)
        }
        search_ready = set(PACK_MEMORY_SOURCE_URIS).issubset(found_uris)
        if not search_ready:
            search_reason = "document_search did not return every bundled pack document"
    except Exception as exc:
        search_reason = f"document_search integrity probe failed: {exc}"
    finally:
        if own_store and store is not None:
            close = getattr(store, "close", None)
            if callable(close):
                close()

    receipt_ready = not require_receipt
    receipt_reason: str | None = None
    if require_receipt:
        try:
            receipt = _read_receipt()
            receipt_ready = bool(
                receipt
                and receipt.get("schemaVersion") == PACK_SCHEMA_VERSION
                and receipt.get("packId") == PACK_ID
                and receipt.get("province") == PACK_PROVINCE
                and receipt.get("packSha256") == pack.sha256
                and receipt.get("formCount") == PACK_FORM_COUNT
                and receipt.get("memorySourceUris") == list(PACK_MEMORY_SOURCE_URIS)
                and receipt.get("documentSearchVerified") is True
            )
            if not receipt_ready:
                receipt_reason = "activation receipt missing or stale"
        except Exception as exc:
            receipt_reason = str(exc)

    ready = (
        pages_ready
        and forms_ready
        and checklist_count == 0
        and conditionals_ready
        and memory_ready
        and search_ready
        and receipt_ready
    )
    reason = None
    if not ready:
        failed = []
        if not pages_ready:
            failed.append("reference pages")
        if not forms_ready:
            failed.append("provider-required form catalog")
        if checklist_count:
            failed.append("unexpected checklist content")
        if not conditionals_ready:
            failed.append("code-defined conditional stage rules")
        if not memory_ready:
            failed.append("document_search memory")
        if not search_ready:
            failed.append(search_reason or "document_search integrity probe")
        if not receipt_ready:
            failed.append(receipt_reason or "activation receipt")
        reason = "not verified: " + ", ".join(failed)
    return {
        "ready": ready,
        "province": PACK_PROVINCE,
        "packId": PACK_ID,
        "packSha256": pack.sha256,
        "referenceOnly": True,
        "currentVersionVerified": False,
        "licensedBlankRequired": True,
        "availability": PACK_AVAILABILITY,
        "pages": len(page_rows),
        "forms": len(form_rows),
        "conditionalDocs": len(conditional_rows),
        "memoryDocuments": len(memory_rows),
        "documentSearchVerified": memory_ready and search_ready,
        "reason": reason,
    }


def activate_exact_beta_bc_pack(
    conn: Any,
    *,
    root: Path | str | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Install, sync, search-test, receipt, and re-derive exact-Beta readiness."""
    pack = load_exact_beta_bc_pack(root=root)
    imported = import_exact_beta_bc_pack(conn, root=root)
    own_store = store is None
    if store is None:
        from plugins.memory.holographic.store import MemoryStore

        store = MemoryStore()
    try:
        from elevate_cli.data.province_guide_memory import sync_province_guide_to_memory

        memory = sync_province_guide_to_memory(
            conn,
            PACK_PROVINCE,
            store=store,
            prune_stale_same_province=True,
        )
        provisional = exact_beta_bc_pack_readiness(
            conn,
            pack=pack,
            require_receipt=False,
            store=store,
        )
        if not provisional.get("ready"):
            raise BetaProvincePackError(
                provisional.get("reason") or "document_search did not return every bundled pack document"
            )
        _write_receipt(
            {
                "schemaVersion": PACK_SCHEMA_VERSION,
                "packId": PACK_ID,
                "province": PACK_PROVINCE,
                "packSha256": pack.sha256,
                "formCount": PACK_FORM_COUNT,
                "memorySourceUris": list(PACK_MEMORY_SOURCE_URIS),
                "documentSearchVerified": True,
                "activatedAt": now_iso(),
            }
        )
        readiness = exact_beta_bc_pack_readiness(
            conn,
            pack=pack,
            require_receipt=True,
            store=store,
        )
        if not readiness.get("ready"):
            raise BetaProvincePackError(readiness.get("reason") or "province pack readiness failed")
        return {**readiness, "import": imported, "memory": memory}
    finally:
        if own_store:
            close = getattr(store, "close", None)
            if callable(close):
                close()


def enforce_exact_beta_province(province: str | None) -> str:
    """Reject non-BC jurisdiction selection only on the exact Beta channel."""
    value = str(province or "").strip().upper()
    if exact_realtor_beta_active():
        if value and value != PACK_PROVINCE:
            raise ValueError("Realtor Beta currently supports the verified British Columbia pack only")
        return PACK_PROVINCE
    return value


__all__ = [
    "BetaProvinceForm",
    "BetaProvincePack",
    "BetaProvincePackError",
    "PACK_AVAILABILITY",
    "PACK_FORM_COUNT",
    "PACK_ID",
    "PACK_PROVINCE",
    "activate_exact_beta_bc_pack",
    "default_exact_beta_bc_pack_root",
    "enforce_exact_beta_province",
    "exact_beta_bc_pack_readiness",
    "exact_beta_bc_pack_receipt_path",
    "import_exact_beta_bc_pack",
    "load_exact_beta_bc_pack",
]
