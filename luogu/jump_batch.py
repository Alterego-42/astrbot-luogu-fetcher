from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .problem_fetcher import ProblemFetcher
from .request_count import clamp_luogu_request_count


def _build_jump_problem_entry(
    pid: str,
    detail: Dict[str, Any],
    *,
    index: int,
    source_index: int,
) -> Dict[str, Any]:
    return {
        'index': index,
        'source_index': source_index,
        'pid': pid,
        'title': detail.get('title') or pid,
        'difficulty_name': detail.get('difficulty_name') or '',
        'tags': detail.get('tags') or [],
        'url': detail.get('url') or f'https://www.luogu.com.cn/problem/{pid}',
    }


async def refresh_jump_batch_summaries(
    *,
    state: Dict[str, Any],
    fetcher: Optional[ProblemFetcher],
    cookies_file: str,
    run_in_pw,
    batch_count: int,
) -> Tuple[Optional[ProblemFetcher], List[Dict[str, Any]]]:
    batch_count = clamp_luogu_request_count(batch_count)
    if not state.get('list_url') or int(state.get('total') or 0) <= 0:
        return fetcher, []

    if fetcher is None:
        fetcher = ProblemFetcher(cookies_file)
        await run_in_pw(fetcher.setup)

    def _do_extract():
        fetcher.page.goto(state['list_url'], timeout=20000)
        fetcher.page.wait_for_load_state('domcontentloaded', timeout=15000)
        return fetcher.extract_problem_summaries(limit=batch_count)

    summaries = await run_in_pw(_do_extract)
    return fetcher, list(summaries or [])[:batch_count]


async def load_jump_problem_batch(
    *,
    state: Dict[str, Any],
    fetcher: Optional[ProblemFetcher],
    cookies_file: str,
    run_in_pw,
    positions: Iterable[int],
) -> Tuple[Optional[ProblemFetcher], List[Dict[str, Any]]]:
    positions = list(positions or [])
    if not positions:
        return fetcher, []

    if fetcher is None:
        fetcher = ProblemFetcher(cookies_file)
        await run_in_pw(fetcher.setup)

    def _do_batch():
        result_items = []
        for display_index, position in enumerate(positions, start=1):
            pid = fetcher.navigate_to_problem(
                position,
                list_url=state.get('list_url'),
                page_size_hint=state.get('page_size'),
            )
            if not pid:
                continue
            detail = fetcher.get_problem_detail(pid)
            result_items.append(
                _build_jump_problem_entry(
                    pid,
                    detail,
                    index=display_index,
                    source_index=position,
                )
            )
        return result_items

    items = await run_in_pw(_do_batch)
    return fetcher, list(items or [])
