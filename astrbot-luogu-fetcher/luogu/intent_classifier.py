from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


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


def _sanitize_route_decision(data: Dict[str, Any]) -> Dict[str, Any]:
    confidence = str(data.get("confidence") or "low").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    reason = str(data.get("reason") or "").strip()[:200]
    return {
        "route_to_luogu": bool(data.get("route_to_luogu")),
        "confidence": confidence,
        "reason": reason or None,
    }


def build_luogu_route_classifier_prompt(user_text: str, matched_scope_terms: List[str]) -> str:
    matched_preview = "、".join(matched_scope_terms[:16]) if matched_scope_terms else "无明确命中"
    return f"""你是 AstrBot 插件里的“洛谷选题路由分类器”。
你的任务只有一个：判断当前用户消息是否应该强制路由到 `luogu_problem_search` 工具。

只输出一个 JSON 对象，不要输出任何额外解释。
JSON 字段定义：
- route_to_luogu: true | false
- confidence: high | medium | low
- reason: 一句简短中文理由

判定为 true 的典型情况：
1. 用户想找题、选题、推荐题、随机来一道题、按标签/难度/来源/年份/地区筛题。
2. 用户提到洛谷、题库，或明显在说 OI/算法竞赛题目需求。
3. 用户提到算法标签、来源标签、地区标签、年份标签、难度颜色（蓝题/紫题/黑题）并带有选题动作。

判定为 false 的典型情况：
1. 用户是在问算法知识、代码实现、题解、调试，不是在选题。
2. 用户只是在闲聊颜色、背景、界面，不是在找题。
3. 用户要求模拟搜索、网页搜索、执行 shell/python，而不是进入洛谷选题流程。

注意：
- 这是“是否进入洛谷选题流程”的二分类，不是解析具体标签。
- 如果语气口语化，但本质是在要一道 OI/算法题，仍应判定为 true。

已命中的可能洛谷标签/难度/题型词：{matched_preview}
用户消息：{user_text}
"""


async def classify_luogu_routing_intent(
    context: Any,
    event: Any,
    user_text: str,
    matched_scope_terms: List[str],
) -> Optional[Dict[str, Any]]:
    if not context or not str(user_text or "").strip():
        return None

    try:
        provider_id = await context.get_current_chat_provider_id(
            umo=event.unified_msg_origin
        )
    except Exception:
        return None

    if not provider_id:
        return None

    prompt = build_luogu_route_classifier_prompt(user_text, matched_scope_terms)
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
    return _sanitize_route_decision(data)
