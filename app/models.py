from pydantic import BaseModel, ConfigDict, Field
from typing import Any, List, Optional
from enum import Enum
from uuid import UUID
from datetime import datetime

class CorrectionClass(str, Enum):
    FACT = "FACT"
    DISCARDABLE = "DISCARDABLE"

class CorrectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"

class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    id: str

class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    id: str

class Permissions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readers: Optional[List[str]] = None
    scopes: Optional[List[str]] = None
    deny_list: Optional[List[str]] = None

class CreateCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    subject: Subject
    field_key: str
    value: Any
    class_: CorrectionClass = Field(..., alias="class")
    permissions: Permissions
    actor: Actor
    idempotency_key: str
    supersedes: Optional[UUID] = None

class CreateCorrectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correction_id: UUID
    status: CorrectionStatus
    supersedes: Optional[UUID]
    created_at: datetime

class FactItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_key: str
    value: Any
    corrected_at: datetime
    correction_id: UUID
    actor: Actor

class FactsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: Subject
    facts: List[FactItem]

class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    correction_id: UUID
    field_key: str
    value: Any
    class_: CorrectionClass = Field(..., alias="class")
    status: CorrectionStatus
    supersedes: Optional[UUID] = None
    superseded_by: Optional[UUID] = None
    created_at: datetime
    actor: Actor

class HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: Subject
    history: List[HistoryItem]
