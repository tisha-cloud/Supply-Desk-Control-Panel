"""
Turns any source file in BLR_Builders_Developers_Supply into Gemini `parts`.

PDFs and images go to the model natively so it sees the real page layout -
these decks put floor labels and areas in separate visual columns and any
text-only extraction scrambles them. Spreadsheets are transcribed to a grid
of text. PPTX contributes its text plus its embedded slide images.
"""
import io
import os
import re

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/png",
    ".tif": "image/png",
    ".tiff": "image/png",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
SHEET_EXTS = {".xlsx", ".xlsm", ".xls"}

MAX_IMAGE_EDGE = 1600
MAX_PPTX_IMAGES = 24


def classify(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return "PDF"
    if ext in IMAGE_EXTS:
        return "IMAGE"
    if ext in SHEET_EXTS:
        return "XLSX"
    if ext == ".pptx":
        return "PPTX"
    if ext in (".doc", ".docx"):
        return "DOCX"
    return "OTHER"


def _normalise_image(raw, ext):
    """Downscale oversized images so a slide deck's photos do not blow the request up."""
    try:
        from PIL import Image
    except ImportError:
        return raw, MIME_BY_EXT.get(ext, "image/jpeg")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return raw, MIME_BY_EXT.get(ext, "image/jpeg")

    if max(img.size) > MAX_IMAGE_EDGE:
        scale = MAX_IMAGE_EDGE / float(max(img.size))
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def _sheet_to_text(path):
    """Flatten a workbook to a readable grid, one block per sheet."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    blocks = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = []
            for cell in row:
                if cell is None:
                    cells.append("")
                elif isinstance(cell, float) and cell.is_integer():
                    cells.append(str(int(cell)))
                else:
                    cells.append(str(cell).replace("\n", " ").replace("\t", " ").strip())
            if any(c for c in cells):
                while cells and not cells[-1]:
                    cells.pop()
                rows.append(" | ".join(cells))
        if not rows:
            continue
        try:
            merged = [str(r) for r in ws.merged_cells.ranges]
        except Exception:
            merged = []
        header = "### SHEET: %s  (%d rows x %d cols)" % (ws.title, ws.max_row, ws.max_column)
        if merged:
            header += "\nmerged ranges: " + ", ".join(merged[:40])
        blocks.append(header + "\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(blocks)


def _pptx_parts(path, client):
    """Slide text plus every embedded picture, in slide order."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(path)
    lines = []
    images = []

    def walk(shapes, slide_no):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP and hasattr(shape, "shapes"):
                walk(shape.shapes, slide_no)
                continue
            if shape.has_text_frame and shape.text_frame.text.strip():
                lines.append("  " + shape.text_frame.text.strip().replace("\n", " / "))
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(cells):
                        lines.append("  TABLE | " + " | ".join(cells))
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE and len(images) < MAX_PPTX_IMAGES:
                try:
                    blob = shape.image.blob
                    ext = "." + (shape.image.ext or "jpg").lower()
                    images.append(_normalise_image(blob, ext))
                except Exception:
                    pass

    for idx, slide in enumerate(prs.slides, start=1):
        lines.append("--- SLIDE %d ---" % idx)
        walk(slide.shapes, idx)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            lines.append("  NOTES: " + slide.notes_slide.notes_text_frame.text.strip())

    parts = [client.text_part("PPTX TEXT CONTENT:\n" + "\n".join(lines))]
    if images:
        parts.append(client.text_part(
            "The %d slide images below follow in slide order; several are floor "
            "plans or availability tables rendered as pictures." % len(images)))
        for blob, mime in images:
            parts.append(client.inline_bytes(blob, mime))
    return parts


GREY_TOLERANCE = 24  # max channel spread still counted as black/white/grey body text


def _accent_colour(color_int):
    """
    Returns '#rrggbb' when a span is drawn in a saturated (non-grey) colour.

    These decks encode availability as coloured text - Prestige, for example,
    prints a building's whole floor stack in white and turns the vacant floors'
    areas green, with a green legend swatch. The colour never reaches the plain
    text layer, so we surface it explicitly rather than hoping the model
    notices the shading in the rendered page.
    """
    red = (color_int >> 16) & 0xFF
    green = (color_int >> 8) & 0xFF
    blue = color_int & 0xFF
    if max(red, green, blue) - min(red, green, blue) <= GREY_TOLERANCE:
        return None
    return "#%02x%02x%02x" % (red, green, blue)


def _pdf_text_hint(path, limit=26000):
    """
    Plain-text pass alongside the native PDF, annotated with text colour.

    Helps with tiny/rotated table text, and carries the colour coding that the
    rendered page conveys visually.
    """
    try:
        import pymupdf
    except ImportError:
        return ""
    try:
        doc = pymupdf.open(path)
    except Exception:
        return ""

    chunks = []
    total = 0
    for idx, page in enumerate(doc, start=1):
        try:
            data = page.get_text("dict")
        except Exception:
            continue

        lines_out = []
        accents = {}
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                parts = []
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    tag = _accent_colour(span.get("color", 0))
                    if tag:
                        accents[tag] = accents.get(tag, 0) + 1
                        parts.append("%s [colour %s]" % (text, tag))
                    else:
                        parts.append(text)
                if parts:
                    lines_out.append(" ".join(parts))

        if not lines_out:
            continue

        header = "--- PAGE %d ---" % idx
        if accents:
            summary = ", ".join("%s x%d" % (c, n) for c, n in
                                sorted(accents.items(), key=lambda kv: -kv[1]))
            header += "\n[accent text colours on this page: %s]" % summary
        block_text = header + "\n" + "\n".join(lines_out)
        chunks.append(block_text)
        total += len(block_text)
        if total > limit:
            chunks.append("... (text dump truncated; read the attached PDF pages directly)")
            break

    doc.close()
    return "\n".join(chunks)


def build_parts(path, client):
    """Return (parts, kind). `parts` is ready to drop into a Gemini request."""
    kind = classify(path)
    ext = os.path.splitext(path)[1].lower()

    if kind == "PDF":
        parts = [client.file_part(path, "application/pdf")]
        hint = _pdf_text_hint(path)
        if hint:
            parts.append(client.text_part(
                "Embedded text layer of the same PDF (page order preserved). Use it to confirm "
                "exact figures, but trust the rendered pages for which number belongs to which "
                "row/column.\n"
                "IMPORTANT: any span written in a saturated (non-grey) colour is tagged inline as "
                "'<text> [colour #rrggbb]', and each page lists its accent colours. These decks "
                "routinely mark VACANT space by colouring it - e.g. a floor-stack table printed in "
                "white/grey with the available floors' areas in green, next to a coloured legend "
                "swatch labelled 'Available'. Read the legend to learn what a colour means on that "
                "page, then use these tags to decide each floor's occupancy.\n" + hint))
        return parts, kind

    if kind == "IMAGE":
        with open(path, "rb") as fh:
            blob, mime = _normalise_image(fh.read(), ext)
        return [client.inline_bytes(blob, mime)], kind

    if kind == "XLSX":
        return [client.text_part("SPREADSHEET CONTENT:\n" + _sheet_to_text(path))], kind

    if kind == "PPTX":
        return _pptx_parts(path, client), kind

    return [client.text_part("Unsupported file type: " + os.path.basename(path))], kind


MONTHS = ("january february march april may june july august september october "
          "november december").split()


def guess_period(text):
    """Pull a 'July 2026' style report period out of a path or filename."""
    low = text.lower()
    month_re = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    m = re.search(month_re + r"[\s_\-.,/\\]*'?(20\d{2}|\d{2})\b", low)
    if m:
        stem = m.group(1)
        year = m.group(2)
        year = year if len(year) == 4 else "20" + year
        full = next((mo for mo in MONTHS if mo.startswith(stem)), stem)
        return full.capitalize() + " " + year
    m = re.search(r"\b(20\d{2})\b", low)
    return m.group(1) if m else ""
