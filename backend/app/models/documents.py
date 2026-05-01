from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DocumentStatus(StrEnum):
    UPLOADING = "uploading"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class DocumentCreate(BaseModel):
    filename: str
    mime_type: str
    org_id: str | None = None
    metadata: dict[str, Any] | None = None


class DocumentResponse(BaseModel):
    key: str = Field(alias="_key")
    filename: str
    mime_type: str
    org_id: str | None
    status: DocumentStatus
    upload_date: datetime
    chunk_count: int = 0
    metadata: dict[str, Any] | None = None


class ChunkResponse(BaseModel):
    key: str = Field(alias="_key")
    doc_id: str
    text: str
    chunk_index: int
    token_count: int
