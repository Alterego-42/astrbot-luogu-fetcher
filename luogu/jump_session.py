"""
洛谷跳题会话的纯展示层辅助函数。

这里集中放状态展示、步骤提示和题目预览文本，避免 main.py
继续堆积大量文案与格式化逻辑。
"""

import difflib
import random
import re
from typing import Any, Dict, List, Optional, Tuple

from .tags import DIFFICULTY_NAMES, fuzzy_match_tag


JUMP_HELP_TEXT = """📖 题库跳转帮助

可用输入：
  0-8        选择难度
  +标签      添加标签，如 +动规
  -标签      移除标签，如 -动规
  done       确认当前标签
  skip       跳过当前步骤
  random     随机选题
  看图       查看题面截图（当前与截图一致）
  截图       获取洛谷网页截图
  back       返回上一步
  back-diff  重新开始筛选
  quit       退出会话"""

JUMP_QUIT_COMMANDS = ('quit', '退出', 'exit', 'q', '算了')
JUMP_HELP_COMMANDS = ('help', '帮助', '?')
JUMP_RANDOM_COMMANDS = ('random', 'r', '随机', 'rand')
JUMP_BACK_TO_KEYWORD_COMMANDS = ('back', 'back-tags', 'back-keyword')
JUMP_BACK_TO_DIFFICULTY_COMMANDS = ('back-diff',)
JUMP_SHOW_IMAGE_COMMANDS = ('看图', 'render', 'img', 'image', '图片')
JUMP_SHOW_SCREENSHOT_COMMANDS = ('截图', 'screenshot')
JUMP_DONE_COMMANDS = ('done',)
JUMP_SKIP_COMMANDS = ('skip', '跳过')
JUMP_STATUS_COMMANDS = ('list', '状态', '当前')


def jump_diff_str(state: Dict) -> str:
    """把跳题会话中的难度状态渲染为用户可读文本。"""
    difficulty = state.get('difficulty')
    if difficulty is None:
        return '不限'
    return DIFFICULTY_NAMES[difficulty - 1] if 1 <= difficulty <= 8 else '不限'


def jump_tags_str(state: Dict) -> str:
    return '、'.join(state['tags']) if state['tags'] else '无'


def jump_kw_str(state: Dict) -> str:
    return state.get('keyword') or '无'


def render_jump_step(step: str, state: Dict) -> str:
    """根据当前步骤生成用户提示。"""
    if step == 'difficulty':
        return (
            "第 1 步：选难度\n\n"
            "发送数字 0-8：\n"
            "  0 不限\n"
            "  1 暂无评定\n"
            "  2 入门\n"
            "  3 普及−\n"
            "  4 普及/提高−\n"
            "  5 普及+/提高\n"
            "  6 提高+/省选−\n"
            "  7 省选/NOI−\n"
            "  8 NOI/NOI+/CTSC\n\n"
            "示例：`5`\n"
            "输入 `quit` 可随时退出。"
        )

    if step == 'tags':
        return (
            "第 2 步：选标签\n\n"
            f"当前标签：{jump_tags_str(state)}\n\n"
            "发送 `+标签` 添加，`-标签` 移除。\n"
            "发送 `done` 进入下一步，`skip` 跳过。\n"
            "支持模糊匹配，例如：`+动规`、`+图论`、`+ICPC`。"
        )

    if step == 'keyword':
        return (
            "第 3 步：关键词筛选\n\n"
            f"难度：{jump_diff_str(state)}\n"
            f"标签：{jump_tags_str(state)}\n"
            f"关键词：{jump_kw_str(state)}\n\n"
            "直接发送题目标题关键词，或发送 `skip` 跳过。"
        )

    if step == 'result':
        return (
            "第 4 步：选题\n\n"
            f"已找到 {state.get('total', 0)} 道题。\n"
            f"难度：{jump_diff_str(state)}\n"
            f"标签：{jump_tags_str(state)}\n"
            f"关键词：{jump_kw_str(state)}\n\n"
            "发送题号序号选题，或发送 `random` 随机来一道。\n"
            "发送 `back` 返回改条件，发送 `back-diff` 重新开始。"
        )

    return ''


def render_no_result_prompt(state: Dict) -> str:
    return (
        "没有找到符合条件的题目。\n\n"
        f"难度：{jump_diff_str(state)}\n"
        f"标签：{jump_tags_str(state)}\n"
        f"关键词：{jump_kw_str(state)}\n\n"
        "发送 `back` 回到关键词步骤继续调整，\n"
        "发送 `back-diff` 重新开始，或发送 `quit` 退出。"
    )


def render_selected_tags_update(state: Dict) -> str:
    return f'当前已选标签：{jump_tags_str(state)}'


def is_jump_quit_command(lower: str) -> bool:
    return lower in JUMP_QUIT_COMMANDS


def is_jump_help_command(lower: str) -> bool:
    return lower in JUMP_HELP_COMMANDS


def is_jump_random_command(lower: str) -> bool:
    return lower in JUMP_RANDOM_COMMANDS


def is_jump_back_to_keyword_command(lower: str) -> bool:
    return lower in JUMP_BACK_TO_KEYWORD_COMMANDS


def is_jump_back_to_difficulty_command(lower: str) -> bool:
    return lower in JUMP_BACK_TO_DIFFICULTY_COMMANDS


def is_jump_show_image_command(lower: str) -> bool:
    return lower in JUMP_SHOW_IMAGE_COMMANDS


def is_jump_show_screenshot_command(lower: str) -> bool:
    return lower in JUMP_SHOW_SCREENSHOT_COMMANDS


def is_jump_done_command(lower: str) -> bool:
    return lower in JUMP_DONE_COMMANDS


def is_jump_skip_command(lower: str) -> bool:
    return lower in JUMP_SKIP_COMMANDS


def is_jump_status_command(lower: str) -> bool:
    return lower in JUMP_STATUS_COMMANDS


def apply_jump_difficulty_input(state: Dict, text: str) -> Optional[str]:
    if not text.isdigit():
        return None
    difficulty = int(text)
    if difficulty < 0 or difficulty > 8:
        return None
    state['difficulty'] = difficulty if difficulty > 0 else None
    diff_name = DIFFICULTY_NAMES[difficulty - 1] if difficulty > 0 else '不限'
    return f'✅ 已选择难度：{diff_name}'


def apply_jump_tag_update(state: Dict, text: str) -> Optional[List[str]]:
    if text.startswith('+'):
        tag_name = text[1:].strip()
        if not tag_name:
            return ['❓ 请输入标签名，如 +动规']

        tag_full, matched = normalize_jump_tag_input(tag_name)
        if matched:
            if tag_full in state['tags']:
                message = f'「{tag_full}」已在已选列表中'
            else:
                state['tags'].append(tag_full)
                message = f'✅ 已添加：「{tag_full}」'
        else:
            if tag_name in state['tags']:
                message = f'「{tag_name}」已在已选列表中'
            else:
                state['tags'].append(tag_name)
                message = (
                    f'📝 已暂存：「{tag_name}」\n'
                    '本地词表暂未命中，筛题时会到洛谷站内标签面板继续尝试；'
                    '若站内也不存在，我会提醒并忽略它。'
                )
        return [message, render_selected_tags_update(state)]

    if text.startswith('-'):
        tag_name = text[1:].strip()
        resolved_tag = resolve_jump_selected_tag(tag_name, state['tags'])
        if resolved_tag:
            state['tags'].remove(resolved_tag)
            message = f'✅ 已移除：「{resolved_tag}」'
        else:
            message = f'「{tag_name}」不在已选列表中'
        return [message, render_selected_tags_update(state)]

    return None


def apply_jump_keyword_input(state: Dict, text: str, lower: str) -> str:
    if is_jump_skip_command(lower) or lower == '无':
        state['keyword'] = None
        return '✅ 跳过关键词筛选'
    if text:
        state['keyword'] = text
        return f'✅ 已设置关键词：「{text}」'
    state['keyword'] = None
    return '✅ 未输入关键词，跳过'


def apply_jump_search_intent_filters(
    state: Dict,
    *,
    difficulty: Optional[int],
    tags: List[str],
    keyword: Optional[str],
    normalize_tags,
) -> Optional[str]:
    state['difficulty'] = difficulty or None
    normalized_tags, unresolved_tags = normalize_tags(tags)
    state['tags'] = normalized_tags
    state['keyword'] = keyword or None
    if not unresolved_tags:
        return None

    unresolved_text = ' '.join(unresolved_tags)
    if state['keyword']:
        if unresolved_text not in state['keyword']:
            state['keyword'] = f'{state["keyword"]} {unresolved_text}'.strip()
    else:
        state['keyword'] = unresolved_text
    return 'ℹ️ 洛谷里没有这些精确标签：' + '、'.join(unresolved_tags) + '。这次我先把它们当关键词一起筛。'


def render_problem_header(pid: str, detail: Dict) -> str:
    diff_name = detail.get('difficulty_name', '暂无评定')
    diff_emoji = {
        '暂无评定': '⚪',
        '入门': '🔴',
        '普及−': '🟠',
        '普及/提高−': '🟡',
        '普及+/提高': '🟢',
        '提高+/省选−': '🔵',
        '省选/NOI−': '🟣',
        'NOI/NOI+/CTSC': '⚫',
    }.get(diff_name, '⬜')

    header = (
        f'📌 {pid}  {detail.get("title", "")}\n'
        f'{diff_emoji} 难度：{diff_name}'
    )
    if detail.get('passed_rate'):
        header += f'\n📊 通过率：{detail.get("passed_rate")}'
    header += f'\n🔗 https://www.luogu.com.cn/problem/{pid}'

    tags: List[str] = detail.get('tags', [])
    if tags:
        header += f'\n🏷️ 标签：{"、".join(tags[:8])}'
    return header


def render_problem_footer() -> str:
    return (
        '─────────────────────\n'
        '💡 输入「看图」或「截图」查看洛谷题面截图\n'
        '发送 `random` 换一题，`back` 改条件，`quit` 退出'
    )


def split_markdown_chunks(md_content: str, max_chunk: int = 1500) -> List[str]:
    if not md_content:
        return []
    return [
        md_content[i:i + max_chunk]
        for i in range(0, len(md_content), max_chunk)
    ]


def build_jump_problem_forward_nodes(
    node_factory: Any,
    plain_factory: Any,
    *,
    sender_id: str,
    sender_name: str,
    header: str,
    md_content: str,
    footer: str,
) -> List[Any]:
    nodes = [
        node_factory(
            uin=sender_id,
            name=sender_name,
            content=[plain_factory(header)],
        )
    ]

    if md_content and len(md_content) > 20:
        chunks = split_markdown_chunks(md_content)
        for idx, chunk in enumerate(chunks):
            label = '📄 题目内容' if idx == 0 else f'📄 题目内容（续{idx}）'
            if len(chunks) > 1:
                label += f' [{idx+1}/{len(chunks)}]'
            nodes.append(
                node_factory(
                    uin=sender_id,
                    name=sender_name,
                    content=[plain_factory(f'{label}\n\n{chunk}')],
                )
            )
    else:
        nodes.append(
            node_factory(
                uin=sender_id,
                name=sender_name,
                content=[plain_factory('📄 题目内容为空或获取失败')],
            )
        )

    nodes.append(
        node_factory(
            uin=sender_id,
            name=sender_name,
            content=[plain_factory(footer)],
        )
    )
    return nodes


def build_jump_problem_fallback_messages(header: str, md_content: str, footer: str) -> List[str]:
    short_md = md_content[:800] if md_content else '（内容为空）'
    if len(md_content or '') > 800:
        short_md += '\n\n...（内容过长，输入「看图」查看截图）'
    return [
        header,
        f'📄 题目内容：\n\n{short_md}',
        footer,
    ]


def format_jump_batch_preview(batch_summaries: List[Dict]) -> str:
    lines = [f'已准备 {len(batch_summaries)} 道题：']
    for display_index, item in enumerate(batch_summaries, start=1):
        diff = item.get('difficulty_name') or '未知'
        lines.append(f'{display_index}. {item.get("pid")} {item.get("title")} | {diff}')
        lines.append(f'   {item.get("url")}')
    lines.append('发送 1/2/3 查看对应题面，发送 random 再换一组，发送 back 修改条件。')
    return '\n'.join(lines)


def normalize_jump_tag_input(tag_name: str) -> Tuple[str, bool]:
    matched = fuzzy_match_tag(tag_name)
    if matched:
        return matched[0], True
    return tag_name.strip(), False


def normalize_jump_tag_list_with_meta(tags: Any) -> Tuple[List[str], List[str]]:
    normalized: List[str] = []
    unresolved: List[str] = []
    seen_normalized = set()
    seen_unresolved = set()
    for raw in tags or []:
        tag_name = str(raw).strip()
        if not tag_name:
            continue
        tag_full, matched = normalize_jump_tag_input(tag_name)
        if matched:
            if tag_full in seen_normalized:
                continue
            normalized.append(tag_full)
            seen_normalized.add(tag_full)
            continue
        if tag_name in seen_unresolved:
            continue
        unresolved.append(tag_name)
        seen_unresolved.add(tag_name)
    return normalized, unresolved


def resolve_jump_selected_tag(tag_name: str, selected_tags: List[str]) -> Optional[str]:
    raw = tag_name.strip()
    if not raw:
        return None
    if raw in selected_tags:
        return raw

    matched = fuzzy_match_tag(raw)
    for candidate in matched:
        if candidate in selected_tags:
            return candidate

    lowered = raw.lower()
    for current in selected_tags:
        current_lower = current.lower()
        if lowered == current_lower or lowered in current_lower or current_lower in lowered:
            return current
    return None


def looks_like_jump_commandish_input(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return False
    if raw.isdigit() or raw.startswith(('+', '-')):
        return True

    compact = re.sub(r'[\s_-]+', '', raw.lower())
    explicit_tokens = {
        'done', 'skip', 'random', 'rand', 'back', 'backdiff',
        'backtags', 'backkeyword', 'quit', 'exit', 'help',
        'render', 'img', 'image', 'screenshot',
        '看图', '截图', '图片', '帮助', '退出', '随机',
    }
    if compact in explicit_tokens:
        return True
    if re.fullmatch(r'[a-z0-9]+', compact):
        return True
    return bool(
        difflib.get_close_matches(
            compact,
            [token for token in explicit_tokens if re.fullmatch(r'[a-z0-9]+', token)],
            n=1,
            cutoff=0.75,
        )
    )


def suggest_jump_step_command(text: str, commands: Tuple[str, ...]) -> Optional[str]:
    compact = re.sub(r'[\s_-]+', '', text.strip().lower())
    if not compact:
        return None
    matches = difflib.get_close_matches(
        compact,
        [command.replace('-', '') for command in commands],
        n=1,
        cutoff=0.75,
    )
    if not matches:
        return None
    normalized = matches[0]
    for command in commands:
        if command.replace('-', '') == normalized:
            return command
    return None


def resolve_jump_batch_pid(batch_summaries: List[Dict], index: int) -> Tuple[Optional[str], Optional[str]]:
    if not batch_summaries:
        return None, None
    if index < 1 or index > len(batch_summaries):
        return None, f'⚠️ 序号超出范围，请输入 1-{len(batch_summaries)}'
    target_pid = str(batch_summaries[index - 1].get('pid') or '').strip()
    if not target_pid:
        return None, f'⚠️ 第 {index} 题缺少题号，暂时无法打开。'
    return target_pid, None


def resolve_jump_selection_target(
    batch_summaries: List[Dict],
    index: int,
    total: int,
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    if index < 1:
        max_display = len(batch_summaries) if batch_summaries else max(0, int(total or 0))
        return None, None, f'⚠️ 序号超出范围，请输入 1-{max_display}'

    if batch_summaries:
        target_pid, selection_error = resolve_jump_batch_pid(batch_summaries, index)
        if target_pid:
            return target_pid, None, None
        return None, None, selection_error or '⚠️ 暂时无法打开这道题。'

    total = max(0, int(total or 0))
    if index <= total:
        return None, index, None
    return None, None, f'⚠️ 序号超出范围，请输入 1-{total}'


def choose_jump_random_positions(total: int, requested_count: int) -> List[int]:
    total = max(0, int(total or 0))
    requested_count = max(1, int(requested_count or 1))
    if total <= 0:
        return []
    if requested_count <= 1:
        return [random.randint(1, total)]
    sample_size = min(requested_count, total)
    return random.sample(range(1, total + 1), sample_size)
