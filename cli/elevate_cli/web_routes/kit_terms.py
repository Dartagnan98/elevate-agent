"""Readable, editable CPS terms that flow through schedule and continuation pages."""
import re
from pathlib import Path

FONT_SIZE = 11
EXTRA_PREFIX = "elevateTermsContinuation"
MARKER = "ElevateTermsLayout"
RESIDENTIAL_TEMPLATE = "/Users/admin/skyleigh-tools/knowledge/deals/forms/cps-residential-fillable-template.pdf"


def is_terms(name):
    return bool(re.fullmatch(r"txtAddSchedule\d*", name, re.I) or
                (name.startswith(EXTRA_PREFIX) and "_address_" not in name))


def managed(pdf):
    return pdf.xref_get_key(pdf.pdf_catalog(), MARKER) == ("bool", "true")


def text_from(pdf):
    return "\n\n".join(w.field_value.strip() for p in pdf for w in (p.widgets() or [])
                       if is_terms(w.field_name) and (w.field_value or "").strip())


def paragraphs(text):
    # The assembler emits each numbered subject on its own line. Preserve
    # explicit paragraph boundaries and separate adjacent numbered subjects.
    text = re.sub(r"\n(?=\d+[).]\s)", "\n\n", text.strip())
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]


def _wrap(text, width):
    import fitz
    font = fitz.Font("helv")
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if font.text_length(candidate, fontsize=FONT_SIZE) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        # Long URLs / unbroken text must not disappear beyond the field edge.
        for char in word:
            if line and font.text_length(line + char, fontsize=FONT_SIZE) > width:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines


def reflow(path, text=None, template_path=None):
    """Replace layout atomically; preserve wording and every non-terms widget.

    Original form pages remain intact. Extra pages are inserted and explicitly
    identified as Section 3 continuations, without renumbering the base form.
    """
    import fitz
    from elevate_cli.web_routes.kit_state import version_path
    output = version_path(path)
    try:
        with fitz.open(path) as pdf:
            content = text_from(pdf) if text is None else text
            original = paragraphs(content)
            pending = list(original)
            extra_pages = [p.number for p in pdf if any(
                w.field_name.startswith(EXTRA_PREFIX) for w in (p.widgets() or []))]
            for index in reversed(extra_pages):
                pdf.delete_page(index)
            for page in pdf:
                for annot in list(page.annots() or []):
                    if annot.info.get("title") == "ElevateTermsContinuationLink":
                        page.delete_annot(annot)
            slots = [(p.number, w.xref) for p in pdf for w in (p.widgets() or [])
                     if is_terms(w.field_name)]
            if not slots:
                raise ValueError("This form has no terms schedule to lay out.")
            last_slot = slots[-1]
            fields = {w.field_name.lower(): str(w.field_value or "") for p in pdf for w in (p.widgets() or [])}
            address = " ".join(fields.get(k, "") for k in
                               ("txtp_unitnumber", "txtp_streetnum", "txtp_street", "txtp_city", "txtp_state", "txtp_zipcode")).strip()
            extra = 0
            used = []
            # A conservative line allowance includes PDF widget padding and
            # leading. Whole paragraphs move to the next box when they fit there.
            while slots or pending:
                if slots:
                    index, xref = slots.pop(0)
                    page = pdf[index]
                    widget = page.load_widget(xref)
                else:
                    extra += 1
                    if extra > 100:
                        raise ValueError("Terms exceed 100 continuation pages. Shorten the text before saving.")
                    page = pdf.new_page(pno=last_slot[0] + extra,
                                        width=pdf[last_slot[0]].rect.width,
                                        height=pdf[last_slot[0]].rect.height)
                    try:
                        template = fitz.open(template_path or RESIDENTIAL_TEMPLATE)
                        template_page = max((p.number for p in template
                                             if any(is_terms(w.field_name) for w in (p.widgets() or []))),
                                            default=4)
                        page.show_pdf_page(page.rect, template, template_page)
                        template.close()
                    except Exception:
                        page.show_pdf_page(page.rect, pdf, last_slot[0])
                    addr_rects = ((26.97, 23.65, 68.46, 36.93),
                                  (68.88, 23.65, 110.37, 36.93),
                                  (110.79, 23.65, 276.34, 36.93),
                                  (277.17, 23.65, 403.73, 36.93),
                                  (404.14, 23.65, 427.38, 36.93),
                                  (427.80, 23.65, 475.10, 36.93))
                    for ix, (name, key) in enumerate((("unit", "txtp_unitnumber"), ("streetnum", "txtp_streetnum"), ("street", "txtp_street"), ("city", "txtp_city"), ("state", "txtp_state"), ("zip", "txtp_zipcode"))):
                        aw = fitz.Widget()
                        aw.field_name = f"{EXTRA_PREFIX}{extra}_address_{name}"
                        aw.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                        aw.rect = fitz.Rect(*addr_rects[ix])
                        aw.field_value = fields.get(key, "")
                        aw.border_width = 0
                        aw.text_fontsize = 9
                        added = page.add_widget(aw)
                        added.field_value = aw.field_value
                        added.update()
                    page.insert_text((476, 31), "PAGE 4 of 10 PAGES", fontsize=9)
                    widget = fitz.Widget()
                    widget.field_name = f"{EXTRA_PREFIX}{extra}"
                    widget.field_label = f"Terms and conditions continuation {extra}"
                    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                    widget.rect = fitz.Rect(42.21, 90.96, 583.42, 620.61)
                    widget.field_flags = 4096
                    added = page.add_widget(widget)
                    widget = page.load_widget(added.xref)
                width = widget.rect.width - 12
                capacity = max(1, int((widget.rect.height - 14) / (FONT_SIZE * 1.35)))
                chunks, remaining = [], capacity
                while pending:
                    lines = _wrap(pending[0], width)
                    cost = len(lines) + (1 if chunks else 0)
                    if cost <= remaining:
                        chunks.append(pending.pop(0))
                        remaining -= cost
                    elif chunks:
                        break
                    else:
                        next_capacity = 40  # Full continuation page at 11pt.
                        if slots:
                            ni, nx = slots[0]
                            nw = pdf[ni].load_widget(nx)
                            next_capacity = int((nw.rect.height - 14) / (FONT_SIZE * 1.35))
                        if len(lines) <= next_capacity and len(lines) > capacity:
                            break
                        # A paragraph larger than a whole page must split, but
                        # never truncate. Break at a measured line boundary.
                        chunks.append(" ".join(lines[:capacity]))
                        pending[0] = " ".join(lines[capacity:])
                        break
                value = "\n\n".join(chunks)
                widget.field_value = value
                widget.text_font = "Helv"
                widget.text_fontsize = FONT_SIZE
                widget.text_color = (0, 0, 0)
                widget.field_flags |= 4096
                # The template's single-box character cap no longer applies
                # once saving can add continuation pages.
                widget.text_maxlen = 0
                pdf.xref_set_key(widget.xref, "MaxLen", "null")
                typ, parent = pdf.xref_get_key(widget.xref, "Parent")
                if typ == "xref":
                    pdf.xref_set_key(int(parent.split()[0]), "MaxLen", "null")
                # MuPDF needs /V explicitly cleared for an empty field.
                if not value:
                    pdf.xref_set_key(widget.xref, "V", "()")
                widget.update()
                used.extend(chunks)
            if extra:
                total = max(1, len(pdf) - 2)
                for pno in range(2, len(pdf)):
                    page = pdf[pno]
                    page.draw_rect(fitz.Rect(474, 13, 590, 37), color=None, fill=(1, 1, 1), overlay=True)
                    page.draw_line(fitz.Point(42, 23), fitz.Point(473, 23), color=(0, 0, 0), width=0.5, overlay=True)
                    page.insert_text((476, 31), f"PAGE {pno - 1} of {total} PAGES", fontsize=9, overlay=True)
            # Preserve characters and order, independently of page boundaries.
            if "".join("".join(used).split()) != "".join("".join(original).split()):
                raise ValueError("Terms layout did not retain all text. The previous PDF is unchanged.")
            pdf.xref_set_key(pdf.pdf_catalog(), MARKER, "true")
            pdf.save(output, garbage=3, deflate=True)
        Path(output).replace(path)
    finally:
        Path(output).unlink(missing_ok=True)
