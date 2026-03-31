from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from .intent_parser import parse_luogu_workflow_intent
from .planner import LuoguWorkflowPlan, plan_luogu_workflow
from .problem_lookup import extract_problem_id
from .request_count import clamp_luogu_request_count, parse_luogu_requested_count, parse_simple_chinese_number
from .session_events import replay_luogu_session_state
from .tags import ALL_TAGS

LUOGU_TOOL_POLICY_HINT_MARKER = "[LUOGU_TOOL_POLICY]"

_PROBLEM_DEMAND_MARKERS = (
    "来一题", "来一道", "来几题", "找一题", "找几题", "选题", "挑题",
    "推荐题", "推荐几题", "随机来一题", "随机来一道", "出一题", "给我一道",
    "搜题", "搜一个", "查题", "题目", "跳一题", "跳一道", "跳题",
    "整一题", "整一道", "做一题", "做一道",
)

_SCOPE_MARKERS = (
    "洛谷", "luogu", "题库", "后缀自动机", "字典树", "trie", "sam", "图论",
    "动态规划", "dp", "字符串", "数学", "icpc", "noi", "省选", "模板题",
    "线段树", "树状数组", "并查集", "最短路", "二分", "生成树", "最小生成树",
    "次小生成树", "网络流", "蓝题", "紫题", "绿题", "黄题", "橙题", "红题", "黑题",
)

_CLASSIFIER_HINT_MARKERS = (
    "题", "算法", "数据结构", "竞赛", "oi", "省选", "noi", "ioi", "csp", "icpc",
    "难度", "标签", "来源", "年份", "地区", "颜色", "蓝题", "紫题", "绿题",
    "黄题", "橙题", "红题", "黑题",
)

_FOLLOW_UP_MARKERS = (
    "多少道", "总共", "一共有", "总数", "随机", "random", "随便来一题", "随便来一道",
    "再来一道", "再来一题", "第", "这道题", "题面", "转发", "合并消息",
    "完整题面", "看图", "截图", "题图", "图片", "关键词", "标签", "来源", "难度",
    "候选", "列表", "重发", "再发", "没看到", "不是说了", "怎么又把",
)

_RANDOM_MARKERS = (
    "随便来一题", "随便来一道", "随机来一题", "随机来一道",
    "随机挑一题", "随机挑一道", "随便挑一题", "随便挑一道",
    "再来一道", "再来一题",
)

_STATEMENT_MARKERS = ("题面", "转发", "合并消息", "完整题面", "markdown", "原文")
_IMAGE_MARKERS = ("看图", "题图", "图片", "图片发出来", "题目图片", "发题图", "图也来", "图呢", "来图", "上图", "发图")
_CLARIFICATION_MARKERS = (
    "是的", "不是", "对", "对的", "没错", "确认", "就这个",
    "难度", "标签", "来源", "蓝题", "紫题", "绿题", "黄题", "橙题", "红题", "黑题",
)


def _compact_lookup_text(text: str) -> str:
    return "".join(ch.lower() for ch in str(text or "") if ch.isalnum())


def parse_luogu_follow_up_index(query: str) -> Optional[int]:
    text = str(query or "").strip()
    if not text:
        return None
    digit_match = re.search(r"第\s*(\d+)\s*[题道个]?", text)
    if digit_match:
        return int(digit_match.group(1))
    chinese_match = re.search(r"第\s*([零一二两三四五六七八九十百千]+)\s*[题道个]?", text)
    if chinese_match:
        return parse_simple_chinese_number(chinese_match.group(1))
    return None


def has_luogu_problem_demand(text: str) -> bool:
    return any(marker in text for marker in _PROBLEM_DEMAND_MARKERS)


def collect_luogu_scope_hits(text: str) -> list[str]:
    lowered = str(text or "").strip().lower()
    compact = _compact_lookup_text(lowered)
    hits: list[str] = []
    seen = set()

    def remember(raw: str) -> None:
        item = str(raw).strip()
        if not item or item in seen:
            return
        seen.add(item)
        hits.append(item)

    for marker in _SCOPE_MARKERS:
        if marker in lowered:
            remember(marker)

    for tag in ALL_TAGS:
        tag_text = str(tag).strip().lower()
        if len(tag_text) < 2:
            continue
        tag_compact = _compact_lookup_text(tag_text)
        if tag_text in lowered or (tag_compact and tag_compact in compact):
            remember(tag)
            if len(hits) >= 24:
                break

    return hits


def should_consult_luogu_intent_classifier(message: str, scope_hits: list[str]) -> bool:
    text = (message or "").strip().lower()
    if not text or text.startswith("/luogu"):
        return False
    has_problemish_hint = any(marker in text for marker in _CLASSIFIER_HINT_MARKERS)
    return has_luogu_problem_demand(text) and (bool(scope_hits) or has_problemish_hint)


def should_nudge_luogu_problem_tool(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text or text.startswith("/luogu"):
        return False

    has_scope = bool(collect_luogu_scope_hits(text))
    has_demand = has_luogu_problem_demand(text)
    if extract_problem_id(text):
        return True
    return has_scope and (
        has_demand
        or ("题" in text and any(ch in text for ch in ("来", "找", "推", "选", "查", "搜", "跳", "做", "整")))
    )


def looks_like_luogu_follow_up(message: str, session_data: Optional[Mapping[str, Any]]) -> bool:
    if not session_data:
        return False
    text = (message or "").strip().lower()
    if not text or text.startswith("/luogu"):
        return False
    return any(marker in text for marker in _FOLLOW_UP_MARKERS)


def message_requests_random_problem(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return (
        text == "random"
        or any(marker in text for marker in _RANDOM_MARKERS)
        or ("随机" in text and any(marker in text for marker in ("一题", "一道", "挑", "来")))
    )


def message_requests_problem_statement(message: str) -> bool:
    text = str(message or "").strip()
    return any(marker in text for marker in _STATEMENT_MARKERS)


def message_requests_problem_image(message: str) -> bool:
    text = str(message or "").strip()
    return "截图" in text or any(marker in text for marker in _IMAGE_MARKERS)


def interpret_luogu_follow_up(query: str, session_data: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not session_data:
        return None
    text = (query or "").strip()
    if not text:
        return None
    lower = text.lower()

    if any(marker in text for marker in ("总共有多少", "一共有多少", "总数", "多少道")):
        return {"kind": "count"}

    follow_up_index = parse_luogu_follow_up_index(text)
    if follow_up_index:
        return {"kind": "select", "index": follow_up_index}

    if (
        lower == "random"
        or any(marker in text for marker in _RANDOM_MARKERS)
        or ("随机" in text and any(marker in text for marker in ("一题", "一道", "挑", "来")))
    ):
        return {"kind": "random"}

    if "截图" in text:
        return {"kind": "image", "mode": "screenshot"}
    if any(marker in text for marker in _IMAGE_MARKERS):
        return {"kind": "image", "mode": "rendered"}

    if any(marker in text for marker in _STATEMENT_MARKERS[:-1]):
        return {"kind": "forward"}

    if any(marker in text for marker in ("候选", "列表", "重发", "再发", "没看到", "再给我看")):
        return {"kind": "repeat_candidates"}

    return None


def looks_like_luogu_clarification_reply(message: str, session_data: Optional[Mapping[str, Any]]) -> bool:
    if not session_data or not session_data.get("pending_clarification"):
        return False
    text = str(message or "").strip()
    if not text or text.startswith("/luogu"):
        return False
    if len(text) <= 40:
        return True
    return any(marker in text for marker in _CLARIFICATION_MARKERS)


def consume_luogu_pending_clarification(
    query: str,
    session_data: Optional[Mapping[str, Any]],
) -> tuple[str, Dict[str, Any], bool]:
    session = dict(session_data or {})
    pending = session.get("pending_clarification") or {}
    if not pending or not looks_like_luogu_clarification_reply(query, session):
        return query, session, False

    original_query = str(pending.get("original_query") or "").strip()
    merged_query = str(query or "").strip()
    if original_query and merged_query != original_query:
        merged_query = f"{original_query}\n补充说明：{merged_query}"
    session.pop("pending_clarification", None)
    return merged_query, session, True


def message_has_quoted_image_context(event: Any) -> bool:
    root = getattr(event, "message_obj", None)
    if root is None:
        return False

    queue: list[tuple[Any, int]] = [(root, 0)]
    seen: set[int] = set()
    found_quote = False
    found_image = False
    attr_names = ("message", "chain", "components", "quote", "reply", "origin", "source", "content")

    while queue:
        current, depth = queue.pop(0)
        if current is None:
            continue
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)

        type_name = current.__class__.__name__.lower()
        try:
            text = repr(current)
        except Exception:
            text = ""
        lower = text.lower()
        if any(marker in lower for marker in ("quote", "reply")) or "引用" in text:
            found_quote = True
        if "image_url" in lower or "图片" in text or type_name == "image" or type_name.endswith("image"):
            found_image = True
        if found_quote and found_image:
            return True

        if depth >= 2:
            continue
        if isinstance(current, dict):
            for value in current.values():
                queue.append((value, depth + 1))
            continue
        if isinstance(current, (list, tuple, set)):
            for value in current:
                queue.append((value, depth + 1))
            continue
        for attr in attr_names:
            if hasattr(current, attr):
                try:
                    value = getattr(current, attr)
                except Exception:
                    continue
                queue.append((value, depth + 1))
    return False


def _is_quoted_image_content_part(part: Any) -> bool:
    if part is None:
        return False
    if isinstance(part, dict):
        part_type = str(part.get("type") or part.get("kind") or "").strip().lower()
        if part_type in {"image", "image_url", "input_image"}:
            return True
        return "image_url" in part or "image" in part

    type_name = part.__class__.__name__.lower()
    if type_name == "image" or type_name.endswith("image") or type_name.endswith("imagepart"):
        return True
    if hasattr(part, "image_url"):
        return True
    try:
        return "image_url" in repr(part).lower()
    except Exception:
        return False


def _replace_request_context_content(context_item: Any, content: Any) -> Any:
    if isinstance(context_item, dict):
        updated = dict(context_item)
        updated["content"] = content
        return updated
    model_copy = getattr(context_item, "model_copy", None)
    if callable(model_copy):
        try:
            return model_copy(update={"content": content})
        except Exception:
            pass
    copy_method = getattr(context_item, "copy", None)
    if callable(copy_method):
        try:
            return copy_method(update={"content": content})
        except Exception:
            pass
    try:
        setattr(context_item, "content", content)
    except Exception:
        pass
    return context_item


def sanitize_quoted_image_request(req: Any) -> int:
    removed_parts = 0

    image_urls = getattr(req, "image_urls", None)
    if isinstance(image_urls, list) and image_urls:
        removed_parts += len(image_urls)
        try:
            req.image_urls = []
        except Exception:
            image_urls.clear()

    contexts = getattr(req, "contexts", None)
    if not isinstance(contexts, list):
        return removed_parts

    sanitized_contexts: list[Any] = []
    for context_item in contexts:
        content = context_item.get("content") if isinstance(context_item, dict) else getattr(context_item, "content", None)

        if isinstance(content, list):
            sanitized_content = [part for part in content if not _is_quoted_image_content_part(part)]
            removed_parts += len(content) - len(sanitized_content)
            if not sanitized_content:
                continue
            sanitized_contexts.append(_replace_request_context_content(context_item, sanitized_content))
            continue

        if _is_quoted_image_content_part(content):
            removed_parts += 1
            continue

        sanitized_contexts.append(context_item)

    try:
        req.contexts = sanitized_contexts
    except Exception:
        contexts[:] = sanitized_contexts
    return removed_parts


@dataclass(slots=True)
class LuoguToolPolicy:
    follow_up: Optional[Dict[str, Any]]
    direct_pid: Optional[str]
    requests_statement: bool
    requests_image: bool
    requests_random: bool
    requested_count: int
    workflow_session: Dict[str, Any]
    workflow_plan: Optional[LuoguWorkflowPlan]
    tool_names: list[str]
    sequence_hint: str


@dataclass(slots=True)
class LuoguLLMRequestPlan:
    policy: LuoguToolPolicy
    scope_hits: list[str]
    classifier_decision: Optional[Dict[str, Any]]
    classifier_routed: bool
    quoted_image_context: bool
    system_prompt_hint: str
    extra_user_instruction: str


def build_luogu_tool_policy(
    *,
    message: str,
    session_data: Optional[Mapping[str, Any]],
) -> LuoguToolPolicy:
    follow_up = interpret_luogu_follow_up(message, session_data)
    direct_pid = extract_problem_id(message)
    requests_statement = message_requests_problem_statement(message)
    requests_image = message_requests_problem_image(message)
    requests_random = message_requests_random_problem(message)
    requested_count = clamp_luogu_request_count(
        parse_luogu_requested_count(message) or (session_data or {}).get("requested_count")
    )
    workflow_session = replay_luogu_session_state(
        list((session_data or {}).get("events") or []),
        fallback=dict(session_data or {}),
    )
    workflow_intent = parse_luogu_workflow_intent(
        message=message,
        session_state=workflow_session,
        follow_up=follow_up,
        direct_pid=direct_pid,
        requests_statement=requests_statement,
        requests_image=requests_image,
        requests_random=requests_random,
        requested_count=requested_count,
    )
    workflow_plan = plan_luogu_workflow(workflow_intent, workflow_session)
    if workflow_plan:
        tool_names = workflow_plan.allowed_tools
        sequence_hint = workflow_plan.sequence_hint
    else:
        tool_names = ["luogu_problem_search"]
        sequence_hint = (
            "This is still a candidate-search stage. Only call `luogu_problem_search` first. "
            "If the result is only a candidate list, total count, or filter explanation, do not call "
            "`luogu_problem_statement` or `luogu_problem_image` until a concrete problem is selected."
        )

    return LuoguToolPolicy(
        follow_up=follow_up,
        direct_pid=direct_pid,
        requests_statement=requests_statement,
        requests_image=requests_image,
        requests_random=requests_random,
        requested_count=requested_count,
        workflow_session=workflow_session,
        workflow_plan=workflow_plan,
        tool_names=tool_names,
        sequence_hint=sequence_hint,
    )


def build_luogu_system_prompt_hint(
    *,
    session_snapshot: str,
    tool_names: list[str],
    sequence_hint: str,
    quoted_image_context: bool,
) -> str:
    tool_usage = (
        "\n工具职责："
        "\n- `luogu_problem_search(query, limit=10)`：只负责筛题、续筛、追问总数、随机/指定选题，并把结果写回当前 Luogu session。"
        "\n- `luogu_problem_statement(pid=None)`：只负责按题号发送题面；pid 省略时读取当前 Luogu session 的 `current_pid`。"
        "\n- `luogu_problem_image(pid=None, mode=\"rendered\")`：只负责按题号发送题图；用户明确要求官网截图时传 `mode=\"screenshot\"`。"
    )
    hint = (
        f"\n{LUOGU_TOOL_POLICY_HINT_MARKER}"
        "\n当前这条用户消息属于洛谷题库选题/题面展示请求。"
        f"\n当前 Luogu session 摘要：\n{session_snapshot}"
        f"{tool_usage}"
        f"\n当前请求允许使用的工具：{', '.join(tool_names)}。"
        "\n禁止先调用 `web_search`、`fetch_url`、`astrbot_execute_shell`、`astrbot_execute_python` 这类外部搜索工具。"
        "\n禁止在第一次工具调用前先输出任何自然语言过渡句，例如“我来帮你找一下”“稍等我查一下”。"
        f"\n流程要求：{sequence_hint}"
        "\n如果当前 session 已经有 `current_pid`，就说明用户已经选中过一道题。之后的“题面/看图/截图”请求应该直接使用对应展示工具，而不是重新筛题。"
    )
    if quoted_image_context:
        hint += (
            "\n如果用户这次是在引用带图片的消息继续追问，请在完成必要工具调用后，用一句简短提醒补充说明："
            "当前模型可能无法读取引用里的图片内容；如果结果不对，请去掉图片引用，直接用纯文本重发需求。"
        )
    return hint


def build_luogu_extra_user_instruction(
    *,
    tool_names: list[str],
    quoted_image_context: bool,
) -> str:
    text = (
        "附加指令：这是一条洛谷专用流程请求。"
        f"当前允许工具只有：{', '.join(tool_names)}。"
        "不要先使用网页搜索、抓取网页、执行 shell 或执行 Python。"
        "在第一次工具调用前不要先发任何自然语言说明。"
        "如果已经选中过题，就沿用当前 Luogu session，不要丢失上下文。"
    )
    if quoted_image_context:
        text += (
            "若用户是在引用图片追问，请在完成工具调用后提醒：当前模型可能读不到引用图片内容，必要时请用户去掉引用后重发文本。"
        )
    return text


async def plan_luogu_llm_request(
    *,
    context: Any,
    event: Any,
    message: str,
    session_data: Optional[Mapping[str, Any]],
    session_snapshot: str,
    classify_intent,
) -> Optional[LuoguLLMRequestPlan]:
    should_force_luogu = (
        should_nudge_luogu_problem_tool(message)
        or looks_like_luogu_follow_up(message, session_data)
        or looks_like_luogu_clarification_reply(message, session_data)
    )
    scope_hits = collect_luogu_scope_hits(message)
    classifier_decision = None
    classifier_routed = False
    if not should_force_luogu and should_consult_luogu_intent_classifier(message, scope_hits):
        classifier_decision = await classify_intent(
            context,
            event,
            message,
            scope_hits,
        )
        if classifier_decision and classifier_decision.get("route_to_luogu"):
            should_force_luogu = True
            classifier_routed = True
    if not should_force_luogu:
        return None

    policy = build_luogu_tool_policy(message=message, session_data=session_data)
    quoted_image_context = message_has_quoted_image_context(event)
    return LuoguLLMRequestPlan(
        policy=policy,
        scope_hits=scope_hits,
        classifier_decision=classifier_decision,
        classifier_routed=classifier_routed,
        quoted_image_context=quoted_image_context,
        system_prompt_hint=build_luogu_system_prompt_hint(
            session_snapshot=session_snapshot,
            tool_names=policy.tool_names,
            sequence_hint=policy.sequence_hint,
            quoted_image_context=quoted_image_context,
        ),
        extra_user_instruction=build_luogu_extra_user_instruction(
            tool_names=policy.tool_names,
            quoted_image_context=quoted_image_context,
        ),
    )


def apply_luogu_request_prompt(
    req: Any,
    *,
    request_plan: LuoguLLMRequestPlan,
    text_part_cls: Any,
) -> int:
    removed_parts = 0
    if request_plan.quoted_image_context:
        removed_parts = sanitize_quoted_image_request(req)

    current_prompt = getattr(req, "system_prompt", "") or ""
    if LUOGU_TOOL_POLICY_HINT_MARKER not in current_prompt:
        req.system_prompt = current_prompt + request_plan.system_prompt_hint
    req.extra_user_content_parts.append(
        text_part_cls(text=request_plan.extra_user_instruction)
    )
    return removed_parts


def enforce_luogu_request(
    *,
    context: Any,
    tool_manager: Any,
    req: Any,
    request_plan: LuoguLLMRequestPlan,
    text_part_cls: Any,
    toolset_cls: Any,
) -> int:
    tools = []
    for name in request_plan.policy.tool_names:
        context.activate_llm_tool(name)
        tool = tool_manager.get_func(name)
        if tool is not None:
            tools.append(tool)
    if tools:
        req.func_tool = toolset_cls(tools)
    return apply_luogu_request_prompt(
        req,
        request_plan=request_plan,
        text_part_cls=text_part_cls,
    )
