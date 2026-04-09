from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


_ALLOWED_CONFIDENCE = {"low", "medium", "high"}
_ALLOWED_INTENTS = {
    "search",
    "count",
    "select",
    "random",
    "replace",
    "statement",
    "image",
    "repeat_candidates",
    "clarify",
    "reject",
    "unknown",
}
_ALLOWED_TARGETS = {
    "fresh_lookup",
    "current_candidates",
    "current_selected",
    "direct_pid",
    "none",
}
_ALLOWED_SEARCH_ACTIONS = {
    "search",
    "count",
    "select",
    "random",
    "repeat_candidates",
    "unknown",
}
_ALLOWED_TOOLS = {
    "luogu_problem_search",
    "luogu_problem_statement",
    "luogu_problem_image",
}


@dataclass(slots=True)
class LuoguSemanticDecision:
    route_to_luogu: bool = False
    confidence: str = "low"
    intent: str = "unknown"
    target: str = "none"
    direct_pid: Optional[str] = None
    index: Optional[int] = None
    image_mode: str = "rendered"
    search_action: str = "unknown"
    tool_candidates: List[str] = field(default_factory=list)
    preferred_after_tools: Optional[List[str]] = None
    reason: Optional[str] = None


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None

    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _normalize_tools(values: Any) -> List[str]:
    items = values if isinstance(values, list) else []
    normalized: List[str] = []
    for item in items:
        name = str(item or "").strip()
        if name in _ALLOWED_TOOLS and name not in normalized:
            normalized.append(name)
    return normalized


def _normalize_pid(value: Any) -> Optional[str]:
    text = str(value or "").strip().upper()
    if not text:
        return None
    match = re.search(r"\bP?\d{1,6}\b", text)
    if not match:
        return None
    pid = match.group(0)
    return pid if pid.startswith("P") else f"P{pid}"


def _normalize_index(value: Any) -> Optional[int]:
    try:
        index = int(value)
    except Exception:
        return None
    return index if index > 0 else None


def _build_session_snapshot(session_state: Optional[Mapping[str, Any]]) -> str:
    session = dict(session_state or {})
    if not session:
        return "无活跃 Luogu session。"

    current_pid = str(session.get("current_pid") or "").strip()
    current_title = str(session.get("current_title") or "").strip()
    tags = "、".join(str(tag) for tag in session.get("tags") or []) or "无"
    return (
        f"query={session.get('query') or '无'}; "
        f"total={int(session.get('total') or 0)}; "
        f"shown_count={int(session.get('shown_count') or 0)}; "
        f"current_pid={current_pid or '无'}; "
        f"current_title={current_title or '无'}; "
        f"tags={tags}; "
        f"difficulty={session.get('difficulty') if session.get('difficulty') is not None else '无'}"
    )


def _sanitize_semantic_decision(data: Dict[str, Any]) -> LuoguSemanticDecision:
    confidence = str(data.get("confidence") or "low").strip().lower()
    if confidence not in _ALLOWED_CONFIDENCE:
        confidence = "low"

    intent = str(data.get("intent") or "unknown").strip().lower()
    if intent not in _ALLOWED_INTENTS:
        intent = "unknown"

    target = str(data.get("target") or "none").strip().lower()
    if target not in _ALLOWED_TARGETS:
        target = "none"

    image_mode = str(data.get("image_mode") or "rendered").strip().lower()
    if image_mode not in {"rendered", "screenshot"}:
        image_mode = "rendered"

    search_action = str(data.get("search_action") or "unknown").strip().lower()
    if search_action not in _ALLOWED_SEARCH_ACTIONS:
        search_action = "unknown"

    tool_candidates = _normalize_tools(data.get("tool_candidates"))
    preferred_after_tools = data.get("preferred_after_tools")
    normalized_after_tools = None
    if isinstance(preferred_after_tools, list):
        normalized_after_tools = _normalize_tools(preferred_after_tools)

    direct_pid = _normalize_pid(data.get("direct_pid"))
    index = _normalize_index(data.get("index"))
    reason = str(data.get("reason") or "").strip()[:240] or None
    route_to_luogu = bool(data.get("route_to_luogu"))

    if direct_pid:
        target = "direct_pid"
        route_to_luogu = True

    if intent == "replace" and search_action == "unknown":
        search_action = "random"
    if intent == "repeat_candidates" and search_action == "unknown":
        search_action = "repeat_candidates"
    if intent == "count" and search_action == "unknown":
        search_action = "count"
    if intent == "select" and search_action == "unknown":
        search_action = "select"
    if intent == "random" and search_action == "unknown":
        search_action = "random"
    if intent == "search" and search_action == "unknown":
        search_action = "search"

    if intent == "image" and not tool_candidates:
        tool_candidates = ["luogu_problem_image"]
    elif intent == "statement" and not tool_candidates:
        tool_candidates = ["luogu_problem_statement"]
    elif intent in {"search", "count", "select", "random", "replace", "repeat_candidates"} and not tool_candidates:
        tool_candidates = ["luogu_problem_search"]

    return LuoguSemanticDecision(
        route_to_luogu=route_to_luogu,
        confidence=confidence,
        intent=intent,
        target=target,
        direct_pid=direct_pid,
        index=index,
        image_mode=image_mode,
        search_action=search_action,
        tool_candidates=tool_candidates,
        preferred_after_tools=normalized_after_tools,
        reason=reason,
    )


def build_luogu_semantic_expert_prompt(
    *,
    user_text: str,
    matched_scope_terms: List[str],
    session_state: Optional[Mapping[str, Any]],
) -> str:
    matched_preview = "、".join(matched_scope_terms[:16]) if matched_scope_terms else "无明确命中"
    session_snapshot = _build_session_snapshot(session_state)
    return f"""你是 AstrBot 插件里的“洛谷语义分析专家”。
你的职责不是直接回答用户，而是把当前消息归一化成插件可执行的结构化决策。

只输出一个 JSON 对象，不要输出任何额外解释。

JSON 字段：
- route_to_luogu: true | false
- confidence: high | medium | low
- intent: search | count | select | random | replace | statement | image | repeat_candidates | clarify | reject | unknown
- target: fresh_lookup | current_candidates | current_selected | direct_pid | none
- direct_pid: "P1000" 或 null
- index: 正整数或 null
- image_mode: rendered | screenshot
- search_action: search | count | select | random | repeat_candidates | unknown
- tool_candidates: 工具数组，只能从 luogu_problem_search / luogu_problem_statement / luogu_problem_image 里选
- preferred_after_tools: 展示类后续工具数组；如果明确不要后续展示就输出 []
- reason: 一句中文理由

判定原则：
1. “来一道/找一道/推荐一道”这类单数选题请求，通常视为 route_to_luogu=true，intent=random，target=fresh_lookup，search_action=random，tool_candidates=["luogu_problem_search"]。
2. 已有候选或已聊到某道题时，“换一道/换一题/来个别的/再来一道”优先视为 intent=replace，target=current_candidates，search_action=random。
3. “第3题/来第一道/就这个”视为 select。
4. “总共有多少道”视为 count。
5. “看图/截图/图也来/图呢/来图/上图/发图”优先视为 image；若 session 有 current_pid，则 target=current_selected。
6. “题面/转发/完整题面”视为 statement。
7. 如果只是算法讨论、代码实现、题解讲解，不是选题流程，则 route_to_luogu=false。

注意：
- “换一道”不是闲聊，是洛谷 follow-up。
- 如果 session 中已有候选列表但没有 current_pid，依然可以把“换一道”“第3题”判定为 Luogu follow-up。
- 优先给出工具级决策，不要把责任推回主 LLM。

当前 session 摘要：{session_snapshot}
已命中的可能范围词：{matched_preview}
用户消息：{user_text}
"""


async def analyze_luogu_semantics(
    context: Any,
    event: Any,
    user_text: str,
    matched_scope_terms: List[str],
    session_state: Optional[Mapping[str, Any]],
    provider_id: Optional[str] = None,
) -> Optional[LuoguSemanticDecision]:
    if not context or not str(user_text or "").strip():
        return None

    if not provider_id:
        try:
            provider_id = await context.get_current_chat_provider_id(
                umo=event.unified_msg_origin
            )
        except Exception:
            return None

    if not provider_id:
        return None

    prompt = build_luogu_semantic_expert_prompt(
        user_text=user_text,
        matched_scope_terms=matched_scope_terms,
        session_state=session_state,
    )
    try:
        llm_resp = await context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
        )
    except Exception:
        return None

    raw_text = getattr(llm_resp, "completion_text", "") or ""
    data = _extract_json_object(raw_text)
    if not data:
        return None
    return _sanitize_semantic_decision(data)
