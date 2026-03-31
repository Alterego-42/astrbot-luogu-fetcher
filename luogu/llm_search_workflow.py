from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .llm_routing_policy import consume_luogu_pending_clarification, interpret_luogu_follow_up
from .nl_jump import parse_jump_natural_language
from .problem_lookup import (
    extract_problem_id,
    format_luogu_problem_tool_result,
    lookup_luogu_problem_by_pid,
    lookup_luogu_problems,
    lookup_luogu_problems_from_list_url,
    merge_luogu_lookup_context,
    normalize_problem_lookup_tags,
    preflight_luogu_problem_tool_action,
    run_problem_async,
    should_merge_luogu_lookup_context,
    should_start_new_luogu_lookup,
)
from .request_count import clamp_luogu_request_count, parse_luogu_requested_count
from .session_events import (
    EVENT_CANDIDATES_UPDATED,
    EVENT_PROBLEM_SELECTED,
    append_session_event,
)
from .tags import DIFFICULTY_NAMES, HOT_TAGS


def build_default_lookup_intent(query: str, session: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    requested_count = clamp_luogu_request_count(
        parse_luogu_requested_count(query) or (session or {}).get("requested_count")
    )
    fallback_keyword = None
    if not (
        session
        and should_merge_luogu_lookup_context(query)
        and not should_start_new_luogu_lookup(
            query,
            action="search",
            difficulty=None,
            tags=[],
            keyword=query,
            unresolved_tags=[],
        )
    ):
        fallback_keyword = query
    return {
        "action": "search",
        "difficulty": None,
        "tags": [],
        "keyword": fallback_keyword,
        "index": None,
        "count": requested_count,
        "need_clarification": False,
        "clarification": None,
        "reply": None,
    }


async def execute_luogu_lookup_turn(
    *,
    context: Any,
    event: Any,
    cfile: str,
    query: str,
    limit: int,
    session_data: Optional[Mapping[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    session = dict(session_data or {})
    query, session, _clarification_consumed = consume_luogu_pending_clarification(query, session)

    direct_pid = extract_problem_id(query)
    if direct_pid:
        payload = await run_problem_async(
            cfile,
            lookup_luogu_problem_by_pid,
            pid=direct_pid,
        )
        result = format_luogu_problem_tool_result(
            query=query,
            action="search",
            difficulty=None,
            tags=[],
            keyword=None,
            unresolved_tags=[],
            payload=payload,
        )
        updated_session = remember_luogu_lookup_session(
            session,
            query=query,
            difficulty=None,
            tags=[],
            keyword=None,
            unresolved_tags=[],
            limit=limit,
            payload=payload,
            requested_count=1,
        )
        return result, updated_session

    intent = await parse_jump_natural_language(context, event, query, HOT_TAGS)
    if not intent:
        intent = build_default_lookup_intent(query, session)

    parsed_action = intent.get("action") or "search"
    requested_count = clamp_luogu_request_count(int(intent.get("count") or 1))
    parsed_tags, parsed_unresolved_tags = normalize_problem_lookup_tags(intent.get("tags"))
    parsed_keyword = intent.get("keyword") or None
    force_new_lookup = should_start_new_luogu_lookup(
        query,
        action=parsed_action,
        difficulty=intent.get("difficulty"),
        tags=parsed_tags,
        keyword=parsed_keyword,
        unresolved_tags=parsed_unresolved_tags,
    )

    follow_up = derive_luogu_search_follow_up(
        query=query,
        session=session,
        force_new_lookup=force_new_lookup,
        parsed_action=parsed_action,
        parsed_tags=parsed_tags,
        parsed_unresolved_tags=parsed_unresolved_tags,
        parsed_keyword=parsed_keyword,
        difficulty=intent.get("difficulty"),
        index=intent.get("index"),
        count=requested_count,
    )
    if follow_up and session:
        follow_up_result, updated_session = await execute_luogu_follow_up(
            cfile=cfile,
            query=query,
            limit=limit,
            session=session,
            follow_up=follow_up,
        )
        if follow_up_result:
            return follow_up_result, dict(updated_session or session)
        if updated_session is not None:
            session = dict(updated_session)

    if intent.get("need_clarification"):
        clarification = intent.get("clarification") or "需求还不够明确，请补充题目的难度、标签或关键词。"
        updated_session = remember_luogu_clarification_session(
            session,
            original_query=query,
            question=clarification,
            partial_intent={
                "difficulty": intent.get("difficulty"),
                "tags": parsed_tags,
                "keyword": parsed_keyword,
            },
        )
        return clarification, updated_session

    action = intent.get("action") or "search"
    tags = parsed_tags
    unresolved_tags = parsed_unresolved_tags
    keyword = parsed_keyword
    merged_lookup = merge_luogu_lookup_context(
        session,
        query=query,
        action=action,
        difficulty=intent.get("difficulty"),
        tags=tags,
        keyword=keyword,
        unresolved_tags=unresolved_tags,
    )
    action = merged_lookup.get("action") or action
    difficulty = merged_lookup.get("difficulty")
    tags = merged_lookup.get("tags") or []
    keyword = merged_lookup.get("keyword") or None
    unresolved_tags = merged_lookup.get("unresolved_tags") or []

    preflight_error = preflight_luogu_problem_tool_action(
        action,
        index=intent.get("index"),
        difficulty=difficulty,
        tags=tags,
        keyword=keyword,
    )
    if preflight_error:
        return preflight_error, session

    if unresolved_tags:
        unresolved_text = " ".join(unresolved_tags)
        keyword = f"{keyword} {unresolved_text}".strip() if keyword else unresolved_text

    payload = await run_problem_async(
        cfile,
        lookup_luogu_problems,
        difficulty=difficulty,
        tags=tags,
        keyword=keyword,
        limit=max(limit, requested_count),
        action=action,
        index=intent.get("index"),
        count=requested_count,
    )
    updated_session = remember_luogu_lookup_session(
        session,
        query=query,
        difficulty=difficulty,
        tags=tags,
        keyword=keyword,
        unresolved_tags=unresolved_tags,
        limit=max(limit, requested_count),
        payload=payload,
        requested_count=requested_count,
    )
    return (
        format_luogu_problem_tool_result(
            query=query,
            action=action,
            difficulty=difficulty,
            tags=tags,
            keyword=keyword,
            unresolved_tags=unresolved_tags,
            payload=payload,
        ),
        updated_session,
    )


def derive_luogu_search_follow_up(
    *,
    query: str,
    session: Optional[Mapping[str, Any]],
    force_new_lookup: bool,
    parsed_action: str,
    parsed_tags: list[str],
    parsed_unresolved_tags: list[str],
    parsed_keyword: Optional[str],
    difficulty: Optional[int],
    index: Optional[int],
    count: int,
) -> Optional[Dict[str, Any]]:
    if force_new_lookup or not session:
        return None

    follow_up = interpret_luogu_follow_up(query, dict(session))
    if follow_up:
        return follow_up

    has_new_constraints = bool(
        parsed_tags
        or parsed_unresolved_tags
        or parsed_keyword
        or difficulty is not None
    )
    if parsed_action == "random" and not has_new_constraints:
        return {"kind": "random", "count": clamp_luogu_request_count(count or session.get("requested_count"))}
    if parsed_action == "select" and not has_new_constraints and index:
        return {"kind": "select", "index": index}
    if parsed_action in ("show_image", "show_screenshot") and session.get("current_pid"):
        return {
            "kind": "image",
            "mode": "screenshot" if parsed_action == "show_screenshot" else "rendered",
        }
    return None


def remember_luogu_lookup_session(
    session_data: Optional[Mapping[str, Any]],
    *,
    query: str,
    difficulty: Optional[int],
    tags: list[str],
    keyword: Optional[str],
    unresolved_tags: list[str],
    limit: int,
    payload: Mapping[str, Any],
    requested_count: int = 1,
) -> Dict[str, Any]:
    session = dict(session_data or {})
    session.update(
        {
            "query": query,
            "difficulty": difficulty,
            "tags": list(tags),
            "keyword": keyword,
            "unresolved_tags": list(unresolved_tags),
            "limit": limit,
            "total": int(payload.get("total") or 0),
            "page_size": int(payload.get("page_size") or 0),
            "list_url": payload.get("list_url"),
            "summaries": list(payload.get("summaries") or []),
            "shown_count": len(payload.get("summaries") or []),
            "requested_count": clamp_luogu_request_count(requested_count),
        }
    )
    append_session_event(
        session,
        EVENT_CANDIDATES_UPDATED,
        total=int(payload.get("total") or 0),
        list_url=payload.get("list_url"),
        difficulty=difficulty,
        tags=list(tags),
        keyword=keyword,
        requested_count=clamp_luogu_request_count(requested_count),
    )
    chosen = payload.get("chosen") or {}
    if chosen:
        session["current_pid"] = chosen.get("pid")
        session["current_title"] = chosen.get("title")
        append_session_event(
            session,
            EVENT_PROBLEM_SELECTED,
            pid=chosen.get("pid"),
            title=chosen.get("title"),
            list_url=payload.get("list_url"),
        )
    else:
        session.pop("current_pid", None)
        session.pop("current_title", None)
        session.pop("current_md", None)
    session.pop("pending_clarification", None)
    return session


def remember_luogu_clarification_session(
    session_data: Optional[Mapping[str, Any]],
    *,
    original_query: str,
    question: str,
    partial_intent: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    session = dict(session_data or {})
    session["pending_clarification"] = {
        "original_query": str(original_query or "").strip(),
        "question": str(question or "").strip(),
        "partial_intent": dict(partial_intent or {}),
    }
    return session


def render_luogu_lookup_candidate_list(session_data: Mapping[str, Any]) -> str:
    payload = {
        "success": True,
        "total": int(session_data.get("total") or 0),
        "list_url": session_data.get("list_url"),
        "summaries": list(session_data.get("summaries") or []),
    }
    return format_luogu_problem_tool_result(
        query=str(session_data.get("query") or "当前洛谷筛选条件"),
        action="search",
        difficulty=session_data.get("difficulty"),
        tags=list(session_data.get("tags") or []),
        keyword=session_data.get("keyword"),
        unresolved_tags=list(session_data.get("unresolved_tags") or []),
        payload=payload,
    )


def format_luogu_session_snapshot(session_data: Optional[Mapping[str, Any]]) -> str:
    if not session_data:
        return "当前没有活跃的洛谷普通聊天 session。若要开始新的选题流程，请先调用 `luogu_problem_search`。"

    filters: list[str] = []
    difficulty = session_data.get("difficulty")
    if isinstance(difficulty, int):
        if difficulty == 0:
            filters.append("难度=不限")
        elif 1 <= difficulty <= len(DIFFICULTY_NAMES):
            filters.append(f"难度={DIFFICULTY_NAMES[difficulty - 1]}")
    if session_data.get("tags"):
        filters.append("标签=" + "、".join(str(tag) for tag in session_data.get("tags") or []))
    if session_data.get("keyword"):
        filters.append(f"关键词={session_data.get('keyword')}")

    parts = [
        f"当前筛选条件：{'；'.join(filters) if filters else '未记录'}",
        f"当前候选总数：{int(session_data.get('total') or 0)}",
        f"当前列表链接：{session_data.get('list_url') or '无'}",
    ]
    current_pid = str(session_data.get("current_pid") or "").strip()
    current_title = str(session_data.get("current_title") or "").strip()
    if current_pid:
        parts.append(f"当前已选中题目：{current_pid} {current_title}".strip())
    else:
        parts.append("当前还没有选中题目。")
    pending = session_data.get("pending_clarification") or {}
    if pending.get("question"):
        parts.append(f"当前待补充信息：{pending.get('question')}")
    return "\n".join(parts)


def resolve_luogu_target_pid(
    *,
    requested_pid: Optional[str],
    event_message: str,
    session_data: Optional[Mapping[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    explicit_pid = extract_problem_id(str(requested_pid or "").strip())
    if not explicit_pid:
        explicit_pid = extract_problem_id(str(event_message or ""))
    if explicit_pid:
        return explicit_pid, None

    session = dict(session_data or {})
    current_pid = str(session.get("current_pid") or "").strip().upper()
    if current_pid:
        normalized_pid = current_pid if current_pid.startswith("P") else f"P{current_pid}"
        return normalized_pid, None

    total = int(session.get("total") or 0)
    shown = int(session.get("shown_count") or 0)
    if total > 0:
        return None, (
            f"当前会话只有候选列表，还没有真正选中题目。"
            f"请先指定“第N题”或“随机来一道”完成选题。"
            f"这一轮候选共 {total} 道，当前展示了前 {shown} 道。"
        )
    return None, "当前会话还没有选中的题目。请先用 `luogu_problem_search` 选出一道题，再调用题面或题图工具。"


async def execute_luogu_follow_up(
    *,
    cfile: str,
    query: str,
    limit: int,
    session: Mapping[str, Any],
    follow_up: Mapping[str, Any],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    kind = str(follow_up.get("kind") or "")

    if kind == "count":
        total = int(session.get("total") or 0)
        shown = int(session.get("shown_count") or 0)
        return f"上一轮洛谷筛选共找到 {total} 道题。上次只展示了前 {shown} 道候选，不是总数。", None

    if kind in ("random", "select"):
        requested_count = clamp_luogu_request_count(int(follow_up.get("count") or session.get("requested_count") or 1))
        if kind == "select":
            select_index = int(follow_up.get("index") or 0)
            summaries = list(session.get("summaries") or [])
            if 1 <= select_index <= len(summaries):
                selected_summary = dict(summaries[select_index - 1] or {})
                selected_pid = str(selected_summary.get("pid") or "").strip()
                if selected_pid:
                    payload = await run_problem_async(
                        cfile,
                        lookup_luogu_problem_by_pid,
                        pid=selected_pid,
                    )
                    payload["requested_count"] = requested_count
                    updated_session = remember_luogu_lookup_session(
                        session,
                        query=query,
                        difficulty=session.get("difficulty"),
                        tags=list(session.get("tags") or []),
                        keyword=session.get("keyword"),
                        unresolved_tags=list(session.get("unresolved_tags") or []),
                        limit=int(session.get("limit") or limit),
                        payload=payload,
                        requested_count=requested_count,
                    )
                    return (
                        format_luogu_problem_tool_result(
                            query=query,
                            action="select",
                            difficulty=session.get("difficulty"),
                            tags=list(session.get("tags") or []),
                            keyword=session.get("keyword"),
                            unresolved_tags=list(session.get("unresolved_tags") or []),
                            payload=payload,
                        ),
                        updated_session,
                    )
        session_list_url = session.get("list_url")
        if session_list_url:
            payload = await run_problem_async(
                cfile,
                lookup_luogu_problems_from_list_url,
                list_url=session_list_url,
                total=session.get("total"),
                page_size=session.get("page_size"),
                limit=session.get("limit") or limit,
                action="random" if kind == "random" else "select",
                index=follow_up.get("index"),
                count=requested_count,
            )
        else:
            payload = await run_problem_async(
                cfile,
                lookup_luogu_problems,
                difficulty=session.get("difficulty"),
                tags=session.get("tags") or [],
                keyword=session.get("keyword"),
                limit=session.get("limit") or limit,
                action="random" if kind == "random" else "select",
                index=follow_up.get("index"),
                count=requested_count,
            )
        updated_session = remember_luogu_lookup_session(
            session,
            query=query,
            difficulty=session.get("difficulty"),
            tags=list(session.get("tags") or []),
            keyword=session.get("keyword"),
            unresolved_tags=list(session.get("unresolved_tags") or []),
            limit=int(session.get("limit") or limit),
            payload=payload,
            requested_count=requested_count,
        )
        return (
            format_luogu_problem_tool_result(
                query=query,
                action="random" if kind == "random" else "select",
                difficulty=session.get("difficulty"),
                tags=list(session.get("tags") or []),
                keyword=session.get("keyword"),
                unresolved_tags=list(session.get("unresolved_tags") or []),
                payload=payload,
            ),
            updated_session,
        )

    if kind == "repeat_candidates":
        return render_luogu_lookup_candidate_list(session), None

    current_pid = session.get("current_pid")
    if not current_pid:
        return "当前还没有选中的题目。请先让我检索并选出一道题，再调用题面或题图工具。", None

    if kind == "forward":
        return f"当前会话已选中 {current_pid}。请改为调用 `luogu_problem_statement(pid={current_pid!r})` 发送题面。", None

    if kind == "image":
        mode = follow_up.get("mode") or "rendered"
        return f"当前会话已选中 {current_pid}。请改为调用 `luogu_problem_image(pid={current_pid!r}, mode={mode!r})` 发送题图。", None

    return "", None
