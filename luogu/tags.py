"""Luogu tag helpers backed by an official tag-catalog snapshot."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Dict, List, Optional
import unicodedata

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
    "o2优化": "O2优化",
    "kd树": "K-D Tree",
    "kdtree": "K-D Tree",
    "kd-tree": "K-D Tree",
}


_BRACKET_CONTENT_RE = re.compile(r"[\(\[（【].*?[\)\]】）]")
_ASCII_CHUNK_RE = re.compile(r"[A-Za-z0-9\*]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _char_seq_match(input_s: str, tag_s: str) -> bool:
    """Whether all chars in ``input_s`` appear in order within ``tag_s``."""

    i = 0
    for ch in tag_s:
        if i < len(input_s) and ch == input_s[i]:
            i += 1
    return i == len(input_s)


def _normalize_tag_text(text: str) -> str:
    """Normalize tag text for more stable fuzzy matching."""

    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(ch.lower() for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _strip_bracket_content(text: str) -> str:
    return _BRACKET_CONTENT_RE.sub(" ", unicodedata.normalize("NFKC", str(text or ""))).strip()


def _extract_ascii_chunks(text: str) -> List[str]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return [chunk.lower() for chunk in _ASCII_CHUNK_RE.findall(normalized)]


def _extract_cjk_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(_CJK_RE.findall(normalized))


def _build_tag_variants(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    compact = _normalize_tag_text(normalized)
    stripped = _strip_bracket_content(normalized)
    stripped_compact = _normalize_tag_text(stripped)
    ascii_chunks = _extract_ascii_chunks(normalized)
    ascii_joined = "".join(ascii_chunks)
    ascii_initials = "".join(chunk[0] for chunk in ascii_chunks if chunk)
    cjk_compact = _normalize_tag_text(_extract_cjk_text(normalized))

    variants = {
        compact,
        stripped_compact,
        ascii_joined,
        ascii_initials,
        cjk_compact,
    }
    variants.update(_normalize_tag_text(chunk) for chunk in ascii_chunks)
    if stripped and stripped != normalized:
        variants.add(_normalize_tag_text(stripped))
        variants.add(_normalize_tag_text(_extract_cjk_text(stripped)))

    return {variant for variant in variants if variant}


def _build_tag_match_spec(tag: str) -> Dict[str, object]:
    normalized = unicodedata.normalize("NFKC", tag).strip()
    compact = _normalize_tag_text(normalized)
    variants = _build_tag_variants(normalized)
    return {
        "name": tag,
        "lower": normalized.lower(),
        "compact": compact,
        "variants": tuple(sorted(variants, key=lambda item: (-len(item), item))),
    }


TAG_MATCH_SPECS = tuple(_build_tag_match_spec(tag) for tag in ALL_TAGS)


def _score_tag_match(input_tag: str, query_variants: set[str], spec: Dict[str, object]) -> int:
    tag = str(spec["name"])
    tag_lower = str(spec["lower"])
    tag_compact = str(spec["compact"])
    tag_variants = set(spec["variants"])
    input_lower = input_tag.lower()
    input_compact = _normalize_tag_text(input_tag)

    if input_tag == tag:
        return 2000
    if input_lower == tag_lower:
        return 1900
    if input_compact and input_compact == tag_compact:
        return 1800

    exact_hits = [variant for variant in query_variants if len(variant) >= 2 and variant in tag_variants]
    score = 0
    if exact_hits:
        score += 1100 + len(exact_hits) * 80
        score += sum(min(len(hit), 12) for hit in exact_hits)

    for variant in query_variants:
        if len(variant) < 2:
            continue
        if variant in tag_compact and variant != tag_compact:
            score = max(score, 900 + min(len(variant), 40))
        if tag_compact in variant and len(tag_compact) >= 3 and variant != tag_compact:
            score = max(score, 820 + min(len(tag_compact), 40))

    if input_tag and _char_seq_match(input_tag, tag):
        score = max(score, 720)
    if input_compact and tag_compact and _char_seq_match(input_compact, tag_compact):
        score = max(score, 760)

    for variant in query_variants:
        if len(variant) < 3:
            continue
        for target in tag_variants:
            if len(target) < 3:
                continue
            ratio = SequenceMatcher(None, variant, target).ratio()
            if ratio >= 0.92:
                score = max(score, 860)
            elif ratio >= 0.84:
                score = max(score, 780)
            elif ratio >= 0.76:
                score = max(score, 700)

    return score


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

    query_variants = _build_tag_variants(input_tag)
    if input_compact:
        query_variants.add(input_compact)

    scored_matches = []
    for spec in TAG_MATCH_SPECS:
        score = _score_tag_match(input_tag, query_variants, spec)
        if score <= 0:
            continue
        scored_matches.append((score, len(str(spec["name"])), str(spec["name"])))

    scored_matches.sort(key=lambda item: (-item[0], item[1], item[2]))
    if not scored_matches:
        return []
    top_score = scored_matches[0][0]
    min_score = max(700, top_score - 180)
    return [tag for score, _, tag in scored_matches if score >= min_score][:10]


def get_tag_id(tag_name: str) -> Optional[int]:
    """Return the official tag ID for a known selectable tag."""

    return KNOWN_TAG_IDS.get(tag_name)
