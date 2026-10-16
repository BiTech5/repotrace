from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class BugReport(BaseModel):
    """Schema for a captured Python failure and its diagnostic context."""
    id: str = Field(..., description="Unique identifier for the bug report")
    title: str = Field(..., description="Title of the bug report")
    description: Optional[str] = Field(None, description="Detailed description of the bug")
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="Timestamp when the bug report was created")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when the bug report was last updated")
    status: str = Field(..., description="Current status of the bug report (e.g., open, closed, in progress)")
    severity: Optional[str] = Field(None, description="Severity level of the bug (e.g., low, medium, high)")
    reporter: Optional[str] = Field(None, description="Name or identifier of the person who reported the bug")
    assignee: Optional[str] = Field(None, description="Name or identifier of the person assigned to fix the bug")
    tags: List[str] = Field(default_factory=list, description="List of tags associated with the bug report")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata related to the bug report")

    class Config:
        frozen = True