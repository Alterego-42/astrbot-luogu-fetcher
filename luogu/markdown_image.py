"""Render Luogu problem Markdown into a readable long image."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from matplotlib import mathtext
from matplotlib.font_manager import FontProperties
from PIL import Image, ImageDraw, ImageFont


_WINDOWS_FONT_DIR = Path("C:/Windows/Fonts")
_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
_MATH_CACHE: Dict[Tuple[str, int, str], Image.Image] = {}
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
_INLINE_MATH_RE = re.compile(
    r"(?P<block>\$\$(.+?)\$\$)|(?P<inline>\$(.+?)\$)|(?P<bracket>\\\[(.+?)\\\])|(?P<paren>\\\((.+?)\\\))"
)


@dataclass
class Fragment:
    kind: str
    width: int
    height: int
    text: str = ""
    font: ImageFont.ImageFont | None = None
    fill: str = "#27303f"
    image: Image.Image | None = None


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


def _load_font(
    text: str,
    size: int,
    *,
    mono: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def _measure_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> Tuple[int, int]:
    if not text:
        return 0, max(1, font.size if hasattr(font, "size") else 18)
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(0, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])


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


def _normalize_math_expression(raw: str) -> str:
    expr = raw.strip()
    if expr.startswith("$$") and expr.endswith("$$"):
        expr = expr[2:-2]
    elif expr.startswith("$") and expr.endswith("$"):
        expr = expr[1:-1]
    elif expr.startswith(r"\[") and expr.endswith(r"\]"):
        expr = expr[2:-2]
    elif expr.startswith(r"\(") and expr.endswith(r"\)"):
        expr = expr[2:-2]
    return expr.strip()


def _render_math_fragment(expr: str, size: int, color: str) -> Image.Image | None:
    expr = _normalize_math_expression(expr)
    if not expr:
        return None

    cache_key = (expr, size, color)
    cached = _MATH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        buffer = io.BytesIO()
        prop = FontProperties(size=max(12, int(size * 0.95)))
        mathtext.math_to_image(
            f"${expr}$",
            buffer,
            prop=prop,
            dpi=max(180, size * 8),
            format="png",
            color=color,
        )
        buffer.seek(0)
        image = Image.open(buffer).convert("RGBA")
        alpha_box = image.getbbox()
        if alpha_box:
            image = image.crop(alpha_box)
        _MATH_CACHE[cache_key] = image
        return image
    except Exception:
        return None


def _split_rich_segments(text: str) -> List[Tuple[str, str]]:
    segments: List[Tuple[str, str]] = []
    cursor = 0
    for match in _INLINE_MATH_RE.finditer(text):
        start, end = match.span()
        if start > cursor:
            segments.append(("text", text[cursor:start]))
        segments.append(("math", match.group(0)))
        cursor = end
    if cursor < len(text):
        segments.append(("text", text[cursor:]))
    return segments or [("text", text)]


def _text_fragment(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    size: int,
    fill: str,
    mono: bool = False,
) -> Fragment:
    font = _load_font(text or " ", size=size, mono=mono)
    width, height = _measure_text(draw, text or " ", font)
    return Fragment(
        kind="text",
        text=text,
        font=font,
        fill=fill,
        width=width,
        height=height,
    )


def _build_fragments(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    size: int,
    fill: str,
    mono: bool = False,
    allow_math: bool = True,
) -> List[Fragment]:
    fragments: List[Fragment] = []
    segments = _split_rich_segments(text) if allow_math else [("text", text)]

    for kind, value in segments:
        if kind == "math":
            image = _render_math_fragment(value, size=size, color=fill)
            if image is not None:
                fragments.append(
                    Fragment(
                        kind="math",
                        width=image.width,
                        height=image.height,
                        image=image,
                    )
                )
                continue

        for char in value:
            chunk = "    " if char == "\t" else char
            fragments.append(
                _text_fragment(draw, chunk, size=size, fill=fill, mono=mono)
            )

    return fragments or [_text_fragment(draw, "", size=size, fill=fill, mono=mono)]


def _wrap_fragments(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    *,
    size: int,
    fill: str,
    mono: bool = False,
    allow_math: bool = True,
) -> List[List[Fragment]]:
    fragments = _build_fragments(
        draw,
        text.rstrip(),
        size=size,
        fill=fill,
        mono=mono,
        allow_math=allow_math,
    )
    if not fragments:
        return [[_text_fragment(draw, "", size=size, fill=fill, mono=mono)]]

    lines: List[List[Fragment]] = []
    current: List[Fragment] = []
    current_width = 0

    def flush_line() -> None:
        nonlocal current, current_width
        while current and current[-1].kind == "text" and current[-1].text.isspace():
            current_width -= current[-1].width
            current.pop()
        if current:
            lines.append(current)
        current = []
        current_width = 0

    for fragment in fragments:
        if (
            current
            and current_width + fragment.width > max_width
            and not (fragment.kind == "text" and fragment.text.isspace())
        ):
            flush_line()

        if not current and fragment.kind == "text" and fragment.text.isspace():
            continue

        current.append(fragment)
        current_width += fragment.width

    flush_line()
    return lines or [[_text_fragment(draw, "", size=size, fill=fill, mono=mono)]]


def _line_height(line: Sequence[Fragment], minimum: int) -> int:
    return max([minimum, *[fragment.height for fragment in line]]) + 8


def _draw_lines(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    lines: Sequence[Sequence[Fragment]],
    *,
    x: int,
    y: int,
    minimum_height: int,
) -> int:
    for line in lines:
        line_height = _line_height(line, minimum_height)
        cursor_x = x
        for fragment in line:
            top = y + max(0, (line_height - fragment.height) // 2)
            if fragment.kind == "math" and fragment.image is not None:
                image.paste(fragment.image, (cursor_x, top), fragment.image)
            elif fragment.font is not None:
                draw.text(
                    (cursor_x, top),
                    fragment.text,
                    fill=fragment.fill,
                    font=fragment.font,
                )
            cursor_x += fragment.width
        y += line_height
    return y


def render_markdown_to_image(md_content: str, title: str | None = None) -> bytes:
    if not md_content or not md_content.strip():
        raise ValueError("markdown content is empty")

    canvas_width = 1380
    outer_padding = 42
    inner_width = canvas_width - outer_padding * 2

    probe = Image.new("RGB", (canvas_width, 200), "#f4f1ea")
    probe_draw = ImageDraw.Draw(probe)

    layout: List[Tuple[str, Sequence[Sequence[Fragment]]]] = []
    total_height = outer_padding

    if title and title.strip():
        title_lines = _wrap_fragments(
            probe_draw,
            title.strip(),
            inner_width,
            size=36,
            fill="#1f2937",
        )
        layout.append(("title", title_lines))
        total_height += sum(_line_height(line, 40) for line in title_lines) + 18

    last_kind = ""
    for kind, text in _tokenize_markdown(md_content):
        if kind == "blank":
            if last_kind not in ("", "blank"):
                total_height += 12
            last_kind = "blank"
            continue

        if kind == "heading":
            lines = _wrap_fragments(
                probe_draw,
                text,
                inner_width,
                size=29,
                fill="#8f2d1f",
            )
            layout.append((kind, lines))
            total_height += sum(_line_height(line, 32) for line in lines) + 14
        elif kind == "code":
            code_lines = text.splitlines() or [""]
            wrapped: List[List[Fragment]] = []
            for line in code_lines:
                wrapped.extend(
                    _wrap_fragments(
                        probe_draw,
                        line or " ",
                        inner_width - 36,
                        size=22,
                        fill="#f9fafb",
                        mono=True,
                        allow_math=False,
                    )
                )
            layout.append((kind, wrapped))
            total_height += sum(_line_height(line, 26) for line in wrapped) + 28
        elif kind == "bullet":
            lines = _wrap_fragments(
                probe_draw,
                f"- {text}",
                inner_width,
                size=24,
                fill="#27303f",
            )
            layout.append((kind, lines))
            total_height += sum(_line_height(line, 28) for line in lines) + 10
        else:
            lines = _wrap_fragments(
                probe_draw,
                text,
                inner_width,
                size=24,
                fill="#27303f",
            )
            layout.append((kind, lines))
            total_height += sum(_line_height(line, 28) for line in lines) + 10
        last_kind = kind

    total_height += outer_padding
    image = Image.new("RGB", (canvas_width, max(total_height, 400)), "#f4f1ea")
    draw = ImageDraw.Draw(image)

    y = outer_padding
    if title and title.strip():
        title_lines = layout.pop(0)[1]
        y = _draw_lines(image, draw, title_lines, x=outer_padding, y=y, minimum_height=40)
        draw.line(
            (outer_padding, y - 6, canvas_width - outer_padding, y - 6),
            fill="#d4c7ad",
            width=2,
        )
        y += 12

    for kind, lines in layout:
        if kind == "heading":
            y = _draw_lines(image, draw, lines, x=outer_padding, y=y, minimum_height=32)
            y += 14
            continue

        if kind == "code":
            box_height = sum(_line_height(line, 26) for line in lines) + 20
            draw.rounded_rectangle(
                (outer_padding, y, canvas_width - outer_padding, y + box_height),
                radius=14,
                fill="#1f2937",
            )
            y = _draw_lines(
                image,
                draw,
                lines,
                x=outer_padding + 18,
                y=y + 10,
                minimum_height=26,
            )
            y += 12
            continue

        y = _draw_lines(image, draw, lines, x=outer_padding, y=y, minimum_height=28)
        y += 10

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
