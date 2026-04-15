"""
ocr_annotations_service.py
===========================
Core service that processes a PDF using the Mistral OCR API.

Pipeline Overview:
  Step 1 — Encode the PDF as a base64 data URL (no file upload needed)
  Step 2 — Send the document to Mistral OCR in chunks of 5 pages at a time,
            with structured output schemas for per-image and per-document metadata
  Step 3 — Stitch all page results together, build clean extracted text, and
            return the final OCR response along with processing statistics

Why chunked processing?
  The Mistral OCR API works best with up to 5 pages per call.
  Large documents are split into chunks; each chunk is retried up to 3 times
  on failure before being skipped (non-fatal — other chunks still complete).

Key Mistral API concepts used:
  - client.ocr.process()             : sends the document for OCR
  - model="mistral-ocr-latest"       : the latest Mistral OCR model
  - document_url (base64 data URL)   : how we pass the PDF inline (no upload)
  - pages=[...]                      : process only specific page indices
  - bbox_annotation_format           : structured JSON schema for image bounding boxes
  - document_annotation_format       : structured JSON schema for doc-level metadata
  - include_image_base64             : whether to return image data in the response
"""

import os
import re
import time
import base64
import traceback
import httpx
import fitz                          # PyMuPDF — used to count pages locally
from dotenv import load_dotenv

# Mistral Python SDK (v1.x)
from mistralai.client import Mistral
from mistralai.extra import response_format_from_pydantic_model   # converts a Pydantic model into a structured-output schema

# Our Pydantic models that define what Mistral should return for each image
# and for the document as a whole (language, summary, authors, etc.)
from annotations import ImageAnnotation, DocumentAnnotation

load_dotenv()   # loads MISTRAL_API_KEY from .env

# ─── Mistral Client Setup ─────────────────────────────────────────────────────

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# Use a generous 600-second timeout so large documents don't time out mid-call.
# connect=60s   → time allowed to establish the TCP connection
# read=600s     → time allowed waiting for the API response body
# write=60s     → time allowed to send the request body (large base64 payload)
_http_timeout = httpx.Timeout(600.0, connect=60.0, read=600.0, write=60.0)
_http_client  = httpx.Client(timeout=_http_timeout)

# The Mistral client is shared across all requests (one instance per process)
mistral_client = Mistral(api_key=MISTRAL_API_KEY, client=_http_client)


# ─── Helper Functions ─────────────────────────────────────────────────────────

def _encode_pdf_as_base64_url(file_path: str) -> str:
    """
    Reads a PDF from disk and encodes it as a base64 data URL.

    The Mistral OCR API accepts documents as either:
      (a) A remote URL pointing to the file
      (b) A base64-encoded data URL in the format:
              data:application/pdf;base64,<BASE64_STRING>

    We use option (b) to avoid the extra upload step and signed-URL round-trip.
    The entire PDF is read into memory, encoded, and returned as a string.

    Example output:
        "data:application/pdf;base64,JVBERi0xLjQKJ..."
    """
    with open(file_path, "rb") as pdf_file:
        encoded_bytes = base64.b64encode(pdf_file.read())
        base64_string = encoded_bytes.decode("utf-8")
    return f"data:application/pdf;base64,{base64_string}"


def _page_has_real_text(markdown: str) -> bool:
    """
    Returns True if the page's markdown contains actual text content.

    Mistral OCR returns image placeholders like:
        ![img-0.jpeg](img-0.jpeg)
    for scanned/image-only pages. We strip these out and check if there's
    any remaining text longer than 10 characters.
    """
    text_only = re.sub(r'!\[.*?\]\(.*?\)', '', markdown or '').strip()
    return len(text_only) > 10


def _log_page_result(global_page_index: int, page) -> None:
    """
    Prints a one-line diagnostic summary for a processed page to the console.

    Format:
        Page   1:  4823 chars | 2 img(s) | 0 table(s) | ✓ text
        Page   2:     0 chars | 1 img(s) | 0 table(s) | ⚠ img-only (scanned?)
        Page   3:     0 chars | 0 img(s) | 0 table(s) | ✗ empty
    """
    markdown    = getattr(page, "markdown", "") or ""
    image_count = len(getattr(page, "images",  []) or [])
    table_count = len(getattr(page, "tables",  []) or [])
    has_text    = _page_has_real_text(markdown)

    if has_text:
        status = "✓ text"
    elif image_count > 0:
        status = "⚠ img-only (scanned?)"
    else:
        status = "✗ empty"

    print(
        f"  Page {global_page_index + 1:3d}: {len(markdown):5d} chars | "
        f"{image_count} img(s) | {table_count} table(s) | {status}"
    )


# ─── Main OCR Processing Function ────────────────────────────────────────────

def process_ocr_with_annotations(
    file_path: str, 
    include_images: bool = False,
    table_format: str = None,         # "html", "markdown", or None
    confidence_granularity: str = None, # "page", "word", or None
    extract_header: bool = False,
    extract_footer: bool = False,
):
    """
    Processes a PDF file through the Mistral OCR API and returns structured results.

    Arguments:
        file_path              : Absolute path to the PDF file on disk
        include_images         : If True, returns image base64 data in the response
        table_format           : Format for table extraction ("html", "markdown", or None)
        confidence_granularity : Granularity for confidence scores ("page" or "word")
        extract_header         : If True, specifically extracts header content
        extract_footer         : If True, specifically extracts footer content

    Returns a tuple: (ocr_response, stats_dict, clean_text)
    """
    processing_start_time = time.time()

    try:
        # ── Step 1: Count pages and encode the file ───────────────────────────
        #
        # We use PyMuPDF (fitz) to count pages locally so we know how many
        # chunks to send without making an API call just for metadata.
        pdf_document = fitz.open(file_path)
        total_pages  = len(pdf_document)
        pdf_document.close()

        print(f"\n[OCR] ── Start: '{os.path.basename(file_path)}' "
              f"({total_pages} pages) ──────────────────────")

        # Encode the PDF as a base64 data URL so it can be sent inline
        # to the Mistral API without a separate file-upload step.
        print("[OCR] Step 1/3 — Encoding PDF as base64 data URL...")
        base64_document_url = _encode_pdf_as_base64_url(file_path)
        print(f"[OCR] Encoding complete ({len(base64_document_url) // 1024} KB data URL)")

        # ── Step 2: Chunk-based OCR via Mistral API ───────────────────────────
        #
        # We process the document in chunks of CHUNK_SIZE pages per API call.
        # This keeps individual requests small and allows fine-grained retries.
        #
        # For each chunk we call client.ocr.process() with:
        #   - model                      : "mistral-ocr-latest"
        #   - document.type              : "document_url"
        #   - document.document_url      : our base64 data URL
        #   - pages                      : list of 0-based page indices for this chunk
        #   - bbox_annotation_format     : tells Mistral to return structured JSON
        #                                  for each image bounding box (ImageAnnotation)
        #   - document_annotation_format : tells Mistral to return structured JSON
        #                                  for the whole document (DocumentAnnotation)
        #   - include_image_base64       : whether to embed image data in the response

        CHUNK_SIZE    = 5        # pages per API call (sweet spot for Mistral OCR)
        MAX_RETRIES   = 3        # retry count per chunk before skipping
        all_pages     = []       # collected page results from all chunks
        last_response = None     # last successful chunk response (used for stitching)
        total_chunks  = (total_pages + CHUNK_SIZE - 1) // CHUNK_SIZE

        print(f"[OCR] Step 2/3 — Running OCR on {total_pages} pages "
              f"in {total_chunks} chunk(s) of {CHUNK_SIZE} pages each")

        for chunk_index, chunk_start_page in enumerate(range(0, total_pages, CHUNK_SIZE)):
            chunk_end_page = min(chunk_start_page + CHUNK_SIZE - 1, total_pages - 1)

            # page_indices is the list of 0-based page numbers for this chunk
            # e.g. for pages 6–10 → [5, 6, 7, 8, 9]
            page_indices = list(range(chunk_start_page, chunk_end_page + 1))

            print(f"[OCR] Chunk {chunk_index + 1}/{total_chunks} "
                  f"— pages {chunk_start_page + 1}–{chunk_end_page + 1}")

            chunk_failed   = False
            chunk_response = None

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    # ── Mistral OCR API Call ──────────────────────────────────
                    chunk_response = mistral_client.ocr.process(
                        model="mistral-ocr-latest",

                        # The document is sent as a base64-encoded data URL.
                        # Mistral also supports remote URLs or file IDs (after upload),
                        # but base64 avoids the upload + signed-URL steps entirely.
                        document={
                            "type":         "document_url",
                            "document_url": base64_document_url,
                        },

                        # Only process the pages in this specific chunk
                        pages=page_indices,

                        # Tell Mistral to return structured JSON for each image region
                        # using our ImageAnnotation Pydantic schema
                        bbox_annotation_format=response_format_from_pydantic_model(
                            ImageAnnotation
                        ),

                        # Tell Mistral to return structured JSON for document-level
                        # metadata (language, summary, authors…) using DocumentAnnotation
                        document_annotation_format=response_format_from_pydantic_model(
                            DocumentAnnotation
                        ),

                        # If True, every detected image is returned as base64 data
                        # inside the response — useful for image extraction pipelines
                        include_image_base64=include_images,

                        # --- Advanced Parameters (OCR 2512+ Capabilities) ---
                        table_format=table_format,
                        confidence_scores_granularity=confidence_granularity,
                        extract_header=extract_header,
                        extract_footer=extract_footer,
                    )
                    # Success — exit the retry loop
                    break

                except Exception as api_error:
                    print(f"[OCR]   Attempt {attempt}/{MAX_RETRIES} failed: {api_error}")
                    if attempt < MAX_RETRIES:
                        wait_seconds = 5 * attempt   # back-off: 5s, 10s
                        print(f"[OCR]   Retrying in {wait_seconds}s...")
                        time.sleep(wait_seconds)
                    else:
                        chunk_failed = True

            if chunk_failed:
                # Skip this chunk — non-fatal so we can still return partial results
                print(f"[OCR] ⚠ WARNING: Chunk {chunk_index + 1} permanently failed "
                      f"(pages {chunk_start_page + 1}–{chunk_end_page + 1}) — skipping.")
                continue

            # Collect pages from this chunk's response
            if chunk_response and hasattr(chunk_response, "pages"):
                chunk_pages = chunk_response.pages or []
                all_pages.extend(chunk_pages)
                last_response = chunk_response

                # Print a diagnostic line for each page we just processed
                for page_offset, page in enumerate(chunk_pages):
                    _log_page_result(chunk_start_page + page_offset, page)

        # ── Step 3: Validate, stitch and build clean text ─────────────────────

        if not all_pages:
            raise RuntimeError(
                "OCR returned zero usable pages. "
                "The document may be password-protected, corrupt, or empty."
            )

        # Attach the full page list to the last successful response object.
        # This gives us a single response object with all pages, which callers
        # can serialise with .model_dump_json() to get the complete result.
        final_ocr_response       = last_response
        final_ocr_response.pages = all_pages

        # Build a human-readable plain-text version of the extracted content,
        # one section per page, with a header showing the page number.
        page_text_sections = []
        empty_page_count   = 0

        for page_number, page in enumerate(all_pages, start=1):
            page_markdown = (getattr(page, "markdown", "") or "").strip()

            if not _page_has_real_text(page_markdown):
                empty_page_count += 1

            if page_markdown:
                page_text_sections.append(f"--- Page {page_number} ---\n{page_markdown}")
            else:
                page_text_sections.append(f"--- Page {page_number} ---\n[No text extracted]")

        # Join all page sections into one continuous text block
        full_extracted_text = "\n\n".join(page_text_sections)

        # ── Processing Statistics ─────────────────────────────────────────────
        elapsed_seconds = round(time.time() - processing_start_time, 2)
        total_page_count = len(all_pages)

        # Mistral OCR pricing: $3 per 1,000 pages = $0.003 per page
        estimated_cost_usd = round(total_page_count * 0.003, 4)

        processing_stats = {
            "time_taken":  elapsed_seconds,       # seconds from start to finish
            "pages":       total_page_count,       # total pages successfully processed
            "cost":        estimated_cost_usd,     # estimated API cost in USD
            "empty_pages": empty_page_count,       # pages with no extractable text
        }

        print(f"\n[OCR] Step 3/3 — Complete: {total_page_count} pages | "
              f"{elapsed_seconds}s | {empty_page_count} empty page(s)\n")

        return final_ocr_response, processing_stats, full_extracted_text

    except Exception as fatal_error:
        print(f"[OCR][ERROR] {fatal_error}")
        traceback.print_exc()
        # Return None so callers can check `if ocr_response is None` to detect failure
        return None, None, str(fatal_error)
