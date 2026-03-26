"""Luogu tag helpers backed by an official tag-catalog snapshot."""

from __future__ import annotations

from typing import Dict, List, Optional

from .tag_catalog import OFFICIAL_TAG_ROWS, OFFICIAL_TAG_TYPES


SELECTABLE_TAG_TYPES = {1, 2, 3, 4, 5}

TAG_TYPE_NAMES = {
    int(item["id"]): str(item["name"])
    for item in OFFICIAL_TAG_TYPES
}

ALL_SELECTABLE_ROWS = tuple(
    row for row in OFFICIAL_TAG_ROWS if int(row["type"]) in SELECTABLE_TAG_TYPES
)

ALL_TAGS = [str(row["name"]) for row in ALL_SELECTABLE_ROWS]
KNOWN_TAG_IDS = {
    str(row["name"]): int(row["id"])
    for row in ALL_SELECTABLE_ROWS
}

ALGORITHM_TAGS = [
    str(row["name"])
    for row in ALL_SELECTABLE_ROWS
    if int(row["type"]) == 2
]
SOURCE_TAG_IDS = {
    str(row["name"]): int(row["id"])
    for row in ALL_SELECTABLE_ROWS
    if int(row["type"]) == 3
}
REGION_TAG_IDS = {
    str(row["name"]): int(row["id"])
    for row in ALL_SELECTABLE_ROWS
    if int(row["type"]) == 1
}
TIME_TAG_IDS = {
    str(row["name"]): int(row["id"])
    for row in ALL_SELECTABLE_ROWS
    if int(row["type"]) == 4
}
SPECIAL_TAG_IDS = {
    str(row["name"]): int(row["id"])
    for row in ALL_SELECTABLE_ROWS
    if int(row["type"]) == 5
}

_PREFERRED_HOT_TAGS = [
    "动态规划 DP",
    "搜索",
    "图论",
    "字符串",
    "数学",
    "线段树",
    "并查集",
    "贪心",
    "二分",
    "模拟",
    "网络流",
    "AC 自动机",
    "后缀数组 SA",
    "平衡树",
    "树链剖分",
    "最近公共祖先 LCA",
    "快速傅里叶变换 FFT",
    "快速数论变换 NTT",
    "数位 DP",
    "状压 DP",
    "生成树",
    "最短路",
    "O2优化",
]


def _build_hot_tags() -> List[str]:
    tags: List[str] = []
    for tag in _PREFERRED_HOT_TAGS:
        if tag in KNOWN_TAG_IDS and tag not in tags:
            tags.append(tag)
    for tag in ALGORITHM_TAGS:
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= 32:
            break
    return tags


HOT_TAGS = _build_hot_tags()

DIFFICULTY_NAMES = [
    "暂无评定",
    "入门",
    "普及-",
    "普及/提高-",
    "普及+/提高",
    "提高+/省选-",
    "省选/NOI-",
    "NOI/NOI+/CTSC",
]

DIFFICULTY_COLORS = {
    "暂无评定": "#ebedf0",
    "入门": "#f5222d",
    "普及-": "#fa8c16",
    "普及/提高-": "#fadb14",
    "普及+/提高": "#52c41a",
    "提高+/省选-": "#1890ff",
    "省选/NOI-": "#722ed1",
    "NOI/NOI+/CTSC": "#1f1f1f",
}

TAG_ALIASES = {
    "状压dp": "状压 DP",
    "状态压缩dp": "状压 DP",
    "状态压缩": "状压 DP",
    "次小生成树": "生成树",
    "最小生成树": "生成树",
    "o2优化": "O2优化",
}


def _char_seq_match(input_s: str, tag_s: str) -> bool:
    """Whether all chars in ``input_s`` appear in order within ``tag_s``."""

    i = 0
    for ch in tag_s:
        if i < len(input_s) and ch == input_s[i]:
            i += 1
    return i == len(input_s)


def _normalize_tag_text(text: str) -> str:
    """Normalize tag text for more stable fuzzy matching."""

    return "".join(ch.lower() for ch in text if ch.isalnum())


def fuzzy_match_tag(input_tag: str) -> list[str]:
    """Fuzzy-match a user tag against the official selectable tag set."""

    input_tag = input_tag.strip()
    if not input_tag:
        return []

    input_lower = input_tag.lower()
    input_compact = _normalize_tag_text(input_tag)
    alias = TAG_ALIASES.get(input_lower) or TAG_ALIASES.get(input_compact)
    if alias and alias in KNOWN_TAG_IDS:
        return [alias]

    matches: List[str] = []
    seq_matches: List[str] = []

    for tag in ALL_TAGS:
        if input_tag == tag:
            return [tag]

        tag_lower = tag.lower()
        tag_compact = _normalize_tag_text(tag)

        if input_lower in tag_lower:
            matches.append(tag)
            continue

        if input_compact and (
            input_compact == tag_compact
            or input_compact in tag_compact
            or tag_compact in input_compact
        ):
            matches.append(tag)
            continue

        if _char_seq_match(input_tag, tag):
            seq_matches.append(tag)

    return (matches + seq_matches)[:10]


def get_tag_id(tag_name: str) -> Optional[int]:
    """Return the official tag ID for a known selectable tag."""

    return KNOWN_TAG_IDS.get(tag_name)
