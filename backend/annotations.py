from pydantic import BaseModel, Field
from enum import Enum

class ImageType(str, Enum):
    GRAPH = "graph"
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"

class ImageAnnotation(BaseModel):
    image_type: ImageType = Field(..., description="The type of the image. Must be one of 'graph', 'text', 'table' or 'image'.")
    description: str = Field(..., description="A description of the image.")

class DocumentAnnotation(BaseModel):
    language: str = Field(..., description="The language of the document.")
    summary: str = Field(..., description="A summary of the document.")
    stamps_extract: str = Field(..., description="Verbatim text extracted from any stamps or seals found on the page.")
    handwriting_extract: str = Field(..., description="Verbatim text extracted from any handwriting or signatures.")
    authors: list[str] = Field(..., description="A list of authors.")
