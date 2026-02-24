"""
Pydantic models for PROJ-9: Undo / Rollback-System.
"""
from typing import Literal

from pydantic import BaseModel


OperationType = Literal["MOVE", "RENAME"]
OperationStatus = Literal["completed", "reverted", "revert_failed"]


# --------------------------------------------------------------------------- #
# DB row → response                                                            #
# --------------------------------------------------------------------------- #

class OperationLog(BaseModel):
    id: int
    batch_id: str
    operation_type: OperationType
    source_path: str
    target_path: str
    timestamp: str          # ISO-8601
    status: OperationStatus
    mode: str | None        # 'fast' | 'smart' | None


class BatchSummary(BaseModel):
    """Grouped view of all operations sharing a batch_id."""
    batch_id: str
    operation_type: OperationType
    file_count: int
    timestamp: str          # timestamp of the first operation in the batch
    status: str             # 'completed' | 'partially_reverted' | 'reverted'


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class UndoSingleRequest(BaseModel):
    operation_id: int


class UndoBatchRequest(BaseModel):
    batch_id: str


# --------------------------------------------------------------------------- #
# Responses                                                                    #
# --------------------------------------------------------------------------- #

class UndoResult(BaseModel):
    success: bool
    message: str
    reverted_count: int = 0
    failed_count: int = 0
    errors: list[str] = []
