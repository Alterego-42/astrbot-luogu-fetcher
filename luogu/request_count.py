from __future__ import annotations

import re
from typing import Optional


_COUNT_MAX = 5
_COUNT_DIGIT_RE = re.compile(
    r"(?:再)?(?:来|找|搜|查|给我|推荐|整|做|出|随机来|随机挑|随便来|随便挑)\s*(\d+)\s*[道题个]"
)
_COUNT_CHINESE_RE = re.compile(
    r"(?:再)?(?:来|找|搜|查|给我|推荐|整|做|出|随机来|随机挑|随便来|随便挑)\s*([零一二两三四五六七八九十百千]+)\s*[道题个]"
)


def parse_simple_chinese_number(text: str) -> Optional[int]:
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000}
    value = str(text or "").strip()
    if not value:
        return None

    total = 0
    current = 0
    for ch in value:
        if ch in digits:
            current = digits[ch]
            continue
        unit = units.get(ch)
        if unit is None:
            return None
        if current == 0:
            current = 1
        total += current * unit
        current = 0
    total += current
    return total if total > 0 else None


def clamp_luogu_request_count(value: Optional[int]) -> int:
    if value is None:
        return 1
    return max(1, min(int(value), _COUNT_MAX))


def parse_luogu_requested_count(text: str) -> Optional[int]:
    raw = str(text or "").strip()
    if not raw:
        return None

    digit_match = _COUNT_DIGIT_RE.search(raw)
    if digit_match:
        return clamp_luogu_request_count(int(digit_match.group(1)))

    chinese_match = _COUNT_CHINESE_RE.search(raw)
    if chinese_match:
        parsed = parse_simple_chinese_number(chinese_match.group(1))
        if parsed is not None:
            return clamp_luogu_request_count(parsed)

    return None
