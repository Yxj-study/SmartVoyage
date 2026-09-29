from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


PreferenceOperation = Literal["upsert", "delete", "ignore"]
PreferenceScope = Literal["stable", "temporary"]
PreferenceStatus = Literal["active", "deleted"]


class PreferenceCandidate(BaseModel):
    preference_key: str
    value: Any = None
    operation: PreferenceOperation = "upsert"
    scope: PreferenceScope = "stable"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_text: str = ""


class PreferenceRecord(BaseModel):
    user_id: str = Field(min_length=1)
    preference_key: str
    value: Any
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_session_id: str = ""
    source_text: str = ""
    status: PreferenceStatus = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None
