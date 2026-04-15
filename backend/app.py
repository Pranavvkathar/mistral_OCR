import os
import json
import time
import shutil
import traceback

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pdf_highlight import highlight_text_in_pdf
from ocr_annotations_service import process_ocr_with_annotations
from database import save_report, get_all_reports, get_report_by_id

# ─── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="Mistral OCR API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prevent 304 Not Modified — strip caching headers so static PDFs always reload
@app.middleware("http")
async def disable_caching(request, call_next):
    request.scope["headers"] = [
        (k, v) for k, v in request.scope["headers"]
        if k.lower() not in (b"if-none-match", b"if-modified-since")
    ]
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ─── Folders & Static Files ───────────────────────────────────────────────────

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Served at  /outputs/<filename>
# Frontend requests via  /api/outputs/<filename>  → Vite proxy strips /api
app.mount("/outputs", StaticFiles(directory=OUTPUT_FOLDER), name="outputs")


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.post("/process")
async def process_document(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    print(f"\n[PROCESS] ── Received: '{file.filename}' ──────────────────────────")

    # Save upload to disk
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # ── Step 1: OCR ───────────────────────────────────────────────────────
        print("[PROCESS] Step 1/3 — Running Mistral OCR...")
        annotations_response, stats, clean_text = process_ocr_with_annotations(
            file_path, include_images=True
        )

        if annotations_response is None:
            return {
                "success": False,
                "error": f"OCR failed: {clean_text}",   # clean_text holds the error msg
            }

        print(f"[PROCESS] OCR complete: {stats['pages']} pages, "
              f"{stats.get('empty_pages', 0)} empty, {stats['time_taken']}s")

        # ── Step 2: Build highlighted PDF ─────────────────────────────────────
        print("[PROCESS] Step 2/3 — Generating highlighted PDF...")
        timestamp = int(time.time())
        highlighted_filename = f"{os.path.splitext(file.filename)[0]}.{timestamp}.highlighted.pdf"
        highlighted_pdf_path = os.path.join(OUTPUT_FOLDER, highlighted_filename)

        highlight_text_in_pdf(file_path, highlighted_pdf_path, clean_text, annotations_response)
        print(f"[PROCESS] PDF saved: {highlighted_pdf_path}")

        # ── Step 3: Save to MongoDB ───────────────────────────────────────────
        print("[PROCESS] Step 3/3 — Saving report to MongoDB...")
        response_dict = json.loads(annotations_response.model_dump_json())

        # Promote document_annotation from the first page that actually has one.
        # (Chunk-based OCR attaches it per-chunk, so page[0] may be empty.)
        if response_dict.get("pages"):
            doc_annotation = None
            for page in response_dict["pages"]:
                da = page.get("document_annotation")
                if da and da.get("language"):
                    doc_annotation = da
                    break
            # Fallback: use whatever is in the first page, even if incomplete
            if doc_annotation is None:
                doc_annotation = response_dict["pages"][0].get("document_annotation")
            if doc_annotation:
                response_dict["document_annotation"] = doc_annotation

        # URL stored WITHOUT /api prefix — the static mount serves at /outputs/
        # The Vite proxy rewrites /api/* → /* so the frontend uses /api/outputs/
        pdf_url = f"/outputs/{highlighted_filename}"

        report_id = await save_report(
            filename=file.filename,
            pdf_url=pdf_url,
            stats=stats,
            annotations=response_dict,
            markdown=clean_text,
        )

        print(f"[PROCESS] ✓ Done — report_id={report_id}")

        return {
            "success": True,
            "id": report_id,
            "pdf_url": pdf_url,
            "annotations": response_dict,
            "markdown": clean_text,
            "stats": stats,
        }

    except Exception as e:
        print(f"[PROCESS][ERROR] {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}

    finally:
        # Always clean up the temporary upload to keep disk tidy
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[PROCESS] Temp file removed: {file_path}")
        except Exception as cleanup_err:
            print(f"[PROCESS] Warning: could not remove temp file: {cleanup_err}")


@app.get("/reports")
async def fetch_reports():
    try:
        reports = await get_all_reports()
        return {"success": True, "reports": reports}
    except Exception as e:
        print(f"[REPORTS][ERROR] {e}")
        return {"success": False, "error": str(e)}


@app.get("/reports/{report_id}")
async def fetch_report_by_id(report_id: str):
    try:
        report = await get_report_by_id(report_id)
        if not report:
            return {"success": False, "error": "Report not found"}
        return {"success": True, "report": report}
    except Exception as e:
        print(f"[REPORT DETAIL][ERROR] {e}")
        return {"success": False, "error": str(e)}
