from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from luogu.problem_fetcher import ProblemFetcher
from luogu.tags import DIFFICULTY_NAMES, fuzzy_match_tag


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
    lines.append('如果你想直接让我随机挑一道，也可以明确说“来一道/随机来一题”。')
    return '\n'.join(lines)
