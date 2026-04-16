"""
database.py
===========
MongoDB database layer for the Mistral OCR application.

This module is responsible for:
  - Connecting to MongoDB using the Motor async driver
  - Saving new OCR reports after a document is processed
  - Retrieving all reports (lightweight) for the sidebar list
  - Retrieving a single full report by its MongoDB ObjectId

Collections:
  ocr_reports  — stores one document per processed PDF, containing:
                   filename, pdf_url, stats, annotations, markdown, created_at

Environment Variables (loaded from .env):
  MONGODB_URI      — full connection string (e.g. mongodb+srv://...)
  MONGODB_DB_NAME  — database name (defaults to "OCR")

Why Motor (AsyncIOMotorClient)?
  FastAPI is an async framework. Motor is the async version of PyMongo,
  allowing database calls to be awaited without blocking the event loop.
"""

import os
import datetime

from motor.motor_asyncio import AsyncIOMotorClient   # async MongoDB driver
from bson import ObjectId                            # MongoDB's unique document ID type
from dotenv import load_dotenv

load_dotenv()   # loads MONGODB_URI and MONGODB_DB_NAME from .env

# ─── Database Connection ──────────────────────────────────────────────────────

MONGODB_URI     = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "OCR")   # fallback to "OCR" if not set

# Create one shared async client for the entire application lifetime.
# Motor manages its own internal connection pool, so this is safe and efficient.
mongo_client       = AsyncIOMotorClient(MONGODB_URI)
database           = mongo_client[MONGODB_DB_NAME]
reports_collection = database["ocr_reports"]   # the collection we read/write


# ─── Database Operations ──────────────────────────────────────────────────────

async def save_report(
    filename:    str,
    pdf_url:     str,
    stats:       dict,
    annotations: dict,
    markdown:    str,
) -> str:
    """
    Saves a completed OCR report to the `ocr_reports` collection.

    Arguments:
        filename    : original PDF filename (e.g. "invoice_2024.pdf")
        pdf_url     : server-relative path to the highlighted PDF
                      (e.g. "/outputs/invoice_2024.1713000000.highlighted.pdf")
        stats       : processing stats { time_taken, pages, cost, empty_pages }
        annotations : full Mistral OCR response serialised as a dict
                      (includes .pages[], each with .markdown, .images, .tables,
                       .document_annotation — language, summary, authors, etc.)
        markdown    : full extracted plain text (all pages concatenated)

    Returns:
        The MongoDB ObjectId of the newly inserted document, as a string.
    """
    report_document = {
        "filename":    filename,
        "pdf_url":     pdf_url,
        "stats":       stats,
        "annotations": annotations,   # full structured OCR result
        "markdown":    markdown,      # plain text for full-text reading
        "created_at":  datetime.datetime.utcnow(),
    }

    insert_result = await reports_collection.insert_one(report_document)

    # inserted_id is a BSON ObjectId — convert to string for JSON serialisation
    return str(insert_result.inserted_id)


async def get_all_reports() -> list:
    """
    Retrieves a lightweight list of all OCR reports, sorted newest-first.

    Why we exclude `markdown` and `annotations`:
        Those two fields can be very large (megabytes for multi-page documents).
        The sidebar only needs filename, date, and page count — so we project
        only the fields that are needed for the list view.

    Returns:
        A list of report dicts, each containing:
            { _id, filename, pdf_url, stats, created_at }
    """
    # MongoDB projection: 0 = exclude, 1 = include (not mixed, except _id)
    projection = {
        "markdown":    0,   # exclude full text (can be very large)
        "annotations": 0,   # exclude full OCR data (can be very large)
    }

    # sort("created_at", -1) → newest reports appear at the top of the sidebar
    cursor = reports_collection.find({}, projection).sort("created_at", -1)

    reports = []
    async for report_document in cursor:
        # ObjectId is not JSON-serialisable — convert to plain string
        report_document["_id"] = str(report_document["_id"])
        reports.append(report_document)

    return reports


async def get_report_by_id(report_id: str) -> dict | None:
    """
    Retrieves the full OCR report for a given MongoDB document ID.

    This is called when the user clicks a report in the sidebar.
    Unlike `get_all_reports`, this returns EVERYTHING — including the
    full annotations and extracted markdown text.

    Arguments:
        report_id : the MongoDB ObjectId string (24 hex characters)

    Returns:
        The complete report dict, or None if it does not exist or the ID is invalid.
    """
    try:
        # ObjectId() will raise if report_id is not a valid 24-char hex string
        object_id       = ObjectId(report_id)
        report_document = await reports_collection.find_one({"_id": object_id})

        if report_document:
            report_document["_id"] = str(report_document["_id"])

        return report_document

    except Exception:
        # Invalid ID format or unexpected DB error — return None so the
        # route handler can respond with a clean 404-style error message
        return None
