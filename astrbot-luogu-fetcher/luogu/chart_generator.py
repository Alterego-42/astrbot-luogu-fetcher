"""
洛谷数据图表生成模块

功能：
1. generate_heatmap()      做题热度图（GitHub style 日历热力图）
2. generate_elo_trend()    比赛等级分趋势折线图
3. generate_summary_card() 用户统计卡片（通过/提交/排名/等级分）
4. generate_bar_chart()    通用柱状图
"""

import io
import datetime
import calendar
import math
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import numpy as np

# 中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 洛谷配色
C = {
    'blue':    '#1890ff',
    'green':   '#52c41a',
    'orange':  '#fa8c16',
    'red':     '#f5222d',
    'bg':      '#ffffff',
    'card_bg': '#f6f8fa',
    'text':    '#24292e',
    'subtext': '#586069',
    'border':  '#e1e4e8',
    'heat0':   '#ebedf0',   # 无数据/暂无评定
    # 难度七色（红→橙→黄→绿→蓝→紫→黑）
    'diff_red':    '#f5222d',   # 入门
    'diff_orange': '#fa8c16',   # 普及−
    'diff_yellow': '#fadb14',   # 普及/提高−
    'diff_green':  '#52c41a',   # 普及+/提高
    'diff_blue':   '#1890ff',   # 提高+/省选−
    'diff_purple': '#722ed1',   # 省选/NOI−
    'diff_black':  '#1f1f1f',   # NOI/NOI+/CTSC
}

# 难度等级到颜色的映射（用于热度图）
DIFFICULTY_COLORS = [
    C['heat0'],      # 0: 暂无评定
    C['diff_red'],   # 1: 入门
    C['diff_orange'],# 2: 普及−
    C['diff_yellow'],# 3: 普及/提高−
    C['diff_green'], # 4: 普及+/提高
    C['diff_blue'],  # 5: 提高+/省选−
    C['diff_purple'],# 6: 省选/NOI−
    C['diff_black'], # 7: NOI/NOI+/CTSC
]

# 难度名称（按等级顺序）
DIFFICULTY_NAMES = [
    '暂无评定', '入门', '普及−', '普及/提高−',
    '普及+/提高', '提高+/省选−', '省选/NOI−', 'NOI/NOI+/CTSC'
]


# ─────────────────────────────────────────────────────────────
# 1. 做题热度图（洛谷原版风格：按最大难度着色）
# ─────────────────────────────────────────────────────────────

def generate_heatmap(
    daily_counts: Dict[str, list],
    difficulty_map: Dict[str, int] = None,  # {date_str: max_difficulty_int}
    username: str = '',
    save_path: str = None,
    weeks: int = 26,
) -> bytes:
    """
    生成洛谷风格热度图，每格颜色代表当天通过的最大难度。

    Args:
        daily_counts: {date_str: [submit_count, new_passed_count]}
        difficulty_map: {date_str: max_difficulty_int}  最大难度（0-7）
        username:     用户名
        save_path:    保存路径
        weeks:        显示最近多少周

    Returns:
        PNG 字节数据
    """
    today = datetime.date.today()
    start = today - datetime.timedelta(days=today.weekday() + 1 + (weeks - 1) * 7)
    if today.weekday() == 6:
        start = today - datetime.timedelta(days=(weeks - 1) * 7)

    # 构建 date -> count 映射
    count_map: Dict[datetime.date, int] = {}
    for ds, val in daily_counts.items():
        try:
            d = datetime.date.fromisoformat(ds)
            count_map[d] = val[1] if isinstance(val, list) and len(val) > 1 else (val if isinstance(val, int) else 0)
        except Exception:
            pass

    # 构建 date -> max_difficulty 映射
    diff_map: Dict[datetime.date, int] = {}
    if difficulty_map:
        for ds, diff in difficulty_map.items():
            try:
                d = datetime.date.fromisoformat(ds)
                diff_map[d] = max(0, min(7, diff))  # 限制在 0-7 范围
            except Exception:
                pass

    def _difficulty_color(difficulty: int) -> str:
        """根据难度等级返回对应颜色"""
        return DIFFICULTY_COLORS[max(0, min(7, difficulty))]

    def _count_color(n: int) -> str:
        """根据做题数量返回颜色（无难度数据时使用灰色梯度）"""
        if n <= 0:    return C['heat0']
        if n <= 1:    return '#d0d0d0'
        if n <= 3:    return '#a0a0a0'
        return '#707070'

    # 布局
    fig_w = max(9, weeks * 0.28 + 1.5)
    fig, ax = plt.subplots(figsize=(fig_w, 2.6), dpi=120)
    ax.set_aspect('equal')
    ax.axis('off')
    fig.patch.set_facecolor(C['bg'])

    cell = 0.9
    gap  = 0.18
    step = cell + gap

    month_labels: Dict[int, str] = {}

    col = 0
    cur = start
    passed_count = 0
    while cur <= today:
        week_day = cur.weekday()
        if week_day == 0 and cur != start:
            col += 1
        row = week_day

        cnt  = count_map.get(cur, 0)
        diff = diff_map.get(cur, -1)  # -1 表示无数据

        if cnt > 0:
            passed_count += cnt

        # 根据最大难度选择颜色
        if diff >= 0:
            fc = _difficulty_color(diff)
        elif cnt > 0:
            fc = C['heat0']  # 有做题但无难度数据
        else:
            fc = C['heat0']

        ec = '#c6cbd1' if cnt <= 0 else 'none'

        rect = mpatches.FancyBboxPatch(
            (col * step, -(row * step)),
            cell, cell,
            boxstyle='round,pad=0.08',
            facecolor=fc, edgecolor=ec, linewidth=0.4
        )
        ax.add_patch(rect)

        if cur.day == 1:
            month_labels[col] = cur.strftime('%m月')

        cur += datetime.timedelta(days=1)

    total_cols = col + 1

    # 月份标签
    for c, label in month_labels.items():
        ax.text(c * step + cell / 2, step * 0.5,
                label, ha='center', va='bottom',
                fontsize=7.5, color=C['subtext'])

    # 星期标签（周一三五）
    for row, lbl in [(0, '一'), (2, '三'), (4, '五')]:
        ax.text(-gap * 3, -(row * step) + cell / 2,
                lbl, ha='right', va='center',
                fontsize=8, color=C['subtext'])

    # 洛谷风格图例：难度色块 + 难度名称
    legend_x = total_cols * step - 5 * step
    legend_y = -(7 * step) - 0.35
    ax.text(legend_x, legend_y + 0.1, '难度', ha='left', va='center',
            fontsize=7, color=C['subtext'])

    # 难度颜色图例（从入门到 NOI/NOI+/CTSC）
    for i, (color, name) in enumerate(zip(DIFFICULTY_COLORS[1:], DIFFICULTY_NAMES[1:])):
        lx = legend_x + 1.0 + i * (cell + 0.15)
        rect = mpatches.FancyBboxPatch(
            (lx, legend_y - cell / 2),
            cell, cell,
            boxstyle='round,pad=0.05',
            facecolor=color, edgecolor='none'
        )
        ax.add_patch(rect)

    # 标题
    title = f'{username} · 近 {weeks} 周做题热度  共 {passed_count} 题' if username else f'近 {weeks} 周做题热度  共 {passed_count} 题'
    ax.set_title(title, fontsize=10, color=C['text'],
                 pad=12, loc='left', fontweight='bold')

    ax.set_xlim(-1.5, total_cols * step + 0.5)
    ax.set_ylim(-(7 * step) - 1.2, step * 1.2)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight',
                facecolor=C['bg'], edgecolor='none')
    buf.seek(0)
    img = buf.read()
    plt.close()

    if save_path:
        with open(save_path, 'wb') as f:
            f.write(img)

    return img


# ─────────────────────────────────────────────────────────────
# 2. 比赛等级分趋势折线图（每个点标注分数和变化）
# ─────────────────────────────────────────────────────────────

def generate_elo_trend(
    elo_history: List[Dict],
    username: str = '',
    save_path: str = None,
) -> bytes:
    """
    生成比赛等级分趋势折线图，每个点标注分数。

    Args:
        elo_history: [{date, rating, change, contest}] 按时间正序（旧→新）
        username:    用户名
        save_path:   保存路径

    Returns:
        PNG 字节数据
    """
    if not elo_history:
        return _empty_chart('暂无等级分数据', save_path)

    # 只保留 rating > 0 的条目，并按日期正序排列
    valid = [e for e in reversed(elo_history) if e.get('rating', 0) > 0]
    if not valid:
        return _empty_chart('暂无有效等级分数据', save_path)

    dates    = [e['date'] for e in valid]
    ratings  = [e['rating'] for e in valid]
    changes  = [e.get('change', 0) or 0 for e in valid]
    contests = [e.get('contest', '') for e in valid]

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120)
    fig.patch.set_facecolor(C['bg'])
    ax.set_facecolor(C['card_bg'])

    x = np.arange(len(dates))

    # 折线 + 区域
    ax.plot(x, ratings, color=C['blue'], linewidth=2.2, zorder=3)
    ax.fill_between(x, ratings, alpha=0.12, color=C['blue'])

    # 标注点（上涨绿，下跌红）和分数
    for i, (xi, r, ch, contest) in enumerate(zip(x, ratings, changes, contests)):
        point_color = C['green'] if ch >= 0 else C['red']
        ax.scatter(xi, r, color=point_color, s=55, zorder=5, edgecolors='white', linewidth=1.2)

        # 分数标注（在点上方）
        ax.annotate(f'{r}',
                    xy=(xi, r),
                    xytext=(0, 12),
                    textcoords='offset points',
                    ha='center', fontsize=9,
                    color=C['text'], fontweight='bold')

        # 变化量标注（在分数上方）
        if ch != 0:
            sign = '+' if ch > 0 else ''
            ax.annotate(f'({sign}{ch})',
                        xy=(xi, r),
                        xytext=(0, 24),
                        textcoords='offset points',
                        ha='center', fontsize=7.5,
                        color=point_color)

    # X 轴：日期标签 + 比赛名称
    ax.set_xticks(x)
    labels = []
    for d in dates:
        try:
            dt = datetime.date.fromisoformat(d)
            labels.append(dt.strftime('%m/%d'))
        except Exception:
            labels.append(d[:5])
    ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=8.5,
                        color=C['subtext'])

    # Y 轴
    y_min = min(ratings)
    y_max = max(ratings)
    margin = max(150, (y_max - y_min) * 0.3)
    ax.set_ylim(max(0, y_min - margin), y_max + margin)
    ax.yaxis.set_tick_params(labelcolor=C['subtext'], labelsize=9)

    # 样式
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(C['border'])
    ax.spines['bottom'].set_color(C['border'])
    ax.grid(axis='y', linestyle='--', alpha=0.4, color=C['border'])

    latest = ratings[-1]
    title_str = (f'{username} · 比赛等级分趋势  当前 {latest}' if username
                 else f'比赛等级分趋势  当前 {latest}')
    ax.set_title(title_str, fontsize=11, color=C['text'],
                fontweight='bold', pad=10, loc='left')

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight',
                facecolor=C['bg'], edgecolor='none')
    buf.seek(0)
    img = buf.read()
    plt.close()

    if save_path:
        with open(save_path, 'wb') as f:
            f.write(img)

    return img


# ─────────────────────────────────────────────────────────────
# 3. 用户统计卡片
# ─────────────────────────────────────────────────────────────

def generate_summary_card(
    profile: Dict,
    save_path: str = None,
) -> bytes:
    """
    生成用户统计卡片图片。

    Args:
        profile: data_fetcher.fetch_profile_stats() 返回的字典
                 含 name/uid/passed/submitted/rating/csr/rank/contests
        save_path: 保存路径

    Returns:
        PNG 字节数据
    """
    name      = profile.get('name') or profile.get('uid', '未知')
    uid       = profile.get('uid', '')
    passed    = profile.get('passed', 0)
    submitted = profile.get('submitted', 0)
    rating    = profile.get('rating', 0)
    csr       = profile.get('csr', 0)
    rank      = profile.get('rank')
    contests  = profile.get('contests', 0)

    rows = [
        ('通过题数',   str(passed),    C['green']),
        ('提交次数',   str(submitted), C['blue']),
        ('等级分',     str(rating),    C['orange']),
        ('咕值',       str(csr),       C['subtext']),
        ('等级分排名', f'#{rank}' if rank else 'N/A', C['blue']),
        ('评定比赛',   str(contests),  C['subtext']),
    ]

    fig_h = 0.7 + len(rows) * 0.55 + 0.7
    fig, ax = plt.subplots(figsize=(5.2, fig_h), dpi=130)
    fig.patch.set_facecolor(C['bg'])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, fig_h)
    ax.axis('off')

    # 卡片背景
    card = mpatches.FancyBboxPatch(
        (0.2, 0.1), 9.6, fig_h - 0.2,
        boxstyle='round,pad=0.15',
        facecolor=C['card_bg'], edgecolor=C['border'], linewidth=1.0
    )
    ax.add_patch(card)

    # 标题区
    ax.text(5, fig_h - 0.42, name,
            ha='center', va='center',
            fontsize=14, fontweight='bold', color=C['text'])
    if uid:
        ax.text(5, fig_h - 0.75, f'UID: {uid}',
                ha='center', va='center',
                fontsize=9, color=C['subtext'])

    # 分隔线
    ax.axhline(fig_h - 0.95, xmin=0.04, xmax=0.96,
               color=C['border'], linewidth=0.8)

    # 数据行
    y_start = fig_h - 1.3
    row_h   = 0.52
    for i, (label, value, color) in enumerate(rows):
        y = y_start - i * row_h

        # 左侧标签
        ax.text(0.7, y, label,
                ha='left', va='center',
                fontsize=10, color=C['subtext'])
        # 右侧数值
        ax.text(9.3, y, value,
                ha='right', va='center',
                fontsize=11, color=color, fontweight='bold')

        # 行间分隔线（非最后一行）
        if i < len(rows) - 1:
            ax.axhline(y - row_h * 0.45, xmin=0.06, xmax=0.94,
                       color=C['border'], linewidth=0.4, alpha=0.6)

    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                facecolor=C['bg'], edgecolor='none')
    buf.seek(0)
    img = buf.read()
    plt.close()

    if save_path:
        with open(save_path, 'wb') as f:
            f.write(img)

    return img


# ─────────────────────────────────────────────────────────────
# 4. 难度分布卡片（洛谷原版风格）
# ─────────────────────────────────────────────────────────────

def generate_difficulty_cards(
    passed_data: Dict[str, int],
    attempted_data: Dict[str, int] = None,
    username: str = '',
    save_path: str = None,
) -> bytes:
    """
    生成洛谷风格难度分布卡片（替代柱状图）。

    Args:
        passed_data:    {difficulty_name: count} 已通过题目数
        attempted_data: {difficulty_name: count} 尝试过总数（可选）
        username:       用户名
        save_path:      保存路径

    Returns:
        PNG 字节数据
    """
    # 难度颜色映射
    diff_colors = {
        '暂无评定':   '#bdc3c7',
        '入门':       C['diff_red'],
        '普及−':      C['diff_orange'],
        '普及/提高−': C['diff_yellow'],
        '普及+/提高': C['diff_green'],
        '提高+/省选−': C['diff_blue'],
        '省选/NOI−':  C['diff_purple'],
        'NOI/NOI+/CTSC': C['diff_black'],
    }

    # 按难度顺序排列
    diff_order = DIFFICULTY_NAMES
    total_passed = sum(passed_data.values()) if passed_data else 0
    total_attempted = sum(attempted_data.values()) if attempted_data else 0

    # 计算每行显示几个卡片
    cards_per_row = 4
    card_width = 2.2
    card_height = 1.3
    card_gap = 0.25
    row_gap = 0.4

    rows = []
    current_row = []
    for diff in diff_order:
        passed = passed_data.get(diff, 0)
        attempted = attempted_data.get(diff, 0) if attempted_data else passed
        if passed > 0 or attempted > 0:
            current_row.append({
                'name': diff,
                'passed': passed,
                'attempted': attempted,
                'color': diff_colors.get(diff, '#95a5a6'),
            })
        if len(current_row) >= cards_per_row:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    if not rows:
        return _empty_chart('暂无难度数据', save_path)

    # 计算画布大小
    fig_width = cards_per_row * (card_width + card_gap) + card_gap + 0.5
    fig_height = len(rows) * (card_height + row_gap) + 1.2

    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=130)
    fig.patch.set_facecolor(C['bg'])
    ax.set_xlim(0, fig_width)
    ax.set_ylim(0, fig_height)
    ax.axis('off')

    # 标题
    title = f'{username} · 难度分布' if username else '难度分布'
    ax.text(0.3, fig_height - 0.25, title,
            ha='left', va='center', fontsize=12, fontweight='bold', color=C['text'])
    if total_passed > 0:
        ax.text(fig_width - 0.3, fig_height - 0.25, f'共 {total_passed} 题',
                ha='right', va='center', fontsize=10, color=C['subtext'])

    # 绘制每个难度卡片
    for row_idx, row in enumerate(rows):
        y_top = fig_height - 0.7 - row_idx * (card_height + row_gap)

        for col_idx, card in enumerate(row):
            x_left = 0.25 + col_idx * (card_width + card_gap)

            # 卡片背景
            bg = mpatches.FancyBboxPatch(
                (x_left, y_top - card_height),
                card_width, card_height,
                boxstyle='round,pad=0.08',
                facecolor=C['card_bg'], edgecolor=C['border'], linewidth=1
            )
            ax.add_patch(bg)

            # 难度色块（左上角）
            color_rect = mpatches.FancyBboxPatch(
                (x_left + 0.12, y_top - 0.25),
                0.22, 0.15,
                boxstyle='round,pad=0.03',
                facecolor=card['color'], edgecolor='none'
            )
            ax.add_patch(color_rect)

            # 难度名称
            ax.text(x_left + 0.4, y_top - 0.17,
                    card['name'],
                    ha='left', va='center',
                    fontsize=9, color=C['text'])

            # 题数（已通过）
            ax.text(x_left + 0.12, y_top - 0.55,
                    f'{card["passed"]}',
                    ha='left', va='center',
                    fontsize=18, fontweight='bold', color=card['color'])

            ax.text(x_left + 0.12 + len(str(card['passed'])) * 0.28 + 0.1, y_top - 0.52,
                    '题已通过',
                    ha='left', va='center',
                    fontsize=8, color=C['subtext'])

            # 尝试数（如果有）
            if attempted_data and card['attempted'] != card['passed']:
                ax.text(x_left + 0.12, y_top - 0.85,
                        f'（共尝试 {card["attempted"]} 题）',
                        ha='left', va='center',
                        fontsize=7.5, color=C['subtext'])

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                facecolor=C['bg'], edgecolor='none')
    buf.seek(0)
    img = buf.read()
    plt.close()

    if save_path:
        with open(save_path, 'wb') as f:
            f.write(img)

    return img


# ─────────────────────────────────────────────────────────────
# 5. 通用柱状图（保留，但标注为旧方法）
# ─────────────────────────────────────────────────────────────

def generate_bar_chart(
    data: Dict[str, int],
    title: str,
    ylabel: str = '数量',
    color: str = None,
    save_path: str = None,
    width: int = 800,
    height: int = 380,
    dpi: int = 120,
) -> bytes:
    """生成柱状图（保留兼容性）"""
    if not data:
        return _empty_chart(title + '（暂无数据）', save_path)

    if color is None:
        color = C['blue']

    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(C['bg'])
    ax.set_facecolor(C['card_bg'])

    labels = list(data.keys())
    values = list(data.values())

    bars = ax.bar(labels, values, color=color, width=0.6, edgecolor='none',
                  zorder=3)

    for bar, val in zip(bars, values):
        if val > 0:
            ax.annotate(f'{val}',
                        xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 4),
                        textcoords='offset points',
                        ha='center', va='bottom',
                        fontsize=9, color=C['text'])

    ax.set_title(title, fontsize=12, fontweight='bold',
                 color=C['text'], pad=10, loc='left')
    ax.set_ylabel(ylabel, fontsize=9, color=C['subtext'])

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(C['border'])
    ax.spines['bottom'].set_color(C['border'])
    ax.grid(axis='y', linestyle='--', alpha=0.35, color=C['border'])
    ax.tick_params(colors=C['subtext'])

    ax.set_xticks(range(len(labels)))
    if len(labels) > 6 or max(len(l) for l in labels) > 5:
        ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=8.5)
    else:
        ax.set_xticklabels(labels, fontsize=9.5)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor=C['bg'], edgecolor='none')
    buf.seek(0)
    img = buf.read()
    plt.close()

    if save_path:
        with open(save_path, 'wb') as f:
            f.write(img)

    return img


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────

def _empty_chart(msg: str, save_path: str = None) -> bytes:
    """生成一张占位空图"""
    fig, ax = plt.subplots(figsize=(6, 2), dpi=100)
    fig.patch.set_facecolor(C['bg'])
    ax.axis('off')
    ax.text(0.5, 0.5, msg, ha='center', va='center',
            fontsize=12, color=C['subtext'],
            transform=ax.transAxes)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                facecolor=C['bg'])
    buf.seek(0)
    img = buf.read()
    plt.close()
    if save_path:
        with open(save_path, 'wb') as f:
            f.write(img)
    return img


# ─────────────────────────────────────────────────────────────
# 兼容旧接口（保留 ChartGenerator 类名）
# ─────────────────────────────────────────────────────────────

class ChartGenerator:
    """兼容旧接口的包装器"""

    def __init__(self, width=800, height=400, dpi=120):
        self.width = width
        self.height = height
        self.dpi = dpi

    def generate_bar_chart(self, data, title, xlabel=None, ylabel='数量',
                            color=None, save_path=None):
        return generate_bar_chart(data, title, ylabel=ylabel, color=color,
                                  save_path=save_path, width=self.width,
                                  height=self.height, dpi=self.dpi)

    def generate_trend_chart(self, dates, values, title, ylabel='数量',
                              color=None, fill=True, save_path=None):
        # 转换成 elo_history 格式
        history = [{'date': d, 'rating': v, 'change': 0} for d, v in zip(dates, values)]
        return generate_elo_trend(history, save_path=save_path)

    def generate_summary_card(self, title, stats, save_path=None):
        # 将旧格式转换为 profile dict
        profile = {
            'name': stats.get('用户名') or title,
            'uid':  stats.get('UID', ''),
            'passed':    int(str(stats.get('通过数', 0)).replace(',', '') or 0),
            'submitted': int(str(stats.get('提交数', 0)).replace(',', '') or 0),
            'rating':    int(str(stats.get('等级分', 0)).replace(',', '') or 0),
            'csr':       int(str(stats.get('咕值', 0)).replace(',', '') or 0),
            'rank':      str(stats.get('排名', '')).lstrip('#'),
            'contests':  int(str(stats.get('评定比赛', 0)).replace(',', '') or 0),
        }
        return generate_summary_card(profile, save_path=save_path)


# ─────────────────────────────────────────────────────────────
# 测试入口
# ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print('测试图表生成...')

    # 模拟数据
    import random
    from datetime import date, timedelta
    today = date.today()

    # 热度图（模拟做题数据 + 难度映射）
    daily = {}
    diff_map = {}
    for i in range(180):
        d = today - timedelta(days=i)
        n = random.choices([0, 0, 0, 1, 2, 3, 5], weights=[4,3,2,2,1,1,1])[0]
        if n > 0:
            daily[d.isoformat()] = [n, n]
            # 随机分配最大难度
            diff_map[d.isoformat()] = random.randint(1, 6)
    generate_heatmap(daily, diff_map, username='Sou39O', save_path='screenshots/test_heatmap.png')
    print('热度图: screenshots/test_heatmap.png')

    # 等级分趋势图
    elo = [
        {'date': '2025-12-14', 'rating': 0,    'change': 0,    'contest': 'Opoi 2025'},
        {'date': '2026-01-24', 'rating': 1378,  'change': 1378, 'contest': '1月月赛Ⅳ'},
        {'date': '2026-02-08', 'rating': 1220,  'change': -158, 'contest': '2月月赛I'},
        {'date': '2026-02-11', 'rating': 1085,  'change': -135, 'contest': '2月月赛II'},
        {'date': '2026-02-12', 'rating': 990,   'change': -95,  'contest': '基础赛#30'},
        {'date': '2026-02-21', 'rating': 1090,  'change': 100,  'contest': '2月月赛III'},
    ]
    generate_elo_trend(elo, username='Sou39O', save_path='screenshots/test_elo_trend.png')
    print('等级分趋势: screenshots/test_elo_trend.png')

    # 用户统计卡片
    profile = {
        'name': 'Sou39O', 'uid': '1873020',
        'passed': 106, 'submitted': 112,
        'rating': 1090, 'csr': 199,
        'rank': '5887', 'contests': 5,
    }
    generate_summary_card(profile, save_path='screenshots/test_summary_card.png')
    print('统计卡片: screenshots/test_summary_card.png')

    # 难度分布卡片
    passed_data = {
        '入门': 20, '普及−': 35, '普及/提高−': 25,
        '普及+/提高': 15, '提高+/省选−': 8, '省选/NOI−': 3
    }
    attempted_data = {
        '入门': 25, '普及−': 40, '普及/提高−': 30,
        '普及+/提高': 18, '提高+/省选−': 10, '省选/NOI−': 5
    }
    generate_difficulty_cards(passed_data, attempted_data, username='Sou39O',
                             save_path='screenshots/test_difficulty_cards.png')
    print('难度分布卡片: screenshots/test_difficulty_cards.png')

    print('\n完成！请查看 screenshots/ 目录下的图片')
