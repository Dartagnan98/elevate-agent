import copy
import json
from pathlib import Path

import fitz
import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient

from elevate_cli.web_routes import kit_pdf, kit_state


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "original.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((30, 40), f"Sample contract, page {i+1}")
        for name, kind, value, rect in [
            ("buyer", fitz.PDF_WIDGET_TYPE_TEXT, "Original buyer", (30, 60, 260, 84)),
            (f"notes{i}", fitz.PDF_WIDGET_TYPE_TEXT, "", (30, 100, 400, 160)),
            (f"consent{i}", fitz.PDF_WIDGET_TYPE_CHECKBOX, "Off", (30, 190, 46, 206)),
            (f"hidInternal{i}", fitz.PDF_WIDGET_TYPE_TEXT, "keep", (30, 230, 80, 245)),
        ]:
            w = fitz.Widget(); w.field_name = name; w.field_type = kind
            w.field_value = value; w.rect = fitz.Rect(rect)
            page.add_widget(w)
    doc.save(path); doc.close()
    return path


def values(path):
    with fitz.open(path) as doc:
        return [(w.field_name, w.field_value) for page in doc for w in page.widgets()]


def test_save_actual_fields_keeps_source_and_repeated_values(pdf, tmp_path):
    before = pdf.read_bytes()
    edited = tmp_path / "edited.pdf"
    checkbox = kit_pdf.inspect_pdf(pdf)["pages"][0]["fields"][2]
    kit_pdf.write_edits(pdf, edited, {"buyer": "Updated buyer", "notes1": "Second page notes", "consent0": checkbox["on"]})
    assert pdf.read_bytes() == before
    result = values(edited)
    assert [v for k, v in result if k == "buyer"] == ["Updated buyer"] * 2
    assert ("notes1", "Second page notes") in result
    assert ("consent0", checkbox["on"]) in result
    assert ("hidInternal0", "keep") in result
    cleared = tmp_path / "cleared.pdf"
    kit_pdf.write_edits(edited, cleared, {"buyer": "", "consent0": ""})
    assert all(not v for k, v in values(cleared) if k == "buyer")
    assert ("consent0", "Off") in values(cleared)


@pytest.mark.parametrize("edits", [{"missing": "value"}, {"hidInternal0": "change"}, {"consent0": "not an option"}])
def test_invalid_edits_do_not_create_file(pdf, tmp_path, edits):
    output = tmp_path / "invalid.pdf"
    with pytest.raises(ValueError):
        kit_pdf.write_edits(pdf, output, edits)
    assert not output.exists()


@pytest.fixture
def api(pdf, monkeypatch):
    from elevate_cli import data
    state = {"cpsPurchasePrice": "500000", "offerKit": {"documents": [
        {"id": "cps-residential", "filePath": str(pdf), "generatedAt": "2026-09-01", "ready": True}]}}
    doc = state["offerKit"]["documents"][0]
    doc["generatedInputHash"] = kit_state.input_hash(state, doc)
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params):
            if sql.startswith("UPDATE"):
                state.clear(); state.update(json.loads(params[0]))
            return self
        def fetchone(self): return {"extra_toggles_json": copy.deepcopy(state)}
    monkeypatch.setattr(data, "connect", Connection)
    app = FastAPI(); router = APIRouter(); kit_pdf.register_routes(router); app.include_router(router)
    return TestClient(app), state


BASE = "/api/admin/deals/sample/kit-pdf/buyer/cps-residential"


def test_editor_roundtrip_conflict_and_signing_select_saved_pdf(api, pdf, tmp_path):
    client, state = api
    opened = client.get(BASE).json()
    assert len(opened["pages"]) == 2 and not opened["stale"]
    assert not any(f["name"].startswith("hid") for p in opened["pages"] for f in p["fields"])
    image = client.get(BASE + "/page/2", params={"revision_id": opened["revision"]})
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    response = client.put(BASE, json={"revision": opened["revision"], "values": {"buyer": "Saved buyer", "notes1": ""}})
    assert response.status_code == 200, response.text
    saved = state["offerKit"]["documents"][0]
    assert saved["filePath"] != str(pdf) and pdf.exists()
    assert not kit_state.stale(saved, state)
    assert kit_state.selected_documents(state, "offerKit", ["cps-residential"])[0]["filePath"] == saved["filePath"]
    assert ("buyer", "Saved buyer") in values(saved["filePath"])
    assert client.put(BASE, json={"revision": opened["revision"], "values": {"buyer": "Old tab"}}).status_code == 409
    assert client.get(BASE + "/page/1", params={"revision_id": opened["revision"]}).status_code == 409
    # Regeneration from the original template retains explicit PDF edits, including blanks.
    regenerated = tmp_path / "regenerated.pdf"; regenerated.write_bytes(pdf.read_bytes())
    kit_pdf.reapply_edits(regenerated, saved)
    assert ("buyer", "Saved buyer") in values(regenerated)
    assert saved["pdfWidgetOverrides"]["notes1"] == ""


def test_source_change_does_not_allow_save_to_mark_pdf_current(api):
    client, state = api
    opened = client.get(BASE).json()
    state["cpsPurchasePrice"] = "600000"
    response = client.put(BASE, json={"revision": opened["revision"], "values": {"buyer": "New"}})
    assert response.status_code == 409
    assert client.get(BASE).json()["stale"]


def test_override_change_invalidates_generation_hash(pdf):
    state = {}; doc = {"fields": {}}
    before = kit_state.input_hash(state, doc)
    doc["pdfWidgetOverrides"] = {"buyer": "Edited"}
    assert before != kit_state.input_hash(state, doc)


def test_readonly_widget_not_editable(pdf, tmp_path):
    path = tmp_path / "readonly.pdf"
    with fitz.open(pdf) as doc:
        page = doc[0]; w = next(page.widgets()); w.field_flags = 1; w.update()
        doc.save(path)
    # Another occurrence of a name must not make a read-only occurrence writable.
    with pytest.raises(ValueError):
        kit_pdf.write_edits(path, tmp_path / "out.pdf", {"buyer": "New"})


def test_listing_text_fits_without_losing_repeated_field_values(pdf,tmp_path):
    target=tmp_path/'long-name.pdf'
    name='A considerably longer seller legal name for the narrow contract field'
    kit_pdf.write_edits(pdf,target,{'buyer':name})
    kit_pdf.fit_listing_text(target)
    with fitz.open(target) as saved:
        for page in saved:
            widget=next(w for w in page.widgets() if w.field_name=='buyer')
            assert widget.field_value==name
            assert fitz.get_text_length(name,fontname='helv',fontsize=widget.text_fontsize)<=widget.rect.width-4
