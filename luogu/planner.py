from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from .command_bus import LuoguCommand
from .intent_schema import LuoguIntent, LuoguIntentName, LuoguIntentTarget
from .workflow import LuoguWorkflowState, derive_luogu_workflow_state


SHORT_IMAGE_FOLLOW_UP_MARKERS = (
    "看图",
    "题图",
    "图片",
    "图片发出来",
    "题目图片",
    "发题图",
    "图也来",
    "图呢",
    "来图",
    "上图",
    "发图",
)


class LuoguPlanStepType(str, Enum):
    CALL_TOOL = "CALL_TOOL"


@dataclass(slots=True)
class LuoguPlanStep:
    step_type: LuoguPlanStepType
    tool_name: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LuoguWorkflowPlan:
    intent: LuoguIntent
    workflow_state: LuoguWorkflowState
    allowed_tools: List[str]
    sequence_hint: str
    steps: List[LuoguPlanStep] = field(default_factory=list)
    commands: List[LuoguCommand] = field(default_factory=list)


def detect_selected_image_follow_up_intent(
    message: str,
    session_state: Optional[Mapping[str, Any]],
) -> Optional[LuoguIntent]:
    state = session_state or {}
    current_pid = str(state.get("current_pid") or "").strip().upper()
    text = str(message or "").strip().lower()
    if not current_pid or not text or len(text) > 12:
        return None
    if not any(marker in text for marker in SHORT_IMAGE_FOLLOW_UP_MARKERS):
        return None
    return LuoguIntent(
        intent=LuoguIntentName.REQUEST_IMAGE,
        target=LuoguIntentTarget.CURRENT_SELECTED,
        constraints={"pid": current_pid, "mode": "rendered"},
        confidence=0.95,
        raw_message=str(message or ""),
    )


def plan_luogu_workflow(
    intent: LuoguIntent,
    session_state: Optional[Mapping[str, Any]],
) -> Optional[LuoguWorkflowPlan]:
    state = derive_luogu_workflow_state(session_state)
    if (
        intent.intent == LuoguIntentName.REQUEST_IMAGE
        and intent.target == LuoguIntentTarget.CURRENT_SELECTED
        and state == LuoguWorkflowState.HAVE_SELECTED
    ):
        pid = str(intent.constraints.get("pid") or session_state.get("current_pid") or "").strip().upper()
        mode = str(intent.constraints.get("mode") or "rendered").strip() or "rendered"
        command = LuoguCommand(
            name="send_problem_image",
            payload={"pid": pid, "mode": mode},
            idempotency_key=f"image:{pid}:{mode}",
            precondition="session.current_pid exists",
            postcondition="problem image is sent for current_pid",
        )
        return LuoguWorkflowPlan(
            intent=intent,
            workflow_state=state,
            allowed_tools=["luogu_problem_image"],
            sequence_hint=(
                "这是 FSM/Planner 接管的已选题图片追问。"
                "当前 workflow state=HAVE_SELECTED，"
                "直接调用 `luogu_problem_image` 并沿用当前 session 的 `current_pid`。"
            ),
            steps=[
                LuoguPlanStep(
                    step_type=LuoguPlanStepType.CALL_TOOL,
                    tool_name="luogu_problem_image",
                    payload={"pid": pid, "mode": mode},
                )
            ],
            commands=[command],
        )
    return None
