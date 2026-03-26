"""
自然语言跳题解析辅助模块。

目标不是直接执行模型输出，而是把自由表达约束成可验证的结构化意图，
再交给现有跳题状态机处理。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中抽取首个 JSON 对象。"""
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end < start:
        return None

    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _sanitize_intent(intent: Dict[str, Any]) -> Dict[str, Any]:
    """把模型输出收敛为受控字段。"""
    action = str(intent.get('action') or 'unknown').strip().lower()
    if action not in {
        'search', 'random', 'select', 'show_image',
        'back', 'restart', 'quit', 'help', 'unknown',
    }:
        action = 'unknown'

    difficulty = intent.get('difficulty')
    if isinstance(difficulty, bool):
        difficulty = None
    elif difficulty is not None:
        try:
            difficulty = int(difficulty)
        except Exception:
            difficulty = None
    if difficulty is not None and not (0 <= difficulty <= 8):
        difficulty = None

    index = intent.get('index')
    if isinstance(index, bool):
        index = None
    elif index is not None:
        try:
            index = int(index)
        except Exception:
            index = None
    if index is not None and index <= 0:
        index = None

    tags = intent.get('tags') or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag).strip() for tag in tags if str(tag).strip()][:8]

    keyword = str(intent.get('keyword') or '').strip() or None
    clarification = str(intent.get('clarification') or '').strip() or None
    reply = str(intent.get('reply') or '').strip() or None
    need_clarification = bool(intent.get('need_clarification'))

    return {
        'action': action,
        'difficulty': difficulty,
        'tags': tags,
        'keyword': keyword,
        'index': index,
        'need_clarification': need_clarification,
        'clarification': clarification,
        'reply': reply,
    }


def build_jump_parse_prompt(user_text: str, hot_tags: List[str]) -> str:
    """构造自然语言跳题解析提示词。"""
    tags_preview = '、'.join(hot_tags[:80])
    return f"""你是洛谷题库跳题助手的意图解析器。你的任务是把用户的话解析为 JSON。

只输出一个 JSON 对象，不要输出任何额外解释。

字段定义：
- action: search | random | select | show_image | back | restart | quit | help | unknown
- difficulty: 0-8 或 null
  - 0 = 不限
  - 1 = 暂无评定
  - 2 = 入门
  - 3 = 普及−
  - 4 = 普及/提高−
  - 5 = 普及+/提高
  - 6 = 提高+/省选−
  - 7 = 省选/NOI−
  - 8 = NOI/NOI+/CTSC
- tags: 标签列表，尽量保留用户原意，最多 8 个
- keyword: 题目关键词，没有则为 null
- index: 如果用户明确要“第 N 题”，填正整数，否则 null
- need_clarification: true/false
- clarification: 如果信息不足，需要向用户追问的一句话，否则 null
- reply: 一句简短确认语，可为空

规则：
1. 如果用户想“随机来一道”，action = random。
2. 如果用户想看当前题面的图片，action = show_image。
3. 如果用户要返回上一步，action = back；如果要从头开始，action = restart。
4. 如果用户只是表达筛题条件，action = search。
5. 只有当用户明确说“第 3 题”“第3道”这类时，action = select 且填写 index。
6. 不要编造标签；可参考这些常见标签：{tags_preview}
7. 如果请求模糊到无法安全执行，need_clarification = true。

用户输入：
{user_text}
"""


async def parse_jump_natural_language(
    context: Any,
    event: Any,
    user_text: str,
    hot_tags: List[str],
) -> Optional[Dict[str, Any]]:
    """调用 AstrBot 当前会话模型，把自然语言解析为跳题意图。"""
    if not context or not user_text.strip():
        return None

    try:
        provider_id = await context.get_current_chat_provider_id(
            umo=event.unified_msg_origin
        )
    except Exception:
        return None

    if not provider_id:
        return None

    prompt = build_jump_parse_prompt(user_text, hot_tags)
    try:
        llm_resp = await context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
        )
    except Exception:
        return None

    raw_text = getattr(llm_resp, 'completion_text', '') or ''
    data = _extract_json_object(raw_text)
    if not data:
        return None
    return _sanitize_intent(data)
