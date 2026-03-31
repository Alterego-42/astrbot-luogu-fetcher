from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Tuple


logger = logging.getLogger(__name__)
JUMP_DEFAULT_PAGE_SIZE = 50


def build_jump_initial_state(
    requested_count: int,
    *,
    clamp_count: Callable[[int], int],
) -> dict[str, Any]:
    return {
        'difficulty': None,
        'tags': [],
        'keyword': None,
        'total': 0,
        'list_url': None,
        'page_size': JUMP_DEFAULT_PAGE_SIZE,
        'requested_count': clamp_count(requested_count),
        'batch_summaries': [],
    }


def clear_jump_selection_state(state: dict[str, Any]) -> None:
    state['batch_summaries'] = []
    state.pop('current_pid', None)
    state.pop('current_title', None)
    state.pop('current_md', None)


def move_jump_to_keyword_step(state: dict[str, Any]) -> None:
    state['keyword'] = None
    state['total'] = 0
    state['list_url'] = None
    state['page_size'] = JUMP_DEFAULT_PAGE_SIZE
    clear_jump_selection_state(state)


def move_jump_to_difficulty_step(state: dict[str, Any]) -> None:
    state['difficulty'] = None
    state['tags'] = []
    move_jump_to_keyword_step(state)


def remember_jump_filter_result(state: dict[str, Any], result: dict[str, Any]) -> None:
    state['total'] = result.get('total', 0)
    state['list_url'] = result.get('list_url')
    state['page_size'] = result.get('page_size_detected', JUMP_DEFAULT_PAGE_SIZE)
    clear_jump_selection_state(state)


def remember_jump_problem_artifact(
    state: dict[str, Any],
    *,
    pid: str,
    title: Optional[str],
    md_content: Optional[str],
) -> None:
    clear_jump_selection_state(state)
    state['current_pid'] = pid
    state['current_title'] = title or ''
    state['current_md'] = md_content or ''


async def ensure_jump_cookie_ready(
    *,
    cookies_file: str,
    qq_id: str,
    send_text: Callable[[str], Awaitable[Any]],
    check_cookie_valid: Callable[[str], bool],
    load_credentials: Callable[[str], Optional[Tuple[str, str]]],
    do_login: Callable[..., dict],
) -> bool:
    loop = asyncio.get_event_loop()
    logger.info('[Luogu jump] 检测 cookie 有效性: %s', cookies_file)
    cookie_valid = await loop.run_in_executor(None, check_cookie_valid, cookies_file)
    if cookie_valid:
        return True

    logger.warning('[Luogu jump] Cookie 已过期，检查是否有保存的账密...')
    creds = load_credentials(qq_id)
    if not creds:
        logger.warning('[Luogu jump] Cookie 已过期，且无保存的账密')
        await send_text(
            '⚠️ 登录状态已失效，请重新绑定账号后继续。\n'
            '使用方法：/luogu bind <手机号> <密码>'
        )
        return False

    username, password = creds
    logger.info('[Luogu jump] 发现保存的账密，正在自动登录...')
    await send_text('🔄 Cookie 已过期，正在使用保存的账密自动重新登录...')
    login_result = await loop.run_in_executor(
        None,
        lambda: do_login(username, password, qq_id, save_credentials=False),
    )
    if not login_result.get('success'):
        await send_text(
            f'⚠️ 自动登录失败：{login_result.get("message", "未知错误")}\n'
            '请重新绑定账号'
        )
        return False

    logger.info('[Luogu jump] 自动登录成功，等待 cookie 写入...')
    await asyncio.sleep(0.5)
    cookie_valid = await loop.run_in_executor(None, check_cookie_valid, cookies_file)
    logger.info('[Luogu jump] 重新检测 cookie 有效性: %s', cookie_valid)
    if cookie_valid:
        return True

    await send_text('⚠️ 自动登录成功但 Cookie 仍无效，请重新绑定')
    return False
