import os
import re
import time
import base64
import traceback
import httpx
import fitz  # PyMuPDF
from dotenv import load_dotenv

# ── SDK imports ───────────────────────────────────────────────────────────────
from mistralai.client import Mistral
from mistralai.extra import response_format_from_pydantic_model

from annotations import ImageAnnotation, DocumentAnnotation

load_dotenv()

api_key = os.getenv("MISTRAL_API_KEY")

# 600-second timeout for large OCR calls
_timeout = httpx.Timeout(600.0, connect=60.0, read=600.0, write=60.0)
_http    = httpx.Client(timeout=_timeout)

client = Mistral(api_key=api_key, client=_http)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _encode_file(file_path: str) -> str:
    """Encode a file to a base64 data URL suitable for the Mistral OCR API."""
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:application/pdf;base64,{b64}"


def _has_real_text(markdown: str) -> bool:
    """Return True if the markdown contains real text beyond image placeholders."""
    cleaned = re.sub(r'!\[.*?\]\(.*?\)', '', markdown or '').strip()
    return len(cleaned) > 10


def _log_page(global_idx: int, page) -> None:
    """Print a one-liner diagnostic for a single processed page."""
    md        = getattr(page, "markdown", "") or ""
    img_count = len(getattr(page, "images", []) or [])
    tbl_count = len(getattr(page, "tables", []) or [])
    has_text  = _has_real_text(md)

    if has_text:
        status = "✓ text"
    elif img_count > 0:
        status = "⚠ img-only (scanned?)"
    else:
        status = "✗ empty"

    print(f"  Page {global_idx + 1:3d}: {len(md):5d} chars | "
          f"{img_count} img(s) | {tbl_count} table(s) | {status}")


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def process_ocr_with_annotations(file_path: str, include_images: bool = False):
    """
    Encodes the PDF as base64 and sends it directly to Mistral OCR,
    processing every page in chunks of 5.

    Returns (ocr_response, stats_dict, clean_text_string).
    On failure returns (None, None, error_string).
    """
    start_time = time.time()

    try:
        # ── 0. Count pages & encode file ──────────────────────────────────────
        doc = fitz.open(file_path)
        total_pages = len(doc)
        doc.close()
        print(f"\n[OCR] ── Start: '{os.path.basename(file_path)}' "
              f"({total_pages} pages) ──────────────────────")

        print("[OCR] Step 1/3 — Encoding file as base64...")
        document_url = _encode_file(file_path)
        print(f"[OCR] Encoded OK ({len(document_url) // 1024} KB data URL)")

        # ── 1. Chunk-process every page ───────────────────────────────────────
        CHUNK_SIZE   = 5      # pages per API call
        MAX_RETRIES  = 3
        all_pages    = []
        chunk_response = None
        total_chunks   = (total_pages + CHUNK_SIZE - 1) // CHUNK_SIZE

        print(f"[OCR] Step 2/3 — Running OCR on {total_pages} pages "
              f"in {total_chunks} chunk(s)...")

        for chunk_idx, chunk_start in enumerate(range(0, total_pages, CHUNK_SIZE)):
            chunk_end  = min(chunk_start + CHUNK_SIZE - 1, total_pages - 1)
            page_range = list(range(chunk_start, chunk_end + 1))

            print(f"[OCR] Chunk {chunk_idx + 1}/{total_chunks} "
                  f"— pages {chunk_start + 1}–{chunk_end + 1}")

            last_error = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    chunk_response = client.ocr.process(
                        model="mistral-ocr-latest",
                        document={
                            "type": "document_url",
                            "document_url": document_url,
                        },
                        pages=page_range,
                        bbox_annotation_format=response_format_from_pydantic_model(ImageAnnotation),
                        document_annotation_format=response_format_from_pydantic_model(DocumentAnnotation),
                        include_image_base64=include_images,
                    )
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    print(f"[OCR]   Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                    if attempt < MAX_RETRIES:
                        wait = 5 * attempt
                        print(f"[OCR]   Retrying in {wait}s...")
                        time.sleep(wait)

            if last_error:
                # Non-fatal: log and skip this chunk; don't abort everything
                print(f"[OCR] ⚠ WARNING: Chunk {chunk_idx + 1} permanently failed "
                      f"(pages {chunk_start + 1}–{chunk_end + 1}) — skipping.")
                continue

            if chunk_response and hasattr(chunk_response, "pages"):
                chunk_pages = chunk_response.pages or []
                all_pages.extend(chunk_pages)
                for p_idx, p in enumerate(chunk_pages):
                    _log_page(chunk_start + p_idx, p)

        # ── 2. Validate ───────────────────────────────────────────────────────
        if not all_pages:
            raise RuntimeError(
                "OCR returned zero pages. The document may be unreadable or empty.")

        # Stitch all pages onto the last successful response object
        final_response       = chunk_response
        final_response.pages = all_pages

        # ── 3. Build clean text (per-page with headers) ───────────────────────
        page_texts       = []
        empty_page_count = 0
        for i, page in enumerate(all_pages):
            md = (getattr(page, "markdown", "") or "").strip()
            if not _has_real_text(md):
                empty_page_count += 1
            page_texts.append(
                f"--- Page {i + 1} ---\n{md}" if md
                else f"--- Page {i + 1} ---\n[No text extracted]"
            )

        clean_text = "\n\n".join(page_texts)

        # ── 4. Stats ──────────────────────────────────────────────────────────
        elapsed     = round(time.time() - start_time, 2)
        pages_count = len(all_pages)
        cost        = round(pages_count * 0.003, 4)   # $3 per 1000 pages

        stats = {
            "time_taken":  elapsed,
            "pages":       pages_count,
            "cost":        cost,
            "empty_pages": empty_page_count,
        }

        print(f"\n[OCR] Step 3/3 — Complete: {pages_count} pages | "
              f"{elapsed}s | {empty_page_count} empty page(s)\n")

        return final_response, stats, clean_text

    except Exception as e:
        print(f"[OCR][ERROR] {e}")
        traceback.print_exc()
        return None, None, str(e)
