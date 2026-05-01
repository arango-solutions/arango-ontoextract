from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard pagination envelope per PRD Section 7.8."""

    data: list[T]
    cursor: str | None = None
    has_more: bool = False
    total_count: int = 0


class ErrorDetail(BaseModel):
    """Inner error object per PRD Section 7.8."""

    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str = Field(default="")


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorDetail
