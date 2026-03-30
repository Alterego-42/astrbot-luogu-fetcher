from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class LuoguIntentName(str, Enum):
    REQUEST_SEARCH = "REQUEST_SEARCH"
    REQUEST_SELECT = "REQUEST_SELECT"
    REQUEST_STATEMENT = "REQUEST_STATEMENT"
    REQUEST_IMAGE = "REQUEST_IMAGE"
    REQUEST_RANDOM = "REQUEST_RANDOM"
    REQUEST_COUNT = "REQUEST_COUNT"
    UNKNOWN = "UNKNOWN"


class LuoguIntentTarget(str, Enum):
    CURRENT_SELECTED = "CURRENT_SELECTED"
    CURRENT_CANDIDATES = "CURRENT_CANDIDATES"
    DIRECT_PID = "DIRECT_PID"
    NONE = "NONE"


@dataclass(slots=True)
class LuoguIntent:
    intent: LuoguIntentName
    target: LuoguIntentTarget = LuoguIntentTarget.NONE
    constraints: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    raw_message: str = ""
