from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from .problem_fetcher import ProblemFetcher


async def ensure_jump_fetcher(
    *,
    fetcher: Optional[ProblemFetcher],
    cookies_file: str,
    run_in_pw: Callable[[Callable[[], Any]], Awaitable[Any]],
    list_url: Optional[str] = None,
) -> ProblemFetcher:
    if fetcher is not None:
        return fetcher

    fetcher = ProblemFetcher(cookies_file)
    await run_in_pw(fetcher.setup)
    if list_url:
        def _goto_list() -> None:
            fetcher.page.goto(list_url, timeout=20000)
            fetcher.page.wait_for_load_state('domcontentloaded', timeout=15000)
            import time as _time
            _time.sleep(1.5)

        await run_in_pw(_goto_list)
    return fetcher


async def apply_jump_filters_via_fetcher(
    *,
    fetcher: Optional[ProblemFetcher],
    state: Dict[str, Any],
    cookies_file: str,
    run_in_pw: Callable[[Callable[[], Any]], Awaitable[Any]],
) -> Tuple[ProblemFetcher, Dict[str, Any]]:
    fetcher = await ensure_jump_fetcher(
        fetcher=fetcher,
        cookies_file=cookies_file,
        run_in_pw=run_in_pw,
    )

    def _do_apply() -> Dict[str, Any]:
        user_diff = state.get('difficulty')
        url_difficulty = (user_diff - 1) if user_diff is not None else None
        return fetcher.apply_filters(
            difficulty=url_difficulty,
            tags=state['tags'] if state['tags'] else None,
            keyword=state['keyword'] if state['keyword'] else None,
        )

    result = await run_in_pw(_do_apply)
    return fetcher, result


async def load_jump_problem_detail(
    *,
    fetcher: Optional[ProblemFetcher],
    state: Dict[str, Any],
    cookies_file: str,
    run_in_pw: Callable[[Callable[[], Any]], Awaitable[Any]],
    position: Optional[int] = None,
    pid: Optional[str] = None,
) -> Tuple[ProblemFetcher, Optional[str], Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    fetcher = await ensure_jump_fetcher(
        fetcher=fetcher,
        cookies_file=cookies_file,
        run_in_pw=run_in_pw,
        list_url=state.get('list_url'),
    )

    def _do_show() -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        direct_pid = pid
        if direct_pid:
            detail = fetcher.get_problem_detail(direct_pid)
            md_content = fetcher.extract_markdown_content(direct_pid)
            normalized_pid = str(detail.get('pid') or direct_pid).strip().upper()
            if not normalized_pid.startswith('P'):
                normalized_pid = f'P{normalized_pid}'
            return normalized_pid, detail, md_content, None

        if position:
            resolved_pid = fetcher.navigate_to_problem(
                position,
                list_url=state.get('list_url'),
                page_size_hint=state.get('page_size'),
            )
            if not resolved_pid:
                return None, None, None, (
                    f'❌ 跳转题目失败（page_size={state.get("page_size")}, '
                    f'list_url={state.get("list_url")}）'
                )

        import re as _re

        url = fetcher.page.url
        pid_match = _re.search(r'/problem/(P?\w+)', url, _re.IGNORECASE)
        resolved_pid = pid_match.group(1) if pid_match else '???'
        if not resolved_pid.upper().startswith('P'):
            resolved_pid = 'P' + resolved_pid.upper().lstrip('P')
        detail = fetcher.get_problem_detail(resolved_pid)
        md_content = fetcher.extract_markdown_content(resolved_pid)
        return resolved_pid, detail, md_content, None

    resolved_pid, detail, md_content, error = await run_in_pw(_do_show)
    return fetcher, resolved_pid, detail, md_content, error


async def screenshot_jump_problem(
    *,
    fetcher: ProblemFetcher,
    pid: str,
    run_in_pw: Callable[[Callable[[], Any]], Awaitable[Any]],
) -> Any:
    def _do_screenshot() -> Any:
        fetcher.page.goto(f'https://www.luogu.com.cn/problem/{pid}', timeout=20000)
        fetcher.page.wait_for_load_state('domcontentloaded', timeout=15000)
        import time as _time
        _time.sleep(1.5)
        return fetcher.screenshot_problem(pid)

    return await run_in_pw(_do_screenshot)
