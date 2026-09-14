import re

import fitz

from elevate_cli.web_routes import kit_pdf, kit_terms


def compact(text):
    return re.sub(r"\s+", "", text)


def make_pdf(path, text):
    with fitz.open() as pdf:
        for name, height in [("txtAddSchedule", 180), ("txtAddSchedule2", 510)]:
            page = pdf.new_page(width=612, height=792)
            w = fitz.Widget()
            w.field_name = name
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            w.field_flags = 4096
            w.rect = fitz.Rect(42, 90, 570, 90 + height)
            w.field_value = text if name == "txtAddSchedule" else ""
            page.add_widget(w)
        pdf.save(path)


def assert_visible(path, expected):
    with fitz.open(path) as pdf:
        assert compact(kit_terms.text_from(pdf)) == compact(expected)
        for page in pdf:
            for w in page.widgets() or []:
                if not kit_terms.is_terms(w.field_name):
                    continue
                assert w.text_fontsize == kit_terms.FONT_SIZE
                # Check the actual appearance, not just the AcroForm value.
                visible = page.get_text(clip=w.rect)
                assert compact(visible) == compact(w.field_value or "")
        return len(pdf)


def test_paragraphs_flow_and_extra_pages_remain_editable(tmp_path):
    path = tmp_path / "terms.pdf"
    clauses = [f"{i}) " + (f"Clause {i} must remain readable and complete. " * 7) for i in range(1, 25)]
    text = "Subject to approval:\n\n" + "\n".join(clauses)
    make_pdf(path, text)
    kit_terms.reflow(path)
    count = assert_visible(path, text)
    assert count > 2
    with fitz.open(path) as pdf:
        assert kit_terms.managed(pdf)
        assert "\n\n" in kit_terms.text_from(pdf)
        fields = [w.field_value for p in pdf for w in (p.widgets() or [])]
        assert all(any(clause.strip() in value for value in fields) for clause in clauses)
    # Repeated layout does not duplicate text or add another set of pages.
    kit_terms.reflow(path)
    assert assert_visible(path, text) == count
    kit_terms.reflow(path, "One short paragraph.")
    assert assert_visible(path, "One short paragraph.") == 2


def test_pdf_edit_reflows_and_redraft_preserves_complete_edited_terms(tmp_path):
    path, saved, redraft = (tmp_path / n for n in ("draft.pdf", "saved.pdf", "redraft.pdf"))
    make_pdf(path, "Original clause.")
    kit_terms.reflow(path)
    text = "\n\n".join(f"{i}) " + "New edited wording. " * 25 for i in range(1, 20))
    kit_pdf.write_edits(path, saved, {"txtAddSchedule": text})
    assert assert_visible(saved, text) > 2
    make_pdf(redraft, "New wizard text.")
    kit_terms.reflow(redraft)
    kit_pdf.reapply_edits(redraft, {"pdfTermsOverride": text})
    assert_visible(redraft, text)
    # A deliberate clear also survives redrafting.
    kit_pdf.reapply_edits(redraft, {"pdfTermsOverride": ""})
    assert assert_visible(redraft, "") == 2


def test_one_oversized_paragraph_is_never_truncated(tmp_path):
    path = tmp_path / "long.pdf"
    text = "An unusually long paragraph must retain every word. " * 200
    make_pdf(path, text)
    kit_terms.reflow(path)
    assert assert_visible(path, text) > 2


def test_continuation_uses_the_actual_cps_page_design_and_address(tmp_path):
    path = tmp_path / "cps-page.pdf"
    make_pdf(path, "\n\n".join(f"{i}) " + "Readable CPS subject. " * 40 for i in range(1, 20)))
    with fitz.open(path) as pdf:
        for page in pdf:
            for w in page.widgets() or []:
                if w.field_name == "txtp_streetnum": w.field_value = "1395"; w.update()
                if w.field_name == "txtp_street": w.field_value = "Ellis Street"; w.update()
                if w.field_name == "txtp_city": w.field_value = "Kelowna"; w.update()
        pdf.saveIncr()
    kit_terms.reflow(path)
    with fitz.open(path) as pdf:
        continuation = next(page for page in pdf if any(w.field_name == "elevateTermsContinuation1" for w in page.widgets() or []))
        assert "Section 3 - Terms and Conditions (continued)" not in continuation.get_text()
        assert "Services Act." in continuation.get_text()
        assert "PAGE 4 of" in continuation.get_text()
        assert any(w.field_name.endswith("_address_city") for w in continuation.widgets() or [])


def test_extra_terms_insert_before_the_next_contract_section(tmp_path):
    path = tmp_path / "middle.pdf"
    text = "\n\n".join(f"{i}) " + "A complete subject paragraph. " * 30 for i in range(20))
    make_pdf(path, text)
    with fitz.open(path) as pdf:
        page = pdf.new_page()
        page.insert_text((42, 50), "Next contract section and signatures")
        pdf.saveIncr()
    kit_terms.reflow(path)
    with fitz.open(path) as pdf:
        assert len(pdf) > 3
        assert "Next contract section and signatures" in pdf[-1].get_text()
        assert any(w.field_name.startswith(kit_terms.EXTRA_PREFIX) for w in pdf[2].widgets() or [])
    kit_terms.reflow(path)
    with fitz.open(path) as pdf:
        assert "Next contract section and signatures" in pdf[-1].get_text()
