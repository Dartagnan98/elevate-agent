"""Edit the actual kit PDF, retaining immutable versions and durable field edits."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, StrictStr

from elevate_cli.web_routes import kit_state, kit_terms
from elevate_cli.web_routes.kit_state import version_path


class PdfEdits(BaseModel):
    revision: StrictStr
    values: dict[str, StrictStr]



def _editable(widget):
    import fitz
    name = widget.field_name or ""
    low = re.sub(r"[^a-z0-9]", "", name.lower())
    return bool(name and not (widget.field_flags & 1) and
                (not low.startswith("hid") or low == "hidotime") and
                not re.search(r"pageof|pagenum|dynamicpage|witness\d*sig|signersig\d*|signature\d*|csignature\d*|realtorsig\d*|initial\d*", low) and
                widget.field_type in (fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_CHECKBOX,
                                      fitz.PDF_WIDGET_TYPE_RADIOBUTTON, fitz.PDF_WIDGET_TYPE_COMBOBOX,
                                      fitz.PDF_WIDGET_TYPE_LISTBOX))


def _signed(pdf):
    import fitz
    return any(w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE and
               pdf.xref_get_key(w.xref, "V")[0] not in ("null", "none")
               for page in pdf for w in (page.widgets() or []))


def inspect_pdf(path):
    import fitz
    pages = []
    with fitz.open(path) as pdf:
        signed = _signed(pdf)
        blocked = {w.field_name for p in pdf for w in (p.widgets() or []) if w.field_flags & 1}
        for page in pdf:
            fields = []
            for w in page.widgets() or []:
                if signed or w.field_name in blocked or not _editable(w):
                    continue
                r = w.rect * page.rotation_matrix
                kind = "text"
                if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    kind = "choice"
                elif w.field_type in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                    kind = "select"
                on = str(w.on_state() or "Yes") if kind == "choice" else ""
                value = str(w.field_value or "")
                if kind == "choice" and value in ("Off", "False"):
                    value = ""
                fields.append({"name": w.field_name, "label": ("Offer time: a. or p." if w.field_name.lower() == "hidotime" else w.field_label or w.field_name),
                               "type": kind, "value": value, "on": on,
                               "radio": w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON,
                               "options": list(w.choice_values or []) if kind == "select" else [],
                               "multiline": bool(w.field_flags & 4096) if kind == "text" else False,
                               "maxLength": w.text_maxlen or 0,
                               "rect": [r.x0, r.y0, r.width, r.height]})
            pages.append({"width": page.rect.width, "height": page.rect.height, "fields": fields})
    return {"pages": pages, "signed": signed}


def write_edits(source, destination, values):
    """Validate every edit before creating a new PDF. Never alter source bytes."""
    import fitz
    if len(values) > 2000 or any(not isinstance(v, str) or len(v) > 50000 for v in values.values()):
        raise ValueError("Too much field content. Shorten the text and try saving again.")
    schema = inspect_pdf(source)
    if schema["signed"]:
        raise ValueError("This PDF is signed. Create an unsigned draft before editing.")
    groups = {}
    for page in schema["pages"]:
        for field in page["fields"]:
            groups.setdefault(field["name"], []).append(field)
    missing = set(values) - groups.keys()
    if missing:
        raise ValueError("The form has changed or these fields cannot be edited: " + ", ".join(sorted(missing)))
    for name, value in values.items():
        group = groups[name]
        if group[0]["type"] == "choice" and value not in {"", *(f["on"] for f in group)}:
            raise ValueError("Choose one of the options on the form.")
        if group[0]["type"] == "select" and value and value not in group[0]["options"]:
            raise ValueError("Choose a value from the form's list.")
        if any(f["maxLength"] and len(value) > f["maxLength"] for f in group):
            raise ValueError("Text is longer than this PDF field allows: " + name)
    try:
        with fitz.open(source) as pdf:
            # Unselected radio widgets first, then selected ones (shared /V).
            for selected in (False, True):
                for page in pdf:
                    for w in page.widgets() or []:
                        if w.field_name not in values or not _editable(w):
                            continue
                        value = values[w.field_name]
                        choice = w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON)
                        is_on = choice and value == str(w.on_state() or "Yes")
                        if is_on != selected:
                            continue
                        if not choice and not value:
                            # Some MuPDF versions skip writing an empty value. Clear
                            # the stored value (including its parent) before refresh.
                            pdf.xref_set_key(w.xref, "V", "()")
                            typ, parent = pdf.xref_get_key(w.xref, "Parent")
                            if typ == "xref":
                                pdf.xref_set_key(int(parent.split()[0]), "V", "()")
                        w.field_value = (value if is_on else "Off") if choice else value
                        w.update()
            pdf.save(destination, garbage=3, deflate=True)
        saved = inspect_pdf(destination)
        for name, expected in values.items():
            actual = [f["value"] for p in saved["pages"] for f in p["fields"] if f["name"] == name]
            if groups[name][0]["type"] == "choice":
                valid = bool(actual) and all(v in ("", expected) for v in actual) and (expected in actual if expected else not any(actual))
            else:
                valid = bool(actual) and all(v == expected for v in actual)
            if not valid:
                raise ValueError("The PDF did not retain this field. Your changes have not been saved: " + name)
        with fitz.open(source) as source_pdf:
            flow_terms = kit_terms.managed(source_pdf) and any(kit_terms.is_terms(k) for k in values)
        if flow_terms:
            kit_terms.reflow(destination)
    except Exception:
        Path(destination).unlink(missing_ok=True)
        raise


def reapply_edits(path, doc):
    values = dict(doc.get("pdfWidgetOverrides") or {})
    if "pdfTermsOverride" in doc:
        kit_terms.reflow(path, doc["pdfTermsOverride"])
        values = {k: v for k, v in values.items() if not kit_terms.is_terms(k)}
    elif any(kit_terms.is_terms(k) for k in values):
        import fitz
        with fitz.open(path) as generated:
            flow_terms = kit_terms.managed(generated)
        if flow_terms:
            with fitz.open(doc["filePath"]) as previous:
                terms = kit_terms.text_from(previous)
            kit_terms.reflow(path, terms)
            values = {k: v for k, v in values.items() if not kit_terms.is_terms(k)}
    if not values:
        return
    output = version_path(path)
    write_edits(path, output, values)
    Path(output).replace(path)


def fit_listing_text(path):
    """Keep the full legal names/address/terms visible in narrow form widgets."""
    import fitz
    output = version_path(path)
    try:
        with fitz.open(path) as pdf:
            if _signed(pdf):
                raise ValueError('Cannot resize fields in a signed PDF.')
            for page in pdf:
                for w in page.widgets() or []:
                    if w.field_type != fitz.PDF_WIDGET_TYPE_TEXT or not w.field_value:
                        continue
                    value = str(w.field_value)
                    width, height = w.rect.width - 4, w.rect.height - 3
                    size = min(w.text_fontsize or 10, 12)
                    def fits(fontsize):
                        if not (w.field_flags & 4096):
                            return fitz.get_text_length(value, fontname='helv', fontsize=fontsize) <= width and fontsize <= height
                        lines = 0
                        for paragraph in value.split('\n'):
                            current = ''
                            for word in paragraph.split():
                                candidate = (current + ' ' + word).strip()
                                if fitz.get_text_length(candidate, fontname='helv', fontsize=fontsize) > width:
                                    if not current:
                                        return False
                                    lines += 1
                                    current = word
                                else:
                                    current = candidate
                            lines += 1
                        return lines * fontsize * 1.3 <= height
                    while size >= 6 and not fits(size):
                        size -= .25
                    if size < 6:
                        raise ValueError(f'Text does not fit legibly in {w.field_name}; shorten it or use an approved addendum.')
                    w.text_font = 'Helv'
                    w.text_fontsize = size
                    w.update()
            # Otherwise viewers can discard our fitted appearances and rebuild
            # them from the template's old parent font settings (clipping again).
            pdf.need_appearances(False)
            pdf.save(output, garbage=3, deflate=True)
        Path(output).replace(path)
    finally:
        Path(output).unlink(missing_ok=True)


def revision(doc, toggles):
    pdf_hash = hashlib.sha256(Path(doc["filePath"]).read_bytes()).hexdigest()
    return hashlib.sha256((pdf_hash + kit_state.input_hash(toggles, doc) +
                           str(doc.get("generatedAt")) + str(doc.get("editedAt"))).encode()).hexdigest()


def read_document(conn, deal_id, side, doc_id, lock=False):
    key = {"buyer": "offerKit", "listing": "listingKit"}.get(side)
    if not key:
        raise HTTPException(404, "Kit not found")
    row = conn.execute("SELECT extra_toggles_json FROM deals WHERE id=?" + (" FOR UPDATE" if lock else ""), (deal_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Deal not found")
    raw = row["extra_toggles_json"]
    toggles = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    doc = next((d for d in (toggles.get(key) or {}).get("documents", []) if d.get("id") == doc_id), None)
    if not doc or not doc.get("filePath") or not Path(doc["filePath"]).is_file():
        raise HTTPException(404, "Draft this document first, then open it to edit.")
    return toggles, doc


def save_document(conn, deal_id, side, doc_id, body):
    toggles, doc = read_document(conn, deal_id, side, doc_id, lock=True)
    if revision(doc, toggles) != body.revision or kit_state.stale(doc, toggles):
        raise HTTPException(409, "This document or its source information changed. Your edits are still on screen. Close and reopen the latest draft before saving.")
    if str(doc.get("status", "")).lower() in ("signed", "completed", "executed"):
        raise HTTPException(409, "This document is signed. Create an unsigned draft before editing.")
    if not body.values:
        return {"revision": body.revision, "saved": True}
    source = doc["filePath"]
    destination = version_path(source)
    try:
        write_edits(source, destination, body.values)
        if side == 'listing':
            fit_listing_text(destination)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    now = datetime.utcnow().isoformat()
    doc.setdefault("pdfHistory", []).append({"filePath": source, "savedAt": doc.get("generatedAt")})
    doc.setdefault("pdfWidgetOverrides", {}).update(body.values)
    import fitz
    with fitz.open(destination) as saved_pdf:
        if kit_terms.managed(saved_pdf) and any(kit_terms.is_terms(k) for k in body.values):
            # Page boundaries can change on save. Retain the complete edited
            # schedule, rather than overrides tied to yesterday's page layout.
            doc["pdfTermsOverride"] = kit_terms.text_from(saved_pdf)
            doc["pdfWidgetOverrides"] = {k: v for k, v in doc["pdfWidgetOverrides"].items()
                                         if not kit_terms.is_terms(k)}
    doc.update(filePath=destination, generatedAt=now, pdfEditedAt=now, status="draft", ready=True)
    doc.pop("editedAt", None)
    doc["generatedInputHash"] = kit_state.input_hash(toggles, doc)
    conn.execute("UPDATE deals SET extra_toggles_json=? WHERE id=?", (json.dumps(toggles), deal_id))
    if side == 'listing':
        from elevate_cli.mlc_handoff import refresh_document_reviews
        refresh_document_reviews(conn, deal_id)
    return {"revision": revision(doc, toggles), "saved": True, "pdf": inspect_pdf(destination)}


def register_routes(router, label_for=None):
    from elevate_cli.data import connect

    def label_fields(schema):
        if label_for:
            for page in schema["pages"]:
                for field in page["fields"]:
                    label = label_for(field["name"])
                    if label != field["name"]:
                        field["label"] = label

    @router.get("/api/admin/deals/{deal_id}/kit-pdf/{side}/{doc_id}")
    def get_pdf_editor(deal_id: str, side: str, doc_id: str):
        with connect() as conn:
            toggles, doc = read_document(conn, deal_id, side, doc_id)
        body = inspect_pdf(doc["filePath"])
        label_fields(body)
        body["signed"] = body["signed"] or str(doc.get("status", "")).lower() in ("signed", "completed", "executed")
        body.update(revision=revision(doc, toggles), stale=kit_state.stale(doc, toggles),
                    edited=bool(doc.get("pdfWidgetOverrides")) or "pdfTermsOverride" in doc)
        return body

    @router.get("/api/admin/deals/{deal_id}/kit-pdf/{side}/{doc_id}/page/{page}")
    def get_pdf_editor_page(deal_id: str, side: str, doc_id: str, page: int, revision_id: str):
        import fitz
        with connect() as conn:
            toggles, doc = read_document(conn, deal_id, side, doc_id)
        if revision(doc, toggles) != revision_id:
            raise HTTPException(409, "The PDF changed. Reopen it to view the latest version.")
        with fitz.open(doc["filePath"]) as pdf:
            if page < 1 or page > len(pdf):
                raise HTTPException(404, "Page not found")
            png = pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).tobytes("png")
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @router.put("/api/admin/deals/{deal_id}/kit-pdf/{side}/{doc_id}")
    def put_pdf_editor(deal_id: str, side: str, doc_id: str, body: PdfEdits):
        with connect() as conn:
            result = save_document(conn, deal_id, side, doc_id, body)
        if result.get("pdf"):
            label_fields(result["pdf"])
        return result
