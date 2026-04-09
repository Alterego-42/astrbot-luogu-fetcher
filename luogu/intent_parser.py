from __future__ import annotations

from typing import Any, Mapping, Optional

from .intent_schema import LuoguIntent, LuoguIntentName, LuoguIntentTarget


def _normalize_follow_up_tools(
    *,
    requests_statement: bool,
    requests_image: bool,
    default_statement: bool,
) -> list[str]:
    tools: list[str] = []
    if requests_statement:
        tools.append("luogu_problem_statement")
    if requests_image:
        tools.append("luogu_problem_image")
    if not tools and default_statement:
        tools.append("luogu_problem_statement")
    return tools


def _normalize_explicit_after_tools(
    preferred_after_tools: Optional[list[str]],
    *,
    requests_statement: bool,
    requests_image: bool,
    default_statement: bool,
) -> list[str]:
    allowed = {"luogu_problem_statement", "luogu_problem_image"}
    if preferred_after_tools is not None:
        return [str(tool) for tool in preferred_after_tools if str(tool) in allowed]
    return _normalize_follow_up_tools(
        requests_statement=requests_statement,
        requests_image=requests_image,
        default_statement=default_statement,
    )


def parse_luogu_workflow_intent(
    *,
    message: str,
    session_state: Optional[Mapping[str, Any]],
    follow_up: Optional[Mapping[str, Any]],
    direct_pid: Optional[str],
    requests_statement: bool,
    requests_image: bool,
    requests_random: bool,
    preferred_after_tools: Optional[list[str]] = None,
) -> Optional[LuoguIntent]:
    text = str(message or "").strip()
    current_pid = str((session_state or {}).get("current_pid") or "").strip().upper()
    follow_up_kind = str((follow_up or {}).get("kind") or "")
    image_mode = str((follow_up or {}).get("mode") or "rendered")

    if direct_pid:
        if requests_statement and requests_image:
            return LuoguIntent(
                intent=LuoguIntentName.REQUEST_STATEMENT,
                target=LuoguIntentTarget.DIRECT_PID,
                constraints={"pid": direct_pid, "after_tools": ["luogu_problem_image"], "image_mode": image_mode},
                confidence=0.98,
                raw_message=text,
            )
        if requests_image:
            return LuoguIntent(
                intent=LuoguIntentName.REQUEST_IMAGE,
                target=LuoguIntentTarget.DIRECT_PID,
                constraints={"pid": direct_pid, "mode": image_mode},
                confidence=0.98,
                raw_message=text,
            )
        if requests_statement or text.upper() == str(direct_pid).upper():
            return LuoguIntent(
                intent=LuoguIntentName.REQUEST_STATEMENT,
                target=LuoguIntentTarget.DIRECT_PID,
                constraints={"pid": direct_pid},
                confidence=0.98,
                raw_message=text,
            )

    if current_pid and requests_image and text and len(text) <= 12:
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_IMAGE,
            target=LuoguIntentTarget.CURRENT_SELECTED,
            constraints={"pid": current_pid, "mode": "rendered"},
            confidence=0.95,
            raw_message=text,
        )

    if current_pid and requests_statement and requests_image:
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_STATEMENT,
            target=LuoguIntentTarget.CURRENT_SELECTED,
            constraints={"pid": current_pid, "after_tools": ["luogu_problem_image"], "image_mode": image_mode},
            confidence=0.94,
            raw_message=text,
        )

    if follow_up_kind == "image":
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_IMAGE,
            target=LuoguIntentTarget.CURRENT_SELECTED,
            constraints={"pid": current_pid, "mode": image_mode},
            confidence=0.95,
            raw_message=text,
        )

    if follow_up_kind == "forward" or (current_pid and requests_statement):
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_STATEMENT,
            target=LuoguIntentTarget.CURRENT_SELECTED,
            constraints={"pid": current_pid},
            confidence=0.93,
            raw_message=text,
        )

    if follow_up_kind == "count":
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_COUNT,
            target=LuoguIntentTarget.CURRENT_CANDIDATES,
            constraints={"source": "session_candidates"},
            confidence=0.95,
            raw_message=text,
        )

    if follow_up_kind == "repeat_candidates":
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_SEARCH,
            target=LuoguIntentTarget.CURRENT_CANDIDATES,
            constraints={"source": "session_candidates", "mode": "repeat_candidates"},
            confidence=0.95,
            raw_message=text,
        )

    if follow_up_kind == "select":
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_SELECT,
            target=LuoguIntentTarget.CURRENT_CANDIDATES,
            constraints={
                "index": follow_up.get("index"),
                "after_tools": _normalize_explicit_after_tools(
                    follow_up.get("after_tools") if follow_up else preferred_after_tools,
                    requests_statement=requests_statement,
                    requests_image=requests_image,
                    default_statement=True,
                ),
            },
            confidence=0.95,
            raw_message=text,
        )

    if follow_up_kind == "random":
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_RANDOM,
            target=LuoguIntentTarget.CURRENT_CANDIDATES,
            constraints={
                "after_tools": _normalize_explicit_after_tools(
                    follow_up.get("after_tools") if follow_up else preferred_after_tools,
                    requests_statement=requests_statement,
                    requests_image=requests_image,
                    default_statement=True,
                ),
            },
            confidence=0.95,
            raw_message=text,
        )

    if requests_random:
        return LuoguIntent(
            intent=LuoguIntentName.REQUEST_RANDOM,
            target=LuoguIntentTarget.NONE,
            constraints={
                "after_tools": _normalize_explicit_after_tools(
                    preferred_after_tools,
                    requests_statement=False,
                    requests_image=False,
                    default_statement=True,
                ),
                "source": "fresh_lookup",
            },
            confidence=0.8,
            raw_message=text,
        )

    if requests_statement or requests_image:
        return None

    return LuoguIntent(
        intent=LuoguIntentName.REQUEST_SEARCH,
        target=LuoguIntentTarget.NONE,
        constraints={"source": "fresh_lookup"},
        confidence=0.7,
        raw_message=text,
    )
