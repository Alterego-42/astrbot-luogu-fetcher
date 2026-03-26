"""
将洛谷题面 Markdown 渲染为图片。

目标不是完整实现 Markdown 排版，而是稳定地把已提取的题面文本、
标题和代码块渲染成可阅读的长图，优先替代网页截图。
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


_WINDOWS_FONT_DIR = Path("C:/Windows/Fonts")
_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
_FONT_GROUPS = {
    "sc": [
        _WINDOWS_FONT_DIR / "NotoSansSC-VF.ttf",
        _WINDOWS_FONT_DIR / "Noto Sans SC (TrueType).otf",
        _WINDOWS_FONT_DIR / "Noto Sans SC Medium (TrueType).otf",
        _WINDOWS_FONT_DIR / "msyh.ttc",
        _WINDOWS_FONT_DIR / "simsun.ttc",
        _WINDOWS_FONT_DIR / "SimsunExtG.ttf",
    ],
    "kr": [
        _WINDOWS_FONT_DIR / "malgun.ttf",
        _WINDOWS_FONT_DIR / "malgunbd.ttf",
        _WINDOWS_FONT_DIR / "NotoSansSC-VF.ttf",
        _WINDOWS_FONT_DIR / "msyh.ttc",
    ],
    "jp": [
        _WINDOWS_FONT_DIR / "NotoSansJP-VF.ttf",
        _WINDOWS_FONT_DIR / "meiryo.ttc",
        _WINDOWS_FONT_DIR / "YuGothR.ttc",
        _WINDOWS_FONT_DIR / "msyh.ttc",
    ],
    "mono": [
        _WINDOWS_FONT_DIR / "consola.ttf",
        _WINDOWS_FONT_DIR / "consolab.ttf",
        _WINDOWS_FONT_DIR / "NotoSansSC-VF.ttf",
        _WINDOWS_FONT_DIR / "malgun.ttf",
        _WINDOWS_FONT_DIR / "meiryo.ttc",
        _WINDOWS_FONT_DIR / "msyh.ttc",
    ],
}

_KNOWN_HEADINGS = {
    "题目背景",
    "题目描述",
    "输入格式",
    "输出格式",
    "输入输出样例",
    "说明/提示",
    "题面翻译",
}
_SAMPLE_HEADING_RE = re.compile(r"^(输入|输出)\s*#\d+$")


def _contains_hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7af" for ch in text)


def _contains_kana(text: str) -> bool:
    return any("\u3040" <= ch <= "\u30ff" for ch in text)


def _resolve_font_key(text: str, mono: bool) -> str:
    if mono:
        return "mono"
    if _contains_hangul(text):
        return "kr"
    if _contains_kana(text):
        return "jp"
    return "sc"


def _load_font(text: str, size: int, *, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_key = _resolve_font_key(text, mono)
    cache_key = (f"{font_key}:{'mono' if mono else 'sans'}", size)
    cached = _FONT_CACHE.get(cache_key)
    if cached:
        return cached

    for path in _FONT_GROUPS[font_key]:
        if path.exists():
            try:
                font = ImageFont.truetype(str(path), size=size)
                _FONT_CACHE[cache_key] = font
                return font
            except Exception:
                continue

    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font
    return font


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(0, bbox[2] - bbox[0])


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    *,
    size: int,
    mono: bool = False,
) -> List[Tuple[str, ImageFont.ImageFont]]:
    text = text.rstrip()
    font = _load_font(text, size=size, mono=mono)
    if not text:
        return [("", font)]

    lines: List[Tuple[str, ImageFont.ImageFont]] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _measure(draw, candidate, font) > max_width:
            lines.append((current.rstrip(), font))
            current = char.lstrip()
            continue
        current = candidate

    if current:
        lines.append((current.rstrip(), font))
    return lines or [("", font)]


def _tokenize_markdown(md_content: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    in_code = False
    code_lines: List[str] = []

    for raw_line in md_content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                tokens.append(("code", "\n".join(code_lines).rstrip("\n")))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            tokens.append(("blank", ""))
            continue

        if stripped.startswith("#"):
            tokens.append(("heading", stripped.lstrip("#").strip()))
            continue

        if stripped in _KNOWN_HEADINGS or _SAMPLE_HEADING_RE.match(stripped):
            tokens.append(("heading", stripped))
            continue

        if stripped.startswith(("- ", "* ")):
            tokens.append(("bullet", stripped[2:].strip()))
            continue

        tokens.append(("paragraph", line))

    if code_lines:
        tokens.append(("code", "\n".join(code_lines).rstrip("\n")))
    return tokens


def render_markdown_to_image(md_content: str, title: str | None = None) -> bytes:
    if not md_content or not md_content.strip():
        raise ValueError("markdown content is empty")

    canvas_width = 1380
    outer_padding = 42
    inner_width = canvas_width - outer_padding * 2

    probe = Image.new("RGB", (canvas_width, 200), "#f4f1ea")
    draw = ImageDraw.Draw(probe)

    layout: List[Tuple[str, Sequence[Tuple[str, ImageFont.ImageFont]]]] = []
    total_height = outer_padding

    if title and title.strip():
        title_lines = _wrap_text(draw, title.strip(), inner_width, size=36)
        layout.append(("title", title_lines))
        total_height += len(title_lines) * 48 + 18

    tokens = _tokenize_markdown(md_content)
    last_kind = ""
    for kind, text in tokens:
        if kind == "blank":
            if last_kind not in ("", "blank"):
                total_height += 12
            last_kind = "blank"
            continue

        if kind == "heading":
            lines = _wrap_text(draw, text, inner_width, size=29)
            layout.append((kind, lines))
            total_height += len(lines) * 40 + 14
        elif kind == "code":
            code_lines = text.splitlines() or [""]
            wrapped: List[Tuple[str, ImageFont.ImageFont]] = []
            for line in code_lines:
                wrapped.extend(_wrap_text(draw, line or " ", inner_width - 36, size=22, mono=True))
            layout.append((kind, wrapped))
            total_height += len(wrapped) * 34 + 28
        elif kind == "bullet":
            wrapped = _wrap_text(draw, f"• {text}", inner_width, size=24)
            layout.append((kind, wrapped))
            total_height += len(wrapped) * 34 + 10
        else:
            wrapped = _wrap_text(draw, text, inner_width, size=24)
            layout.append((kind, wrapped))
            total_height += len(wrapped) * 34 + 10
        last_kind = kind

    total_height += outer_padding
    image = Image.new("RGB", (canvas_width, max(total_height, 400)), "#f4f1ea")
    draw = ImageDraw.Draw(image)

    y = outer_padding
    if title and title.strip():
        title_lines = layout.pop(0)[1]
        for line, font in title_lines:
            draw.text((outer_padding, y), line, fill="#1f2937", font=font)
            y += 48
        draw.line(
            (outer_padding, y - 6, canvas_width - outer_padding, y - 6),
            fill="#d4c7ad",
            width=2,
        )
        y += 12

    for kind, lines in layout:
        if kind == "heading":
            for line, font in lines:
                draw.text((outer_padding, y), line, fill="#8f2d1f", font=font)
                y += 40
            y += 14
            continue

        if kind == "code":
            box_height = len(lines) * 34 + 20
            draw.rounded_rectangle(
                (outer_padding, y, canvas_width - outer_padding, y + box_height),
                radius=14,
                fill="#1f2937",
            )
            code_y = y + 10
            for line, font in lines:
                draw.text((outer_padding + 18, code_y), line, fill="#f9fafb", font=font)
                code_y += 34
            y += box_height + 12
            continue

        for line, font in lines:
            draw.text((outer_padding, y), line, fill="#27303f", font=font)
            y += 34
        y += 10

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
