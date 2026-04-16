"""
app.py
======
FastAPI application — the main entry point for the Mistral OCR backend.

This file wires together all three service layers:
  1. ocr_annotations_service  — runs Mistral OCR on the uploaded PDF
  2. pdf_highlight             — generates a highlighted PDF report from OCR results
  3. database                  — persists the report to MongoDB

API Endpoints:
  POST /process              — upload a PDF, run OCR, get back results
  GET  /reports              — list all saved reports (lightweight, for the sidebar)
  GET  /reports/{report_id}  — fetch a single full report by its MongoDB ID

Static Files:
  /outputs/<filename>        — serves generated highlighted PDFs directly
  (the Vite dev proxy rewrites /api/* → /* so the frontend accesses them at /api/outputs/)

How to run:
  uvicorn app:app --reload
"""

import os
import json
import time
import base64
import shutil
import traceback

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Local service modules
from ocr_annotations_service import process_ocr_with_annotations
from database                import save_report, get_all_reports, get_report_by_id


# ─── FastAPI App Initialisation ───────────────────────────────────────────────

app = FastAPI(
    title="Mistral OCR API",
    description="Backend service for processing PDFs with Mistral OCR and storing results.",
    version="1.0.0",
)

# Allow requests from any origin (needed for the Vite dev server on a different port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── No-Cache Middleware ──────────────────────────────────────────────────────
#
# Browsers cache static files aggressively. When a new highlighted PDF is
# generated, the browser might serve the old cached version if we don't
# strip the If-None-Match / If-Modified-Since headers from incoming requests
# and set no-store on outgoing responses.

@app.middleware("http")
async def disable_browser_caching(request, call_next):
    """
    Prevents 304 Not Modified responses for static PDF files.
    Strips inbound cache-validation headers and adds no-cache headers to every response.
    """
    request.scope["headers"] = [
        (key, value)
        for key, value in request.scope["headers"]
        if key.lower() not in (b"if-none-match", b"if-modified-since")
    ]
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"]        = "no-cache"
    response.headers["Expires"]       = "0"
    return response


# ─── Folder Setup & Static File Serving ──────────────────────────────────────

# uploads/  — temporary storage for incoming PDFs (deleted after processing)
# outputs/  — permanent storage for the generated highlighted PDFs
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Mount the outputs folder so PDFs and images can be fetched directly by URL.
# Accessible at: GET /outputs/<filename>
# The Vite dev proxy rewrites /api/outputs/<file> → /outputs/<file>
app.mount("/outputs", StaticFiles(directory=OUTPUT_FOLDER), name="outputs")


# ─── Helper: Save OCR Extracted Images to Disk ───────────────────────────────

def save_ocr_images(filename: str, ocr_result_dict: dict) -> dict:
    """
    Saves each image extracted by Mistral OCR to disk as a JPEG file,
    then replaces the bulky `image_base64` field in the annotations dict
    with a lightweight server-side URL (`image_url`).

    This keeps MongoDB documents small and lets the frontend load images
    directly from /api/outputs/<filename> — much more reliable than
    embedding multi-MB base64 strings in JSON.

    Arguments:
        filename        : original PDF filename (used to name image files)
        ocr_result_dict : the full serialised OCR response dict

    Returns:
        The modified dict with image_base64 stripped and image_url added.
    """
    base_name = os.path.splitext(filename)[0]
    # Sanitise so spaces / special chars don't break file names
    safe_base = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in base_name)

    for page in ocr_result_dict.get("pages", []):
        page_idx = page.get("index", 0)
        for image in page.get("images", []):
            img_id  = image.get("id")          # e.g. "img-0.jpeg"
            img_b64 = image.pop("image_base64", None)   # remove from dict

            if not img_b64 or not img_id:
                image["image_url"] = None
                continue

            # Build a unique, filesystem-safe filename:
            #   <safe_pdf_name>_page<N>_img-0.jpeg
            img_filename = f"{safe_base}_page{page_idx}_{img_id}"
            img_disk_path = os.path.join(OUTPUT_FOLDER, img_filename)

            try:
                # Remove any whitespace that some base64 encoders insert
                clean_b64 = img_b64.strip().replace("\n", "").replace("\r", "")
                img_bytes = base64.b64decode(clean_b64)
                with open(img_disk_path, "wb") as f:
                    f.write(img_bytes)
                # Store URL (backend proxy path)
                image["image_url"] = f"/outputs/{img_filename}"
                print(f"  [IMG] Saved {img_filename} ({len(img_bytes):,} bytes)")
            except Exception as img_err:
                print(f"  [IMG] Warning — could not save {img_id}: {img_err}")
                image["image_url"] = None

    return ocr_result_dict


# ─── Route: Process a PDF ────────────────────────────────────────────────────

@app.post("/process")
async def process_document(
    file: UploadFile = File(...),
    # Advanced OCR Options (Form fields)
    table_format: str = Form(None),           # "html", "markdown", "null"
    confidence_level: str = Form(None),      # "page", "word", "null"
    extract_header: bool = Form(False),
    extract_footer: bool = Form(False)
):
    """
    Main endpoint — accepts a PDF upload, runs the full OCR pipeline, and returns results.
    
    The API now accepts advanced options matching the Mistral 'Playground' capabilities:
      - table_format: extract tables as HTML or Markdown strings
      - confidence_level: granularity of AI confidence scores
      - extract_header/footer: separate extraction of page headers/footers
    """
    # Save the uploaded file to disk (needed because the OCR service reads it from a path)
    temp_file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    print(f"\n[PROCESS] ── Received: '{file.filename}' ──────────────────────────")

    # Map "null" strings from frontend back to None for the SDK logic
    t_fmt = table_format if table_format != "null" else None
    c_lvl = confidence_level if confidence_level != "null" else None

    with open(temp_file_path, "wb") as temp_file:
        shutil.copyfileobj(file.file, temp_file)

    try:
        # ── Step 1: Run Mistral OCR ───────────────────────────────────────────
        print(f"[PROCESS] Step 1/3 — Running Mistral OCR (fmt={t_fmt}, conf={c_lvl})...")
        ocr_response, processing_stats, extracted_text = process_ocr_with_annotations(
            file_path=temp_file_path,
            include_images=True,
            table_format=t_fmt,
            confidence_granularity=c_lvl,
            extract_header=extract_header,
            extract_footer=extract_footer
        )

        if ocr_response is None:
            # extracted_text holds the error message when ocr_response is None
            return {"success": False, "error": f"OCR failed: {extracted_text}"}

        print(
            f"[PROCESS] OCR complete: {processing_stats['pages']} pages, "
            f"{processing_stats.get('empty_pages', 0)} empty, "
            f"{processing_stats['time_taken']}s"
        )

        # ── Step 2: Save extracted images to disk ────────────────────────────
        print("[PROCESS] Step 2/3 — Saving extracted images to disk...")
        ocr_result_dict = json.loads(ocr_response.model_dump_json())
        ocr_result_dict  = save_ocr_images(file.filename, ocr_result_dict)

        # The Mistral API returns `document_annotation` inside each page object,
        # because OCR is done in chunks and each chunk gets its own annotation.
        # We hoist it to the root of the response dict so the frontend can access
        # it easily at `annotations.document_annotation.language` etc.
        #
        # We scan all pages to find the first one with a valid language field,
        # because chunk[0] pages may not always carry the annotation.
        if ocr_result_dict.get("pages"):
            best_document_annotation = None
            for page in ocr_result_dict["pages"]:
                page_annotation = page.get("document_annotation")
                if page_annotation and page_annotation.get("language"):
                    best_document_annotation = page_annotation
                    break   # use the first page that has a language value

            # Fallback: use first page's annotation even if language is empty
            if best_document_annotation is None:
                best_document_annotation = ocr_result_dict["pages"][0].get("document_annotation")

            if best_document_annotation:
                ocr_result_dict["document_annotation"] = best_document_annotation

        pdf_url = None

        # ── Step 3: Persist to MongoDB ────────────────────────────────────────
        print("[PROCESS] Step 3/3 — Saving report to MongoDB...")
        report_id = await save_report(
            filename=file.filename,
            pdf_url=pdf_url,
            stats=processing_stats,
            annotations=ocr_result_dict,
            markdown=extracted_text,
        )

        print(f"[PROCESS] ✓ Done — report_id={report_id}")

        return {
            "success":     True,
            "id":          report_id,
            "pdf_url":     pdf_url,
            "annotations": ocr_result_dict,
            "markdown":    extracted_text,
            "stats":       processing_stats,
        }

    except Exception as unexpected_error:
        print(f"[PROCESS][ERROR] {unexpected_error}")
        traceback.print_exc()
        return {"success": False, "error": str(unexpected_error)}

    finally:
        # Always remove the temporary upload file to keep the uploads/ folder clean.
        # This runs whether or not an exception occurred.
        try:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                print(f"[PROCESS] Temp file cleaned up: {temp_file_path}")
        except Exception as cleanup_error:
            print(f"[PROCESS] Warning — could not clean up temp file: {cleanup_error}")


# ─── Route: List All Reports ──────────────────────────────────────────────────

@app.get("/reports")
async def fetch_all_reports():
    """
    Returns a lightweight list of all saved OCR reports for the sidebar.

    Heavy fields (markdown, annotations) are excluded by the database layer
    to keep this response small and fast — the sidebar only needs filename,
    date, page count, etc.

    Response:
        { "success": true, "reports": [ { _id, filename, pdf_url, stats, created_at }, ... ] }
    """
    try:
        all_reports = await get_all_reports()
        return {"success": True, "reports": all_reports}
    except Exception as error:
        print(f"[REPORTS][ERROR] {error}")
        return {"success": False, "error": str(error)}


# ─── Route: Get a Single Full Report ─────────────────────────────────────────

@app.get("/reports/{report_id}")
async def fetch_report_by_id(report_id: str):
    """
    Returns the complete OCR report for a given report ID (MongoDB ObjectId string).

    Called when the user clicks a report in the sidebar — loads the full
    annotations, PDF URL, and extracted text so the viewer panels can populate.

    Path Parameter:
        report_id : 24-character hex MongoDB ObjectId (e.g. "661f3a2b4e1a2b3c4d5e6f7a")

    Response (on success):
        { "success": true, "report": { _id, filename, pdf_url, stats, annotations, markdown, created_at } }
    """
    try:
        report = await get_report_by_id(report_id)
        if not report:
            return {"success": False, "error": f"Report '{report_id}' not found."}
        return {"success": True, "report": report}
    except Exception as error:
        print(f"[REPORT DETAIL][ERROR] {error}")
        return {"success": False, "error": str(error)}
