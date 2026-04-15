import os
import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "OCR")

client = AsyncIOMotorClient(MONGODB_URI)
db = client[MONGODB_DB_NAME]
reports_collection = db["ocr_reports"]

async def save_report(filename: str, pdf_url: str, stats: dict, annotations: dict, markdown: str):
    """
    Saves a new OCR report to the MongoDB database.
    """
    document = {
        "filename": filename,
        "pdf_url": pdf_url,
        "stats": stats,
        "annotations": annotations,
        "markdown": markdown,
        "created_at": datetime.datetime.utcnow()
    }
    result = await reports_collection.insert_one(document)
    return str(result.inserted_id)

async def get_all_reports():
    """
    Retrieves a list of all historical reports with basic metadata for the sidebar.
    """
    # Exclude heavy payloads like markdown and deep annotations to keep fetch fast
    cursor = reports_collection.find({}, {"markdown": 0, "annotations": 0}).sort("created_at", -1)
    
    reports = []
    async for document in cursor:
        document["_id"] = str(document["_id"])
        reports.append(document)
        
    return reports

async def get_report_by_id(report_id: str):
    """
    Retrieves a full report by ID.
    """
    try:
        document = await reports_collection.find_one({"_id": ObjectId(report_id)})
        if document:
            document["_id"] = str(document["_id"])
        return document
    except Exception as e:
        return None
