"""
洛谷跳题会话的纯展示层辅助函数。

这里集中放状态展示、步骤提示和题目预览文本，避免 main.py
继续堆积大量文案与格式化逻辑。
"""

from typing import Dict, List

from .tags import DIFFICULTY_NAMES


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
