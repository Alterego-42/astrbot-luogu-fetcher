from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class LuoguWorkflowState(str, Enum):
    IDLE = "IDLE"
    HAVE_CANDIDATES = "HAVE_CANDIDATES"
    HAVE_SELECTED = "HAVE_SELECTED"
    AWAITING_RENDER = "AWAITING_RENDER"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"


def derive_luogu_workflow_state(session_state: Mapping[str, Any] | None) -> LuoguWorkflowState:
    data = session_state or {}
    if data.get("current_pid"):
        return LuoguWorkflowState.HAVE_SELECTED
    if int(data.get("total") or 0) > 0:
        return LuoguWorkflowState.HAVE_CANDIDATES
    if data.get("last_error"):
        return LuoguWorkflowState.FAILED_RETRYABLE
    return LuoguWorkflowState.IDLE
