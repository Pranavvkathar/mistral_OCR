"""
pdf_highlight.py
================
Service for generating an "Interleaved OCR Report" PDF.

This module takes the original uploaded PDF and the structured results from the
Mistral OCR API to build a new document where:
  1. Each original page is reproduced.
  2. Detected images (bbox_annotations) are highlighted with RED boxes.
  3. Detected tables are highlighted with BLUE boxes.
  4. A dedicated "Text Strip" is appended below each page showing the clean,
     extracted markdown text rendered with PyMuPDF's auto-wrapping text engine.

How it works:
  - We use PyMuPDF (fitz) to manipulate the PDF.
  - Mistral returns bounding boxes in a normalised 0–1000 coordinate system.
  - We convert these to PDF "points" (1/72 inch) based on the actual page dimensions.
  - We create a new, taller page for each original page to make room for the OCR text.
  - All rendering is done using built-in fonts (Helvetica) to ensure the file 
    is lightweight and Unicode-safe without needing external font files.

Drawing Logic:
  - top-left     (0, 0)   → top of the page
  - source pdf   (0, 0, w, h)
  - extra area   (0, h, w, h + extra_height)
"""

import re
import traceback
import fitz          # PyMuPDF — the industry-standard PDF manipulation library


# ─── Constants & Styling ──────────────────────────────────────────────────────

# Mistral OCR normalises all coordinates to a 1000x1000 grid regardless of
# the actual physical size of the page.
MISTRAL_GRID_SIZE = 1000.0

BODY_FONT_SIZE    = 9        # Font size for extracted text (pt)
LINE_HEIGHT_MULT  = 1.35     # Leading multiplier (line-height)
PAGE_MARGIN       = 10       # Left/right margin for text (pt)
HEADER_HEIGHT     = 22       # Height of the purple "EXTRACTED TEXT" bar (pt)

# Premium Color Palette (RGB 0-1)
# Using deep purples and high-contrast whites for a modern aesthetic.
COLOR_HEADER_BG = (0.18, 0.06, 0.38)   # Deep Purple
COLOR_HEADER_FG = (1.0,  1.0,  1.0)      # White
COLOR_BODY_TEXT = (0.05, 0.05, 0.12)   # Near-Black
COLOR_EMPTY_MSG = (0.45, 0.45, 0.50)   # Medium Grey
COLOR_BBOX_IMG  = (0.90, 0.10, 0.10)   # Vivid Red
COLOR_BBOX_TBL  = (0.10, 0.20, 0.90)   # Vivid Blue


# ─── BBox Extraction Helper ───────────────────────────────────────────────────

def _resolve_bbox_coordinates(bbox_object) -> list | None:
    """
    Normalises the bounding box coordinates returned by the Mistral SDK.

    Mistral's structured JSON for images/tables can store coordinates in
    a few different attributes depending on the specific model/SDK version:
      1. Flat attributes (top_left_x, top_left_y, ...)
      2. A nested .bbox list [x0, y0, x1, y1]
      3. A nested .bbox object with .top_left and .bottom_right sub-objects

    Returns:
        [x0, y0, x1, y1] if successful, else None.
    """
    if bbox_object is None:
        return None

    # Handle Flat Attributes (Common in the Mistral SDK 1.x / V0)
    if hasattr(bbox_object, "top_left_x"):
        try:
            return [
                float(bbox_object.top_left_x),     float(bbox_object.top_left_y),
                float(bbox_object.bottom_right_x), float(bbox_object.bottom_right_y)
            ]
        except (TypeError, ValueError, AttributeError):
            pass

    # Handle Nested .bbox attribute
    raw_bbox = getattr(bbox_object, "bbox", None)
    if raw_bbox is None:
        return None

    # bbox as a list: [x0, y0, x1, y1]
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            return [float(c) for c in raw_bbox]
        except (TypeError, ValueError):
            pass

    # bbox as an object with .top_left and .bottom_right
    if hasattr(raw_bbox, "top_left") and hasattr(raw_bbox, "bottom_right"):
        tl, br = raw_bbox.top_left, raw_bbox.bottom_right
        try:
            # Check for .x / .y attributes
            if hasattr(tl, "x"):
                return [float(tl.x), float(tl.y), float(br.x), float(br.y)]
            # Check for list [x, y] format
            if isinstance(tl, (list, tuple)):
                return [float(tl[0]), float(tl[1]), float(br[0]), float(br[1])]
        except (TypeError, ValueError):
            pass

    return None


# ─── Text Cleaning Helper ─────────────────────────────────────────────────────

def _strip_markdown_for_rendering(markdown_text: str) -> str:
    """
    Cleans markdown syntax so the plain text looks professional in the PDF.

    We remove:
      - Image references like ![img.png](...)
      - Heading markers (# ## ###)
      - Bold/Italic stars (* **)
      - Horizontal rules (---)
      - Links (converting [text](url) → text)
    """
    text = markdown_text or ""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)                      # Remove images
    text = re.sub(r'^\s*#{1,6}\s+', '', text, flags=re.MULTILINE)   # Remove headers
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)             # Remove bold/italic
    text = re.sub(r'^\s*---+\s*$', '', text, flags=re.MULTILINE)    # Remove separators
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)           # Remove links
    text = re.sub(r'`+', '', text)                                   # Remove code ticks
    return text.strip()


# ─── Height Estimation ────────────────────────────────────────────────────────

def _estimate_text_strip_height(text: str, page_width: float) -> float:
    """
    Estimates the height (in points) needed to display the extracted text strip.

    Calculation:
      - Calculates characters per line based on page width.
      - Counts manual newlines and estimates wrapped lines.
      - Adds fixed height for the header bar and margins.
    """
    if not text:
        return float(HEADER_HEIGHT + 30)

    # Simple char-width estimation (Helvetica is ~0.55em wide on average)
    available_width = page_width - (2 * PAGE_MARGIN)
    chars_per_line  = max(1, int(available_width / (BODY_FONT_SIZE * 0.55)))

    # Count estimated lines
    raw_paragraphs = text.split("\n")
    total_lines    = 0
    for para in raw_paragraphs:
        # Every paragraph takes at least 1 line, plus extra for wrapping
        total_lines += max(1, int(len(para) / chars_per_line) + 1)

    # Points needed = (Header + Margins + (Lines * line_height))
    line_h = BODY_FONT_SIZE * LINE_HEIGHT_MULT
    needed = HEADER_HEIGHT + (total_lines * line_h) + (PAGE_MARGIN * 2)

    # Cap page height at 14 inches (1008 pts) to prevent creating invalid PDF pages
    return float(max(40, min(needed, 1008)))


# ─── Main Export Function ─────────────────────────────────────────────────────

def highlight_text_in_pdf(
    original_pdf_path: str,
    output_pdf_path:   str,
    extracted_text:    str,
    ocr_response,
) -> str:
    """
    Generates a new PDF report with bounding box highlights and text strips.

    Pipeline:
      1. Opens the source PDF.
      2. Iterates through each page.
      3. Draws RED boxes around detected images and BLUE boxes around tables.
      4. Appends a new section at the bottom of the page containing the clean OCR text.
      5. Saves the final production PDF to disk.
    """
    src_pdf       = fitz.open(original_pdf_path)
    report_pdf    = fitz.open()   # Create a new, empty PDF document
    mistral_pages = getattr(ocr_response, "pages", []) or []

    print(f"[PDF] Generating report: {len(src_pdf)} pages")

    for i, source_page in enumerate(src_pdf):
        try:
            # Get dimensions (handles rotated pages correctly)
            width  = source_page.rect.width
            height = source_page.rect.height
            rot    = source_page.rotation  # 0, 90, 180, or 270

            # Get OCR data for this specific page
            page_data = mistral_pages[i] if i < len(mistral_pages) else None
            markdown  = (getattr(page_data, "markdown", "") or "") if page_data else ""
            cleaned_text = _strip_markdown_for_rendering(markdown)

            page_images = list(getattr(page_data, "images", []) or []) if page_data else []
            page_tables = list(getattr(page_data, "tables", []) or []) if page_data else []

            # ── Step A: Create the new, larger page ───────────────────────────
            #
            # We add "extra_height" to the bottom of each page to fit the OCR text.
            extra_h = _estimate_text_strip_height(cleaned_text, width)

            # PyMuPDF correctly handles rotation if we swap W/H appropriately
            if rot in (90, 270):
                new_page = report_pdf.new_page(width=height + extra_h, height=width)
            else:
                new_page = report_pdf.new_page(width=width, height=height + extra_h)

            new_page.set_rotation(rot)

            # ── Step B: Copy original PDF content ─────────────────────────────
            #
            # We place the original page content inside the top rectangle (0, 0, w, h).
            # The remaining bottom area (h, w, h+extra_h) will be our text strip.
            new_page.show_pdf_page(fitz.Rect(0, 0, width, height), src_pdf, i)

            # ── Step C: Draw Bounding Boxes ───────────────────────────────────
            #
            # Coordinate Conversion:
            #   Mistral (0-1000) → PDF Points (actual width/height)
            #   pdf_x = (mistral_x / 1000) * actual_width

            # Draw IMAGES in RED
            for img in page_images:
                coords = _resolve_bbox_coordinates(img)
                if coords:
                    rect = fitz.Rect(
                        coords[0] * width  / MISTRAL_GRID_SIZE, coords[1] * height / MISTRAL_GRID_SIZE,
                        coords[2] * width  / MISTRAL_GRID_SIZE, coords[3] * height / MISTRAL_GRID_SIZE
                    )
                    new_page.draw_rect(rect, color=COLOR_BBOX_IMG, width=2.0)

            # Draw TABLES in BLUE
            for tbl in page_tables:
                coords = _resolve_bbox_coordinates(tbl)
                if coords:
                    rect = fitz.Rect(
                        coords[0] * width  / MISTRAL_GRID_SIZE, coords[1] * height / MISTRAL_GRID_SIZE,
                        coords[2] * width  / MISTRAL_GRID_SIZE, coords[3] * height / MISTRAL_GRID_SIZE
                    )
                    new_page.draw_rect(rect, color=COLOR_BBOX_TBL, width=2.0)

            # ── Step D: Render the Text Strip ─────────────────────────────────

            strip_y_start    = height
            strip_y_end      = height + extra_h
            header_bar_end   = strip_y_start + HEADER_HEIGHT

            # 1. Header background (Deep Purple)
            new_page.draw_rect(
                fitz.Rect(0, strip_y_start, width, header_bar_end),
                color=None,
                fill=COLOR_HEADER_BG,
            )

            # 2. Header text
            new_page.insert_text(
                (PAGE_MARGIN, header_bar_end - 6),
                f"PAGE {i + 1}  \u2014  MISTRAL OCR EXTRACTED TEXT",
                fontname="hebo",   # Helvetica-Bold
                fontsize=8,
                color=COLOR_HEADER_FG,
            )

            # 3. Body OCR Text (Auto-wrapping textbox)
            text_rect = fitz.Rect(
                PAGE_MARGIN,
                header_bar_end + 6,
                width - PAGE_MARGIN,
                strip_y_end - PAGE_MARGIN
            )

            if cleaned_text:
                new_page.insert_textbox(
                    text_rect,
                    cleaned_text,
                    fontname="helv",   # Helvetica
                    fontsize=BODY_FONT_SIZE,
                    lineheight=LINE_HEIGHT_MULT,
                    color=COLOR_BODY_TEXT,
                    align=0            # Left align
                )
            else:
                new_page.insert_text(
                    (PAGE_MARGIN, header_bar_end + 18),
                    "[No extractable text found on this page]",
                    fontname="helv",
                    fontsize=8,
                    color=COLOR_EMPTY_MSG
                )

            print(f"[PDF]   Page {i+1} processed successfully.")

        except Exception as page_err:
            print(f"[PDF]   Page {i+1} failed: {page_err}")
            traceback.print_exc()
            # If a complex page fails, we try to at least provide a plain copy
            # so the report isn't completely missing pages.
            try:
                fallback_page = report_pdf.new_page(width=source_page.rect.width, height=source_page.rect.height)
                fallback_page.set_rotation(source_page.rotation)
                fallback_page.show_pdf_page(source_page.rect, src_pdf, i)
                print(f"[PDF]   Page {i+1} fallback plain copy used.")
            except:
                pass

    # 4. Finalise and Save
    report_pdf.save(output_pdf_path)
    report_pdf.close()
    src_pdf.close()

    print(f"[PDF] ✓ Report generated → {output_pdf_path}")
    return output_pdf_path
