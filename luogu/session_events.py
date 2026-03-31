from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


EVENT_SEARCH_STARTED = "SearchStarted"
EVENT_CANDIDATES_UPDATED = "CandidatesUpdated"
EVENT_PROBLEM_SELECTED = "ProblemSelected"
EVENT_STATEMENT_SENT = "StatementSent"
EVENT_IMAGE_SENT = "ImageSent"
EVENT_TOOL_FAILED = "ToolFailed"


def append_session_event(session_data: Dict[str, Any], event_type: str, **payload: Any) -> Dict[str, Any]:
    events = list(session_data.get("events") or [])
    events.append({"type": event_type, "payload": dict(payload)})
    session_data["events"] = events
    return session_data


def replay_luogu_session_state(
    events: List[Mapping[str, Any]] | None,
    *,
    fallback: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "current_pid": None,
        "current_title": None,
        "current_md": None,
        "current_image_mode": None,
        "total": 0,
        "list_url": None,
        "difficulty": None,
        "tags": [],
        "keyword": None,
        "requested_count": 1,
        "last_error": None,
    }

    for event in events or []:
        event_type = str(event.get("type") or "")
        payload = dict(event.get("payload") or {})
        if event_type in {EVENT_SEARCH_STARTED, EVENT_CANDIDATES_UPDATED}:
            if payload.get("total") is not None:
                state["total"] = int(payload.get("total") or 0)
            if payload.get("list_url"):
                state["list_url"] = payload.get("list_url")
            if payload.get("difficulty") is not None:
                state["difficulty"] = payload.get("difficulty")
            if payload.get("tags") is not None:
                state["tags"] = list(payload.get("tags") or [])
            if payload.get("keyword") is not None:
                state["keyword"] = payload.get("keyword")
            if payload.get("requested_count") is not None:
                state["requested_count"] = int(payload.get("requested_count") or 1)
            state["last_error"] = None
        elif event_type == EVENT_PROBLEM_SELECTED:
            state["current_pid"] = payload.get("pid")
            state["current_title"] = payload.get("title")
            if payload.get("list_url"):
                state["list_url"] = payload.get("list_url")
            state["last_error"] = None
        elif event_type == EVENT_STATEMENT_SENT:
            if payload.get("pid"):
                state["current_pid"] = payload.get("pid")
            if payload.get("title"):
                state["current_title"] = payload.get("title")
            if payload.get("markdown") is not None:
                state["current_md"] = payload.get("markdown")
            state["last_error"] = None
        elif event_type == EVENT_IMAGE_SENT:
            if payload.get("pid"):
                state["current_pid"] = payload.get("pid")
            if payload.get("mode"):
                state["current_image_mode"] = payload.get("mode")
            state["last_error"] = None
        elif event_type == EVENT_TOOL_FAILED:
            state["last_error"] = payload.get("reason") or payload.get("tool")

    fallback_data = dict(fallback or {})
    for key in ("current_pid", "current_title", "current_md", "list_url", "keyword", "last_error"):
        if not state.get(key) and fallback_data.get(key):
            state[key] = fallback_data.get(key)
    if not state.get("total") and fallback_data.get("total") is not None:
        state["total"] = int(fallback_data.get("total") or 0)
    if state.get("difficulty") is None and fallback_data.get("difficulty") is not None:
        state["difficulty"] = fallback_data.get("difficulty")
    if not state.get("tags") and fallback_data.get("tags"):
        state["tags"] = list(fallback_data.get("tags") or [])
    if not state.get("current_image_mode") and fallback_data.get("current_image_mode"):
        state["current_image_mode"] = fallback_data.get("current_image_mode")
    if fallback_data.get("requested_count") is not None and int(state.get("requested_count") or 0) <= 1:
        state["requested_count"] = int(fallback_data.get("requested_count") or 1)
    return state
