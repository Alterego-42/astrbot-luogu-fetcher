from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from .command_bus import LuoguCommand
from .intent_schema import LuoguIntent, LuoguIntentName, LuoguIntentTarget
from .workflow import LuoguWorkflowState, derive_luogu_workflow_state


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


def _normalize_after_tools(intent: LuoguIntent, *, default: Optional[list[str]] = None) -> list[str]:
    allowed = {"luogu_problem_statement", "luogu_problem_image"}
    return [
        str(tool)
        for tool in (intent.constraints.get("after_tools") or default or [])
        if str(tool) in allowed
    ]


def _build_tool_steps(
    tool_names: List[str],
    *,
    payload_by_tool: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[LuoguPlanStep]:
    return [
        LuoguPlanStep(
            step_type=LuoguPlanStepType.CALL_TOOL,
            tool_name=tool_name,
            payload=dict((payload_by_tool or {}).get(tool_name) or {}),
        )
        for tool_name in tool_names
    ]


def _plan_problem_display(
    intent: LuoguIntent,
    state: LuoguWorkflowState,
    *,
    pid: str,
    selected_from_session: bool,
) -> LuoguWorkflowPlan:
    image_mode = str(intent.constraints.get("image_mode") or intent.constraints.get("mode") or "rendered")
    if intent.intent == LuoguIntentName.REQUEST_STATEMENT:
        tool_names = ["luogu_problem_statement", *_normalize_after_tools(intent)]
        payload_by_tool: Dict[str, Dict[str, Any]] = {}
        if not selected_from_session:
            payload_by_tool["luogu_problem_statement"] = {"pid": pid}
        if "luogu_problem_image" in tool_names:
            payload_by_tool["luogu_problem_image"] = {} if selected_from_session else {"pid": pid, "mode": image_mode}
        sequence_hint = (
            "用户已经给出题号，且同时想看题面和题图。先调用 `luogu_problem_statement`，再调用 `luogu_problem_image`。"
            if intent.target == LuoguIntentTarget.DIRECT_PID and "luogu_problem_image" in tool_names
            else "用户已经给出题号且想看题面，直接调用 `luogu_problem_statement`。"
            if intent.target == LuoguIntentTarget.DIRECT_PID
            else "这是题面阶段，直接调用 `luogu_problem_statement`。如果参数里没给 pid，就让工具读取当前 session 的 `current_pid`。"
        )
        commands = [
            LuoguCommand(
                name="send_problem_statement",
                payload={} if selected_from_session else {"pid": pid},
                idempotency_key=f"statement:{pid or 'session'}",
                precondition="target pid is available directly or in session.current_pid",
                postcondition="problem statement is sent",
            )
        ]
        if "luogu_problem_image" in tool_names:
            commands.append(
                LuoguCommand(
                    name="send_problem_image",
                    payload={"mode": image_mode, **({} if selected_from_session else {'pid': pid})},
                    idempotency_key=f"image-after-statement:{pid or 'session'}:{image_mode}",
                    precondition="target pid is available directly or in session.current_pid",
                    postcondition="problem image is sent after the statement",
                )
            )
        return LuoguWorkflowPlan(
            intent=intent,
            workflow_state=state,
            allowed_tools=tool_names,
            sequence_hint=sequence_hint,
            steps=_build_tool_steps(tool_names, payload_by_tool=payload_by_tool),
            commands=commands,
        )

    payload = {"mode": image_mode}
    if not selected_from_session:
        payload["pid"] = pid
    sequence_hint = (
        "用户已经给出题号且想看图，直接调用 `luogu_problem_image`。"
        if intent.target == LuoguIntentTarget.DIRECT_PID
        else "这是图片阶段，直接调用 `luogu_problem_image`。用户明确说“截图/官网截图”时传 `mode=\"screenshot\"`，否则用默认渲染图。"
    )
    return LuoguWorkflowPlan(
        intent=intent,
        workflow_state=state,
        allowed_tools=["luogu_problem_image"],
        sequence_hint=sequence_hint,
        steps=_build_tool_steps(["luogu_problem_image"], payload_by_tool={"luogu_problem_image": payload}),
        commands=[
            LuoguCommand(
                name="send_problem_image",
                payload=payload,
                idempotency_key=f"image:{pid or 'session'}:{image_mode}",
                precondition="target pid is available directly or in session.current_pid",
                postcondition="problem image is sent",
            )
        ],
    )


def _plan_candidate_read(intent: LuoguIntent, state: LuoguWorkflowState) -> LuoguWorkflowPlan:
    if intent.intent == LuoguIntentName.REQUEST_COUNT:
        sequence_hint = "这是候选结果追问阶段，只调用 `luogu_problem_search` 读取当前 session 的候选总数。"
        command_name = "count_candidates"
        mode = "count"
    else:
        sequence_hint = "这是候选结果追问阶段，只调用 `luogu_problem_search` 读取并复述当前 session 的候选列表。"
        command_name = "repeat_candidates"
        mode = "repeat_candidates"
    return LuoguWorkflowPlan(
        intent=intent,
        workflow_state=state,
        allowed_tools=["luogu_problem_search"],
        sequence_hint=sequence_hint,
        steps=_build_tool_steps(["luogu_problem_search"]),
        commands=[
            LuoguCommand(
                name=command_name,
                payload={"mode": mode},
                idempotency_key=f"{command_name}:{state.value}",
                precondition="session has active candidate results",
                postcondition="candidate session context is read without changing selection",
            )
        ],
    )


def _plan_candidate_transition(intent: LuoguIntent, state: LuoguWorkflowState) -> LuoguWorkflowPlan:
    selection_kind = "select" if intent.intent == LuoguIntentName.REQUEST_SELECT else "random"
    after_tools = _normalize_after_tools(intent, default=["luogu_problem_statement"])
    tool_names = ["luogu_problem_search", *after_tools]
    payload_by_tool: Dict[str, Dict[str, Any]] = {
        "luogu_problem_search": {
            "action": selection_kind,
            "index": intent.constraints.get("index"),
        }
    }
    commands = [
        LuoguCommand(
            name=f"{selection_kind}_candidate",
            payload=dict(payload_by_tool["luogu_problem_search"]),
            idempotency_key=f"{selection_kind}:{intent.constraints.get('index') or 'auto'}",
            precondition="session has active candidate results",
            postcondition="session.current_pid points to the newly chosen problem",
        )
    ]
    if "luogu_problem_statement" in after_tools:
        commands.append(
            LuoguCommand(
                name="send_problem_statement",
                precondition="selection writes session.current_pid",
                postcondition="selected problem statement is sent",
            )
        )
    if "luogu_problem_image" in after_tools:
        commands.append(
            LuoguCommand(
                name="send_problem_image",
                payload={"mode": "rendered"},
                precondition="selection writes session.current_pid",
                postcondition="selected problem image is sent",
            )
        )

    if selection_kind == "select":
        if after_tools == ["luogu_problem_statement", "luogu_problem_image"]:
            sequence_hint = "这是候选阶段的“先按序号选题，再发题面和题图”请求。先调用 `luogu_problem_search` 完成 select，再依次调用 `luogu_problem_statement` 和 `luogu_problem_image`。"
        elif after_tools == ["luogu_problem_image"]:
            sequence_hint = "这是候选阶段的“先按序号选题，再发题图”请求。先调用 `luogu_problem_search` 完成 select，确认 session 写入新的 `current_pid` 后，再调用 `luogu_problem_image`。"
        else:
            sequence_hint = "这是候选阶段的按序号选题请求。先调用 `luogu_problem_search` 完成 select；如果已经选出具体题目，再调用 `luogu_problem_statement`。"
    else:
        if after_tools == ["luogu_problem_statement", "luogu_problem_image"]:
            sequence_hint = "这是候选阶段的“随机选题后再发题面和题图”请求。先调用 `luogu_problem_search` 完成 random，再依次调用 `luogu_problem_statement` 和 `luogu_problem_image`。"
        elif after_tools == ["luogu_problem_image"]:
            sequence_hint = "这是候选阶段的“随机选题后再发题图”请求。先调用 `luogu_problem_search` 完成 random，确认 session 写入新的 `current_pid` 后，再调用 `luogu_problem_image`。"
        else:
            sequence_hint = "这是候选阶段的随机选题请求。先调用 `luogu_problem_search` 完成 random；如果已经选出具体题目，再调用 `luogu_problem_statement`。"

    return LuoguWorkflowPlan(
        intent=intent,
        workflow_state=state,
        allowed_tools=tool_names,
        sequence_hint=sequence_hint,
        steps=_build_tool_steps(tool_names, payload_by_tool=payload_by_tool),
        commands=commands,
    )


def _plan_fresh_lookup(intent: LuoguIntent, state: LuoguWorkflowState) -> LuoguWorkflowPlan:
    if intent.intent == LuoguIntentName.REQUEST_RANDOM:
        after_tools = _normalize_after_tools(intent, default=["luogu_problem_statement"])
        tool_names = ["luogu_problem_search", *after_tools]
        commands = [
            LuoguCommand(
                name="start_random_lookup",
                idempotency_key="fresh-random-lookup",
                precondition="no direct pid is supplied",
                postcondition="a random problem is chosen from current request constraints",
            )
        ]
        if "luogu_problem_statement" in after_tools:
            commands.append(
                LuoguCommand(
                    name="send_problem_statement",
                    precondition="search writes session.current_pid",
                    postcondition="selected problem statement is sent",
                )
            )
        return LuoguWorkflowPlan(
            intent=intent,
            workflow_state=state,
            allowed_tools=tool_names,
            sequence_hint=(
                "用户明确要求随机选题。先调用 `luogu_problem_search` 完成随机选择。"
                "只有在搜索结果已经选出具体题目后，后续轮次再调用展示工具。"
            ),
            steps=_build_tool_steps(tool_names),
            commands=commands,
        )

    return LuoguWorkflowPlan(
        intent=intent,
        workflow_state=state,
        allowed_tools=["luogu_problem_search"],
        sequence_hint=(
            "这是候选筛题阶段，只调用 `luogu_problem_search`。"
            "如果结果只是候选列表、总数或条件说明，不要提前调用题面或题图工具。"
            "只有明确选中了具体题目后，后续轮次再调用 `luogu_problem_statement` 或 `luogu_problem_image`。"
        ),
        steps=_build_tool_steps(["luogu_problem_search"]),
        commands=[
            LuoguCommand(
                name="search_candidates",
                idempotency_key="fresh-search-lookup",
                precondition="message describes lookup constraints instead of a direct pid",
                postcondition="session is updated with fresh candidate results",
            )
        ],
    )


def plan_luogu_workflow(
    intent: Optional[LuoguIntent],
    session_state: Optional[Mapping[str, Any]],
) -> Optional[LuoguWorkflowPlan]:
    if intent is None:
        return None

    current_session = dict(session_state or {})
    state = derive_luogu_workflow_state(current_session)

    if (
        intent.intent in {LuoguIntentName.REQUEST_STATEMENT, LuoguIntentName.REQUEST_IMAGE}
        and intent.target == LuoguIntentTarget.DIRECT_PID
    ):
        pid = str(intent.constraints.get("pid") or "").strip().upper()
        if pid:
            return _plan_problem_display(intent, state, pid=pid, selected_from_session=False)

    if (
        intent.intent in {LuoguIntentName.REQUEST_STATEMENT, LuoguIntentName.REQUEST_IMAGE}
        and intent.target == LuoguIntentTarget.CURRENT_SELECTED
        and state == LuoguWorkflowState.HAVE_SELECTED
    ):
        pid = str(intent.constraints.get("pid") or current_session.get("current_pid") or "").strip().upper()
        return _plan_problem_display(intent, state, pid=pid, selected_from_session=True)

    if (
        intent.intent in {LuoguIntentName.REQUEST_COUNT, LuoguIntentName.REQUEST_SEARCH}
        and intent.target == LuoguIntentTarget.CURRENT_CANDIDATES
        and state == LuoguWorkflowState.HAVE_CANDIDATES
    ):
        return _plan_candidate_read(intent, state)

    if (
        intent.intent in {LuoguIntentName.REQUEST_SELECT, LuoguIntentName.REQUEST_RANDOM}
        and intent.target == LuoguIntentTarget.CURRENT_CANDIDATES
        and state == LuoguWorkflowState.HAVE_CANDIDATES
    ):
        return _plan_candidate_transition(intent, state)

    if intent.intent in {LuoguIntentName.REQUEST_SEARCH, LuoguIntentName.REQUEST_RANDOM}:
        return _plan_fresh_lookup(intent, state)

    return None
