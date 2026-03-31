from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from .llm_search_workflow import resolve_luogu_target_pid

LUOGU_BIND_REQUIRED_MESSAGE = "该用户还没有绑定洛谷账号，请先提醒他使用 /luogu bind 绑定后再调用这个工具。"


def resolve_luogu_bound_cookie_file(cookie_file: Any) -> Tuple[Optional[str], Optional[str]]:
    normalized = str(cookie_file or "").strip()
    if not normalized or not Path(normalized).exists():
        return None, LUOGU_BIND_REQUIRED_MESSAGE
    return normalized, None


def prepare_luogu_problem_display_target(
    *,
    cookie_file: Any,
    requested_pid: Optional[str],
    event_message: str,
    session_data: Optional[Mapping[str, Any]],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    normalized_cookie_file, cookie_error = resolve_luogu_bound_cookie_file(cookie_file)
    if cookie_error:
        return None, None, cookie_error

    resolved_pid, pid_error = resolve_luogu_target_pid(
        requested_pid=requested_pid,
        event_message=event_message,
        session_data=session_data,
    )
    if pid_error:
        return None, None, pid_error
    return normalized_cookie_file, resolved_pid, None


def normalize_luogu_image_mode(mode: Any, event_message: str) -> str:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode in ("rendered", "screenshot"):
        return normalized_mode
    return "screenshot" if "截图" in str(event_message or "") else "rendered"
