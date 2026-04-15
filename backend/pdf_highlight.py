"""
pdf_highlight.py
Creates an interleaved OCR report PDF:
  • Each source page is reproduced with coloured bounding-box overlays.
    Red  = images / figures  |  Blue = tables
  • A text strip with the OCR-extracted text is appended directly below each page.
    Rendered with PyMuPDF native text tools — fully Unicode safe, no ReportLab needed.
"""

import re
import traceback
import fitz          # PyMuPDF


# ── Constants ──────────────────────────────────────────────────────────────────
GRID      = 1000.0   # Mistral normalises bbox to 0–1000 per axis
FONT_S    = 9        # body font size (pt)
LINE_LEAD = 1.35     # line-height multiplier
MARGIN    = 10       # horizontal margin (pt)
HEADER_H  = 22       # height of the coloured page-header bar (pt)

# Deep-purple header colours (RGB 0-1)
HEADER_BG  = (0.18, 0.06, 0.38)
HEADER_FG  = (1.0,  1.0,  1.0)
BODY_FG    = (0.05, 0.05, 0.12)
EMPTY_FG   = (0.45, 0.45, 0.50)


# ── BBox normaliser ────────────────────────────────────────────────────────────

def _extract_bbox(obj) -> list | None:
    """
    Extract [x0, y0, x1, y1] from a Mistral OCR image or table object.

    Handles all known SDK versions / formats:
      1. Mistral v0 SDK  — flat individual attrs: top_left_x, top_left_y,
                           bottom_right_x, bottom_right_y  (confirmed from debug)
      2. Generic object  — .top_left / .bottom_right with .x/.y sub-attrs
      3. Nested .bbox    — list [x0,y0,x1,y1]  OR  object  OR  dict
    """
    if obj is None:
        return None

    # ── Format 1: Mistral v0 — flat attributes on the image/table object ──────
    if hasattr(obj, "top_left_x"):
        try:
            return [
                float(obj.top_left_x),  float(obj.top_left_y),
                float(obj.bottom_right_x), float(obj.bottom_right_y),
            ]
        except (TypeError, ValueError, AttributeError):
            pass

    # ── Format 2+3: Nested .bbox attribute ───────────────────────────────────
    raw = getattr(obj, "bbox", None)
    if raw is None:
        return None

    # 2a. Plain list / tuple of 4 numbers
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            return [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])]
        except (TypeError, ValueError):
            pass

    # 2b. Object with .top_left / .bottom_right having .x / .y
    if hasattr(raw, "top_left") and hasattr(raw, "bottom_right"):
        tl, br = raw.top_left, raw.bottom_right
        try:
            if hasattr(tl, "x"):
                return [float(tl.x), float(tl.y), float(br.x), float(br.y)]
            if isinstance(tl, (list, tuple)):
                return [float(tl[0]), float(tl[1]), float(br[0]), float(br[1])]
        except (TypeError, ValueError):
            pass

    # 2c. Dict with top_left / bottom_right keys
    if isinstance(raw, dict):
        tl = raw.get("top_left")
        br = raw.get("bottom_right")
        if tl and br:
            try:
                if isinstance(tl, dict):
                    return [float(tl.get("x", 0)), float(tl.get("y", 0)),
                            float(br.get("x", 0)), float(br.get("y", 0))]
                if isinstance(tl, (list, tuple)):
                    return [float(tl[0]), float(tl[1]), float(br[0]), float(br[1])]
            except (TypeError, ValueError):
                pass

    return None


# ── Markdown → plain text ──────────────────────────────────────────────────────

def _clean(md: str) -> str:
    """Strip markdown syntax so plain text renders cleanly in the PDF."""
    md = re.sub(r'!\[.*?\]\(.*?\)', '', md)                       # image refs
    md = re.sub(r'^\s*#{1,6}\s+', '', md, flags=re.MULTILINE)    # headings
    md = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', md)              # bold/italic
    md = re.sub(r'^\s*---+\s*$', '', md, flags=re.MULTILINE)     # hr (but NOT table seps)
    md = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', md)            # links → text only
    md = re.sub(r'`+', '', md)                                    # backticks
    return md.strip()


# ── Text-strip height estimator ────────────────────────────────────────────────

def _estimate_extra_h(text: str, page_width: float) -> float:
    """
    Estimate the height needed for the text strip using PyMuPDF's built-in
    text measurement, then add header + margins.
    """
    if not text:
        return float(HEADER_H + 30)

    # Use PyMuPDF's font metrics to measure how many lines we need.
    # fontsize=FONT_S, line-height factor LINE_LEAD.
    chars_per_line = max(1, int((page_width - 2 * MARGIN) / (FONT_S * 0.55)))
    raw_lines = text.split("\n")
    wrapped_count = 0
    for ln in raw_lines:
        wrapped_count += max(1, int(len(ln) / chars_per_line) + 1)

    line_h  = FONT_S * LINE_LEAD
    needed  = HEADER_H + wrapped_count * line_h + MARGIN * 2
    capped  = min(needed, 14 * 72)   # cap at 14 inches (1008 pt)
    return float(max(capped, HEADER_H + 40))


# ── Main export ────────────────────────────────────────────────────────────────

def highlight_text_in_pdf(input_pdf_path: str, output_pdf_path: str,
                           ocr_text: str, ocr_response) -> str:
    """
    Build the interleaved OCR report PDF.

    All drawing is done with PyMuPDF native methods (Unicode-safe, no ReportLab).
    All page logic is inside the 'for i, src_page' loop so index 'i' is always
    in scope — no helper functions that lose the loop variable.
    """
    src_doc       = fitz.open(input_pdf_path)
    res_doc       = fitz.open()
    mistral_pages = getattr(ocr_response, "pages", []) or []

    print(f"[PDF] Building report: {len(src_doc)} src pages | "
          f"{len(mistral_pages)} OCR pages")

    for i, src_page in enumerate(src_doc):
        try:
            w = src_page.rect.width    # visual width  (after rotation)
            h = src_page.rect.height   # visual height (after rotation)
            r = src_page.rotation      # 0 / 90 / 180 / 270

            # ── Retrieve Mistral OCR data for this page ────────────────────
            m_page  = mistral_pages[i] if i < len(mistral_pages) else None
            raw_md  = (getattr(m_page, "markdown", "") or "") if m_page else ""
            cleaned = _clean(raw_md)

            images = list(getattr(m_page, "images",  None) or []) if m_page else []
            tables = list(getattr(m_page, "tables",  None) or []) if m_page else []

            # ── Debug: show first image attributes on page 1 ─────────────
            if i == 0 and images:
                img0   = images[0]
                b_test = _extract_bbox(img0)
                print(f"[PDF Debug] Page 1 image bbox resolved to: {b_test}")

            # ── Calculate text strip height ────────────────────────────────
            extra_h = _estimate_extra_h(cleaned, w)

            # ── Create new (taller) page ───────────────────────────────────
            if r in (90, 270):
                new_page = res_doc.new_page(width=h + extra_h, height=w)
            else:
                new_page = res_doc.new_page(width=w, height=h + extra_h)
            new_page.set_rotation(r)

            # ── Copy original source page into the top section ─────────────
            # show_pdf_page uses VISUAL coordinates, so (0,0,w,h) is always correct.
            new_page.show_pdf_page(fitz.Rect(0, 0, w, h), src_doc, i)

            # ── Draw bounding boxes ────────────────────────────────────────
            for img_obj in images:
                b = _extract_bbox(img_obj)
                if b:
                    try:
                        rect = fitz.Rect(b[0] * w / GRID, b[1] * h / GRID,
                                         b[2] * w / GRID, b[3] * h / GRID)
                        new_page.draw_rect(rect, color=(0.9, 0.1, 0.1),
                                           fill=None, width=2.5)
                    except Exception as be:
                        print(f"[PDF]   Page {i+1}: image bbox draw error: {be}")

            for tbl_obj in tables:
                b = _extract_bbox(tbl_obj)
                if b:
                    try:
                        rect = fitz.Rect(b[0] * w / GRID, b[1] * h / GRID,
                                         b[2] * w / GRID, b[3] * h / GRID)
                        new_page.draw_rect(rect, color=(0.1, 0.2, 0.9),
                                           fill=None, width=2.5)
                    except Exception as be:
                        print(f"[PDF]   Page {i+1}: table bbox draw error: {be}")

            # ── Render text strip directly on the new page ─────────────────
            # The text strip lives in the VISUAL region (0, h) → (w, h+extra_h).
            # For r=0 / r=180, visual coords == pre-transform coords, so
            # PyMuPDF's native draw/text functions work as-is.
            # For r=90 / r=270, the strip ends up at the page "right side" visually
            # but still shows the correct content.

            strip_top    = h                          # top of strip in visual y
            strip_bottom = h + extra_h                # bottom of strip
            header_bot   = strip_top + HEADER_H       # bottom of header bar

            # Coloured header background
            new_page.draw_rect(
                fitz.Rect(0, strip_top, w, header_bot),
                color=None,
                fill=HEADER_BG,
            )

            # Header label
            new_page.insert_text(
                (MARGIN, header_bot - 6),
                f"PAGE {i + 1}  \u2014  EXTRACTED OCR TEXT",
                fontname="hebo",          # Helvetica-Bold (built-in)
                fontsize=8,
                color=HEADER_FG,
            )

            # Body text — PyMuPDF insert_textbox is Unicode-safe and auto-wraps
            body_rect = fitz.Rect(
                MARGIN,
                header_bot + 4,
                w - MARGIN,
                strip_bottom - 4,
            )

            if cleaned:
                overflow = new_page.insert_textbox(
                    body_rect,
                    cleaned,
                    fontname="helv",      # Helvetica (built-in)
                    fontsize=FONT_S,
                    lineheight=LINE_LEAD,
                    color=BODY_FG,
                    align=0,              # left-align
                )
                if overflow < 0:
                    # Some text was clipped — increase extra_h estimate next time
                    print(f"[PDF]   Page {i+1}: WARNING text overflow "
                          f"({-overflow:.0f}pt clipped — "
                          f"full text is in Raw Text tab)")
            else:
                new_page.insert_text(
                    (MARGIN, header_bot + 18),
                    "[No text extracted from this page]",
                    fontname="helv",
                    fontsize=8,
                    color=EMPTY_FG,
                )

            print(f"[PDF]   Page {i + 1}: OK  "
                  f"(text={len(cleaned)}chars, strip={extra_h:.0f}pt, "
                  f"imgs={len(images)}, tables={len(tables)})")

        except Exception as e:
            print(f"[PDF] Page {i+1} FAILED: {e}")
            traceback.print_exc()

            # Remove any partially-created page before adding the fallback copy
            if len(res_doc) > i:
                res_doc.delete_page(-1)

            try:
                w2 = src_page.rect.width
                h2 = src_page.rect.height
                fb = res_doc.new_page(width=w2, height=h2)
                fb.set_rotation(src_page.rotation)
                fb.show_pdf_page(fitz.Rect(0, 0, w2, h2), src_doc, i)
                print(f"[PDF]   Page {i+1}: fallback plain copy saved")
            except Exception as fe:
                print(f"[PDF]   Page {i+1}: fallback also failed: {fe}")

    res_doc.save(output_pdf_path)
    res_doc.close()
    src_doc.close()
    print(f"[PDF] Report saved: {output_pdf_path}")
    return output_pdf_path
