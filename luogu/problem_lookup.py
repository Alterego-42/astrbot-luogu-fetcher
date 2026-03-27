from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from luogu.problem_fetcher import ProblemFetcher
from luogu.tags import DIFFICULTY_NAMES, fuzzy_match_tag

_PROBLEM_ID_PREFIX_RE = re.compile(r"\b[Pp]\s*(\d{4,})\b")
_PROBLEM_ID_CONTEXT_RE = re.compile(
    r"(?:题号|题目|洛谷题|洛谷题号|problem)\s*(?:是|为|[:：#])?\s*([Pp]?\d{4,})\b",
    re.IGNORECASE,
)

_FOLLOW_UP_ADD_MARKERS = tuple(
    "".join(ch for ch in marker.lower() if ch.isalnum())
    for marker in (
        "再加",
        "加个",
        "加上",
        "补个",
        "补上",
        "追加",
        "带上",
        "也要",
        "还要",
    )
)
_FOLLOW_UP_REMOVE_MARKERS = tuple(
    "".join(ch for ch in marker.lower() if ch.isalnum())
    for marker in (
        "去掉",
        "不要",
        "删掉",
        "删除",
        "移除",
        "去除",
    )
)
_FOLLOW_UP_REPLACE_MARKERS = tuple(
    "".join(ch for ch in marker.lower() if ch.isalnum())
    for marker in (
        "换成",
        "改成",
        "改为",
        "变成",
    )
)


def _run_problem_sync(cookies_file: str, task_fn, **kwargs) -> Any:
    """在线程中运行 ProblemFetcher 任务。"""
    with ProblemFetcher(cookies_file) as fetcher:
        return task_fn(fetcher, **kwargs)


async def run_problem_async(cookies_file: str, task_fn, **kwargs) -> Any:
    """异步包装：在线程池中运行 ProblemFetcher 任务。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _run_problem_sync(cookies_file, task_fn, **kwargs)
    )


def normalize_problem_lookup_tags(tags: Any) -> Tuple[List[str], List[str]]:
    normalized: List[str] = []
    unresolved: List[str] = []
    seen_normalized = set()
    seen_unresolved = set()
    for raw in tags or []:
        tag_name = str(raw).strip()
        if not tag_name:
            continue
        matched = fuzzy_match_tag(tag_name)
        if matched:
            candidate = matched[0]
            if candidate not in seen_normalized:
                normalized.append(candidate)
                seen_normalized.add(candidate)
            continue
        if tag_name not in seen_unresolved:
            unresolved.append(tag_name)
            seen_unresolved.add(tag_name)
    return normalized, unresolved


def _dedupe_strings(values: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for raw in values:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _compact_text(text: str) -> str:
    return "".join(ch.lower() for ch in str(text or "") if ch.isalnum())


def _contains_marker(text: str, markers: Tuple[str, ...]) -> bool:
    compact = _compact_text(text)
    return any(marker in compact for marker in markers)


def _resolve_session_tags_for_removal(query: str, session_tags: List[str]) -> List[str]:
    raw = str(query or "").strip()
    compact = _compact_text(raw)
    matched: List[str] = []
    for tag in session_tags:
        tag_text = str(tag).strip()
        if not tag_text:
            continue
        tag_compact = _compact_text(tag_text)
        if tag_text in raw or (tag_compact and tag_compact in compact) or (compact and compact in tag_compact):
            matched.append(tag_text)
    return _dedupe_strings(matched)


def should_merge_luogu_lookup_context(query: str) -> bool:
    raw = str(query or "").strip()
    if not raw:
        return False
    if raw.startswith(("+", "-")):
        return True
    compact = _compact_text(raw)
    if any(marker in compact for marker in _FOLLOW_UP_ADD_MARKERS + _FOLLOW_UP_REMOVE_MARKERS + _FOLLOW_UP_REPLACE_MARKERS):
        return True
    merge_markers = (
        "标签",
        "关键词",
        "关键字",
        "难度",
        "来源",
        "范围",
        "筛一下",
        "缩小",
        "收窄",
        "限制",
        "不限难度",
        "难度不限",
        "不限制难度",
        "任意难度",
    )
    return any(marker in raw for marker in merge_markers)


def merge_luogu_lookup_context(
    session: Optional[Dict[str, Any]],
    *,
    query: str,
    action: str,
    difficulty: Optional[int],
    tags: List[str],
    keyword: Optional[str],
    unresolved_tags: List[str],
) -> Dict[str, Any]:
    current = {
        "action": action,
        "difficulty": difficulty,
        "tags": _dedupe_strings(tags or []),
        "keyword": str(keyword).strip() if keyword else None,
        "unresolved_tags": _dedupe_strings(unresolved_tags or []),
        "merged": False,
    }
    if query.strip().startswith(("+", "-")) and not current["tags"] and not current["unresolved_tags"]:
        explicit_tag = query.strip()[1:].strip()
        current["tags"], current["unresolved_tags"] = normalize_problem_lookup_tags([explicit_tag])
    if not session or action not in ("search", "") or not should_merge_luogu_lookup_context(query):
        return current

    text = str(query or "").strip()
    compact = _compact_text(text)
    add_mode = text.startswith("+") or _contains_marker(text, _FOLLOW_UP_ADD_MARKERS)
    remove_mode = text.startswith("-") or _contains_marker(text, _FOLLOW_UP_REMOVE_MARKERS)
    replace_mode = _contains_marker(text, _FOLLOW_UP_REPLACE_MARKERS)
    mentions_tags = any(marker in text for marker in ("标签", "来源")) or text.startswith(("+", "-"))
    mentions_keyword = any(marker in text for marker in ("关键词", "关键字"))
    clear_tags = any(marker in compact for marker in ("清空标签", "删除标签", "去掉标签", "不要标签", "清空来源标签"))
    clear_keyword = any(marker in compact for marker in ("清空关键词", "清空关键字", "删除关键词", "删除关键字", "去掉关键词", "去掉关键字", "不要关键词", "不要关键字"))
    reset_difficulty = any(marker in compact for marker in ("不限难度", "难度不限", "不限制难度", "任意难度"))

    merged_tags = _dedupe_strings(list(session.get("tags") or []))
    merged_unresolved = _dedupe_strings(list(session.get("unresolved_tags") or []))
    merged_keyword = str(session.get("keyword") or "").strip() or None
    merged_difficulty = session.get("difficulty")

    if reset_difficulty:
        merged_difficulty = None
    elif difficulty is not None:
        merged_difficulty = difficulty

    if clear_tags:
        merged_tags = []
        merged_unresolved = []

    if clear_keyword:
        merged_keyword = None

    if current["tags"] or current["unresolved_tags"]:
        if remove_mode:
            to_remove = set(current["tags"])
            to_remove.update(_resolve_session_tags_for_removal(text, merged_tags))
            merged_tags = [tag for tag in merged_tags if tag not in to_remove]
            unresolved_to_remove = set(current["unresolved_tags"])
            merged_unresolved = [tag for tag in merged_unresolved if tag not in unresolved_to_remove]
        elif replace_mode and mentions_tags:
            merged_tags = current["tags"]
            merged_unresolved = current["unresolved_tags"]
        else:
            merged_tags = _dedupe_strings(merged_tags + current["tags"])
            merged_unresolved = _dedupe_strings(merged_unresolved + current["unresolved_tags"])

    if mentions_keyword and not current["keyword"] and remove_mode:
        merged_keyword = None
    elif current["keyword"]:
        if remove_mode and mentions_keyword:
            merged_keyword = None
        elif replace_mode or (mentions_keyword and not add_mode):
            merged_keyword = current["keyword"]
        elif add_mode and merged_keyword:
            merged_keyword = " ".join(_dedupe_strings([merged_keyword, current["keyword"]])).strip() or None
        else:
            merged_keyword = current["keyword"]

    return {
        "action": "search",
        "difficulty": merged_difficulty,
        "tags": merged_tags,
        "keyword": merged_keyword,
        "unresolved_tags": merged_unresolved,
        "merged": True,
    }


def extract_problem_id(text: str) -> Optional[str]:
    content = str(text or "").strip()
    if not content:
        return None

    for pattern in (_PROBLEM_ID_PREFIX_RE, _PROBLEM_ID_CONTEXT_RE):
        match = pattern.search(content)
        if not match:
            continue
        raw = match.group(1).replace(" ", "").upper()
        return raw if raw.startswith("P") else f"P{raw}"

    return None


def _format_lookup_conditions(difficulty: Optional[int], tags: List[str], keyword: Optional[str]) -> str:
    parts: List[str] = []
    if difficulty is not None:
        if difficulty == 0:
            parts.append('难度：不限')
        elif 1 <= difficulty <= len(DIFFICULTY_NAMES):
            parts.append(f'难度：{DIFFICULTY_NAMES[difficulty - 1]}')
    if tags:
        parts.append('标签：' + '、'.join(tags))
    if keyword:
        parts.append(f'关键词：{keyword}')
    return '；'.join(parts) if parts else '未指定筛选条件'


def preflight_luogu_problem_tool_action(
    action: str,
    *,
    index: Optional[int],
    difficulty: Optional[int],
    tags: List[str],
    keyword: Optional[str],
) -> Optional[str]:
    if action == 'unknown':
        return "这个工具只处理洛谷选题需求。请直接描述想要的题目条件，例如“来一道提高组图论题”。"
    if action in ('show_image', 'show_screenshot', 'back', 'restart', 'quit'):
        return "这个工具只负责在普通聊天里检索或挑题；看图、截图和多轮回退请改用 /luogu jump。"
    if action == 'help':
        return "你可以把选题需求直接交给这个工具，例如“来一道 ICPC 图论题”或“找几道 O2 优化题”。"
    if action == 'select' and not index:
        return "如果你想指定第几题，请明确说“第 3 题”这类序号。"
    if action == 'select' and not (difficulty is not None or tags or keyword):
        return "这个工具不会记住上一轮候选列表；如果你想指定序号，请把筛选条件一起说出来，或改用 /luogu jump。"
    return None


def lookup_luogu_problem_by_pid(
    fetcher: ProblemFetcher,
    *,
    pid: str,
) -> Dict[str, Any]:
    detail = fetcher.get_problem_detail(pid)
    normalized_pid = str(detail.get('pid') or pid).strip().upper()
    if not normalized_pid.startswith('P'):
        normalized_pid = f'P{normalized_pid}'
    return {
        'success': True,
        'total': 1,
        'chosen': {
            'index': 1,
            'pid': normalized_pid,
            'title': detail.get('title') or normalized_pid,
            'difficulty_name': detail.get('difficulty_name') or '',
            'tags': detail.get('tags') or [],
            'url': detail.get('url') or f'https://www.luogu.com.cn/problem/{normalized_pid}',
        },
        'summaries': [],
        'list_url': f'https://www.luogu.com.cn/problem/{normalized_pid}',
        'applied_tags': [],
        'missing_tags': [],
    }


def lookup_luogu_problems(
    fetcher: ProblemFetcher,
    *,
    difficulty: Optional[int],
    tags: List[str],
    keyword: Optional[str],
    limit: int,
    action: str,
    index: Optional[int],
) -> Dict[str, Any]:
    user_diff = difficulty
    url_difficulty = (user_diff - 1) if user_diff is not None else None
    result = fetcher.apply_filters(
        difficulty=url_difficulty,
        tags=tags or None,
        keyword=keyword or None,
    )
    if not result.get('success'):
        return {
            'success': False,
            'message': result.get('message', '筛选失败'),
        }

    summaries = fetcher.extract_problem_summaries(limit=limit)
    payload: Dict[str, Any] = {
        'success': True,
        'total': result.get('total', 0),
        'list_url': result.get('list_url'),
        'applied_tags': result.get('applied_tags') or tags,
        'missing_tags': result.get('missing_tags') or [],
        'summaries': summaries,
    }

    if payload['total'] <= 0:
        return payload

    if action in ('random', 'select'):
        if action == 'random':
            import random as _rand
            chosen_index = _rand.randint(1, payload['total'])
        else:
            chosen_index = index or 1

        chosen_index = max(1, min(chosen_index, payload['total']))
        pid = fetcher.navigate_to_problem(chosen_index, list_url=result.get('list_url'))
        if pid:
            detail = fetcher.get_problem_detail(pid)
            payload['chosen'] = {
                'index': chosen_index,
                'pid': pid,
                'title': detail.get('title') or pid,
                'difficulty_name': detail.get('difficulty_name') or '',
                'tags': detail.get('tags') or [],
                'url': detail.get('url') or f'https://www.luogu.com.cn/problem/{pid}',
            }
    return payload


def format_luogu_problem_tool_result(
    query: str,
    action: str,
    difficulty: Optional[int],
    tags: List[str],
    keyword: Optional[str],
    unresolved_tags: List[str],
    payload: Dict[str, Any],
) -> str:
    if not payload.get('success'):
        return '洛谷选题失败：' + str(payload.get('message') or '未知错误')

    lines = [
        f'查询：{query}',
        '筛选：' + _format_lookup_conditions(difficulty, tags, keyword),
    ]
    if unresolved_tags:
        lines.append('未命中官方标签，已回退为关键词：' + '、'.join(unresolved_tags))
    if payload.get('missing_tags'):
        lines.append('筛选阶段未找到的标签：' + '、'.join(payload['missing_tags']))

    total = int(payload.get('total') or 0)
    if total <= 0:
        lines.append('结果：没有找到符合条件的题目。建议换个关键词，或进入 /luogu jump 继续细筛。')
        return '\n'.join(lines)

    shown_count = len(payload.get('summaries') or [])
    if shown_count > 0:
        lines.append(f'结果：共找到 {total} 道题，当前先展示前 {shown_count} 道候选。')
    else:
        lines.append(f'结果：共找到 {total} 道题。')

    chosen = payload.get('chosen')
    if chosen:
        chosen_title = str(chosen.get('title') or '').strip()
        chosen_pid = str(chosen.get('pid') or '').strip()
        if chosen_pid and chosen_title.startswith(chosen_pid + ' '):
            chosen_title = chosen_title[len(chosen_pid) + 1:].strip()
        lines.extend([
            '已选中的题目：',
            f'- {chosen_pid} {chosen_title or chosen_pid}',
            f'- 难度：{chosen.get("difficulty_name") or "未知"}',
            f'- 标签：{"、".join(chosen.get("tags") or []) or "无"}',
            f'- 链接：{chosen.get("url")}',
            '如果需要继续换题、看图或截图，建议进入 /luogu jump。',
        ])
        return '\n'.join(lines)

    summaries = payload.get('summaries') or []
    if summaries:
        lines.append('前几个候选题目：')
        for item in summaries:
            diff = f' | {item["difficulty_name"]}' if item.get('difficulty_name') else ''
            lines.append(f'{item["index"]}. {item["pid"]} {item["title"]}{diff}')
            lines.append(f'   {item["url"]}')
    lines.append('你可以继续说“总共有多少道”“随便来一道”“第 3 题”“再加个线段树标签”。')
    return '\n'.join(lines)
