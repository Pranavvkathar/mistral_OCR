"""
annotations.py
==============
Pydantic models that define the STRUCTURED OUTPUT FORMAT for the Mistral OCR API.

How Annotations Work (from official Mistral docs):
─────────────────────────────────────────────────
The Mistral Document AI API adds an "annotations" layer on top of basic OCR.
You define a JSON schema (via Pydantic) and Mistral fills it in for you.

There are two annotation types:

  1. bbox_annotation_format  (→ ImageAnnotation)
     ──────────────────────────────────────────
     After regular OCR finishes, Mistral calls a Vision-capable LLM for every
     bounding box (chart, figure, image, table) that was detected on the page.
     Each bounding box gets annotated using the schema you provide.

     Workflow:
       OCR runs → bboxes detected → Vision LLM annotates each bbox → JSON returned

  2. document_annotation_format  (→ DocumentAnnotation)
     ─────────────────────────────────────────────────
     Mistral runs OCR, then sends the full Markdown output + the first 8 image
     bboxes to a Vision LLM together with your schema, to produce document-level
     metadata in one pass.

     Workflow:
       OCR runs → full markdown + top-8 images → Vision LLM → JSON returned

Common Use Cases (from official docs):
  - Classify images as charts, tables, photographs, text blocks
  - Convert charts to tables or extract fine print from figures
  - Extract receipt data (merchant name, amounts) for expense management
  - Extract vendor details from invoices for automated accounting
  - Capture key clauses from contracts

These models are passed to the API via:
    from mistralai.extra import response_format_from_pydantic_model
    client.ocr.process(
        bbox_annotation_format=response_format_from_pydantic_model(ImageAnnotation),
        document_annotation_format=response_format_from_pydantic_model(DocumentAnnotation),
    )
"""

from pydantic import BaseModel, Field
from enum import Enum


# ─── BBox Annotation Schema ───────────────────────────────────────────────────
#
# Used with:  bbox_annotation_format=response_format_from_pydantic_model(ImageAnnotation)
#
# Mistral will call a Vision LLM for EVERY bounding box found on each page,
# and fill in each field below for that specific image/figure region.
#
# Official Mistral docs example:
#   class Image(BaseModel):
#     image_type:        str = Field(..., description="The type of the image.")
#     short_description: str = Field(..., description="A description in english describing the image.")
#     summary:           str = Field(..., description="Summarize the image.")


class ImageType(str, Enum):
    """
    Classifies what kind of visual element a bounding box contains.
    Mistral assigns one of these labels to every detected image region.

    Values:
        GRAPH  → Charts, bar graphs, line plots, scatter plots
        TEXT   → Dense text blocks rendered as an image (e.g. scanned paragraphs)
        TABLE  → Tabular data that appears as an image (not a markdown table)
        IMAGE  → Photographs, diagrams, logos, illustrations
    """
    GRAPH = "graph"
    TEXT  = "text"
    TABLE = "table"
    IMAGE = "image"


class ImageAnnotation(BaseModel):
    """
    Structured annotation for a single image/figure bounding box on a page.

    Per the official Mistral docs, after OCR detects image regions, a
    Vision-capable LLM is called for each bbox individually with this schema.

    Fields:
        image_type        : what category the bounding box falls into
        short_description : a one-line description of what the image shows
        summary           : a detailed summary of the image content
                            (e.g. for a chart: axes, trends, key observations)

    Example output (from official docs):
        {
          "image_type": "scatter plot",
          "short_description": "Comparison of different models based on performance and cost.",
          "summary": "The image consists of two scatter plots comparing various models..."
        }
    """
    image_type: ImageType = Field(
        ...,
        description=(
            "The type/category of the image. "
            "Must be one of: 'graph' (charts/plots), 'text' (text-as-image), "
            "'table' (tabular image), or 'image' (photo/diagram/illustration)."
        )
    )
    short_description: str = Field(
        ...,
        description=(
            "A short, one-line description in English of what the image shows. "
            "Example: 'Bar chart comparing quarterly revenue by region.'"
        )
    )
    summary: str = Field(
        ...,
        description=(
            "A detailed summary of the image content. "
            "For charts/graphs, include axes labels, trends, and key data points. "
            "For tables, describe the columns and notable values. "
            "For photos/diagrams, describe the subject and context clearly."
        )
    )


# ─── Document Annotation Schema ───────────────────────────────────────────────
#
# Used with:  document_annotation_format=response_format_from_pydantic_model(DocumentAnnotation)
#
# Mistral sends the full OCR markdown output + the first 8 detected image bboxes
# to a Vision LLM, which fills in this schema once per document (or per chunk).
#
# Because OCR is processed in chunks of pages, Mistral attaches a
# DocumentAnnotation to each chunk's response. We later hoist the best one
# (the first with a valid `language` field) to the root of our result dict.


class DocumentAnnotation(BaseModel):
    """
    Structured annotation for an entire document (or chunk of pages).

    Generated once per API call by sending the full Markdown output plus
    the first 8 image bboxes to a Vision-capable LLM.

    Fields:
        language            : detected primary language (e.g. "English", "French")
        summary             : concise summary of the document's content and purpose
        stamps_extract      : verbatim text from official stamps or seals
        handwriting_extract : verbatim text from handwriting or signatures
        authors             : list of author names found anywhere in the document

    Example output:
        {
          "language": "English",
          "summary": "A 2020 annual report for Standard Chartered Bank...",
          "stamps_extract": "CERTIFIED TRUE COPY — Finance Department",
          "handwriting_extract": "Signed: J. Smith  Date: 12/03/2020",
          "authors": ["John Smith", "Maria Chen"]
        }
    """
    language: str = Field(
        ...,
        description=(
            "The primary language the document is written in. "
            "Return the full language name in English (e.g. 'English', 'French', 'Arabic')."
        )
    )
    summary: str = Field(
        ...,
        description=(
            "A concise 2–4 sentence summary of the document's content, type, and purpose. "
            "Example: 'This is a formal invoice from Acme Corp dated March 2024 "
            "for consulting services totalling $12,500.'"
        )
    )
    stamps_extract: str = Field(
        ...,
        description=(
            "Verbatim text extracted from any official stamps, seals, or watermarks "
            "found on the document. If none are present, return an empty string."
        )
    )
    handwriting_extract: str = Field(
        ...,
        description=(
            "Verbatim text extracted from any handwriting or signatures on the document. "
            "If none are present, return an empty string."
        )
    )
    authors: list[str] = Field(
        ...,
        description=(
            "A list of author names found anywhere in the document "
            "(title page, headers, footers, signature blocks, etc.). "
            "Return an empty list if no authors are identified."
        )
    )
