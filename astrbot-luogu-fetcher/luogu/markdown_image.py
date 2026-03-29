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
        _WINDOWS_FONT_DIR / "FandolSong-Regular.otf",
        Path(r"C:/texlive/2024/texmf-dist/fonts/opentype/public/fandol/FandolSong-Regular.otf"),
        Path(r"C:/texlive/2023/texmf-dist/fonts/opentype/public/fandol/FandolSong-Regular.otf"),
        Path(r"C:/Program Files/MiKTeX/fonts/opentype/public/fandol/FandolSong-Regular.otf"),
        Path(r"C:/Users/Laptop/AppData/Local/Programs/MiKTeX/fonts/opentype/public/fandol/FandolSong-Regular.otf"),
        _WINDOWS_FONT_DIR / "NotoSansSC-VF.ttf",
        _WINDOWS_FONT_DIR / "Noto Sans SC (TrueType).otf",
        _WINDOWS_FONT_DIR / "Noto Sans SC Medium (TrueType).otf",
        _WINDOWS_FONT_DIR / "msyh.ttc",
        _WINDOWS_FONT_DIR / "simsun.ttc",
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
_TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")

_TITLE_TEXT_SIZE = 34
_HEADING_TEXT_SIZE = 29
_BODY_TEXT_SIZE = 24
_CODE_TEXT_SIZE = 22
_TABLE_TEXT_SIZE = 22

_PAGE_BG = "#f7f1e6"
_TEXT_COLOR = "#2a241d"
_TITLE_COLOR = "#241d16"
_HEADING_COLOR = "#8c3d21"
_RULE_COLOR = "#d6c3a5"
_CODE_BG = "#2d2924"
_TABLE_BORDER = "#cdb99a"
_TABLE_HEADER_BG = "#ead8b9"
_TABLE_CELL_BG = "#fbf7ef"
_TABLE_ALT_BG = "#f4ebdc"


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
    lines = md_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0

    while index < len(lines):
        line = lines[index].rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            code_lines: List[str] = []
            index += 1
            while index < len(lines):
                candidate = lines[index].rstrip("\n")
                if candidate.strip().startswith("```"):
                    break
                code_lines.append(candidate)
                index += 1
            tokens.append(("code", "\n".join(code_lines).rstrip("\n")))
            index += 1
            continue

        if (
            index + 1 < len(lines)
            and _is_table_row(stripped)
            and _is_table_separator(lines[index + 1].strip())
        ):
            table_lines = [line, lines[index + 1].rstrip("\n")]
            index += 2
            while index < len(lines):
                candidate = lines[index].rstrip("\n")
                if not _is_table_row(candidate.strip()):
                    break
                table_lines.append(candidate)
                index += 1
            tokens.append(("table", "\n".join(table_lines)))
            continue

        if not stripped:
            tokens.append(("blank", ""))
            index += 1
            continue

        if stripped.startswith("#"):
            tokens.append(("heading", stripped.lstrip("#").strip()))
            index += 1
            continue

        if stripped in _KNOWN_HEADINGS or _SAMPLE_HEADING_RE.match(stripped):
            tokens.append(("heading", stripped))
            index += 1
            continue

        if stripped.startswith(("- ", "* ")):
            tokens.append(("bullet", stripped[2:].strip()))
            index += 1
            continue

        tokens.append(("paragraph", line))
        index += 1
    return tokens


def _is_table_row(stripped: str) -> bool:
    if not stripped or stripped.startswith("```"):
        return False
    return "|" in stripped and stripped.count("|") >= 2


def _is_table_separator(stripped: str) -> bool:
    if not stripped:
        return False
    parts = [part.strip() for part in stripped.strip("|").split("|")]
    return bool(parts) and all(_TABLE_SEPARATOR_RE.fullmatch(part or "") for part in parts)


def _split_table_row(row: str) -> List[str]:
    stripped = row.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


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
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b, a = pixels[x, y]
                if r >= 248 and g >= 248 and b >= 248:
                    pixels[x, y] = (255, 255, 255, 0)
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


def _build_table_layout(
    draw: ImageDraw.ImageDraw,
    table_text: str,
    max_width: int,
) -> Dict[str, object]:
    raw_lines = [line for line in table_text.splitlines() if line.strip()]
    if len(raw_lines) < 2:
        raise ValueError("table block is incomplete")

    rows = [_split_table_row(raw_lines[0])]
    rows.extend(_split_table_row(line) for line in raw_lines[2:])
    col_count = max(len(row) for row in rows) if rows else 1

    border_width = 2
    cell_padding_x = 14
    cell_padding_y = 10
    usable_width = max_width - border_width * (col_count + 1)
    col_width = max(140, usable_width // max(1, col_count))
    table_width = border_width + col_count * (col_width + border_width)

    table_rows: List[Dict[str, object]] = []
    total_height = border_width

    for row_index, row in enumerate(rows):
        cell_lines: List[Sequence[Sequence[Fragment]]] = []
        row_height = 0
        for col_index in range(col_count):
            cell_text = row[col_index] if col_index < len(row) else ""
            wrapped = _wrap_fragments(
                draw,
                cell_text,
                col_width - cell_padding_x * 2,
                size=_TABLE_TEXT_SIZE,
                fill=_TEXT_COLOR,
            )
            block_height = sum(_line_height(line, _TABLE_TEXT_SIZE + 4) for line in wrapped)
            cell_lines.append(wrapped)
            row_height = max(row_height, block_height)
        row_height += cell_padding_y * 2
        table_rows.append(
            {
                "cells": cell_lines,
                "height": row_height,
                "header": row_index == 0,
            }
        )
        total_height += row_height + border_width

    return {
        "rows": table_rows,
        "col_width": col_width,
        "col_count": col_count,
        "width": table_width,
        "height": total_height,
        "border_width": border_width,
        "cell_padding_x": cell_padding_x,
        "cell_padding_y": cell_padding_y,
    }


def _draw_table(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    table_layout: Dict[str, object],
    *,
    x: int,
    y: int,
) -> int:
    rows = table_layout["rows"]
    col_width = int(table_layout["col_width"])
    col_count = int(table_layout["col_count"])
    border_width = int(table_layout["border_width"])
    cell_padding_x = int(table_layout["cell_padding_x"])
    cell_padding_y = int(table_layout["cell_padding_y"])
    table_width = int(table_layout["width"])
    table_height = int(table_layout["height"])

    draw.rounded_rectangle(
        (x, y, x + table_width, y + table_height),
        radius=14,
        outline=_TABLE_BORDER,
        width=border_width,
        fill=_TABLE_BORDER,
    )

    cursor_y = y + border_width
    for row_index, row in enumerate(rows):
        row_height = int(row["height"])
        fill = _TABLE_HEADER_BG if row["header"] else (_TABLE_CELL_BG if row_index % 2 else _TABLE_ALT_BG)
        cursor_x = x + border_width
        for cell_lines in row["cells"]:
            draw.rectangle(
                (cursor_x, cursor_y, cursor_x + col_width, cursor_y + row_height),
                fill=fill,
            )
            text_y = cursor_y + cell_padding_y
            text_y = _draw_lines(
                image,
                draw,
                cell_lines,
                x=cursor_x + cell_padding_x,
                y=text_y,
                minimum_height=_TABLE_TEXT_SIZE + 4,
            )
            cursor_x += col_width + border_width
        cursor_y += row_height + border_width

    return y + table_height


def render_markdown_to_image(md_content: str, title: str | None = None) -> bytes:
    if not md_content or not md_content.strip():
        raise ValueError("markdown content is empty")

    canvas_width = 1380
    outer_padding = 42
    inner_width = canvas_width - outer_padding * 2

    probe = Image.new("RGB", (canvas_width, 200), _PAGE_BG)
    probe_draw = ImageDraw.Draw(probe)

    layout: List[Tuple[str, Sequence[Sequence[Fragment]]]] = []
    total_height = outer_padding

    if title and title.strip():
        title_lines = _wrap_fragments(
            probe_draw,
            title.strip(),
            inner_width,
            size=_TITLE_TEXT_SIZE,
            fill=_TITLE_COLOR,
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
                size=_HEADING_TEXT_SIZE,
                fill=_HEADING_COLOR,
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
                        size=_CODE_TEXT_SIZE,
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
                size=_BODY_TEXT_SIZE,
                fill=_TEXT_COLOR,
            )
            layout.append((kind, lines))
            total_height += sum(_line_height(line, 28) for line in lines) + 10
        elif kind == "table":
            table_layout = _build_table_layout(probe_draw, text, inner_width)
            layout.append((kind, table_layout))
            total_height += int(table_layout["height"]) + 16
        else:
            lines = _wrap_fragments(
                probe_draw,
                text,
                inner_width,
                size=_BODY_TEXT_SIZE,
                fill=_TEXT_COLOR,
            )
            layout.append((kind, lines))
            total_height += sum(_line_height(line, 28) for line in lines) + 10
        last_kind = kind

    total_height += outer_padding
    image = Image.new("RGB", (canvas_width, max(total_height, 400)), _PAGE_BG)
    draw = ImageDraw.Draw(image)

    y = outer_padding
    if title and title.strip():
        title_lines = layout.pop(0)[1]
        y = _draw_lines(image, draw, title_lines, x=outer_padding, y=y, minimum_height=40)
        draw.line(
            (outer_padding, y - 6, canvas_width - outer_padding, y - 6),
            fill=_RULE_COLOR,
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
                fill=_CODE_BG,
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

        if kind == "table":
            y = _draw_table(
                image,
                draw,
                lines,
                x=outer_padding,
                y=y,
            )
            y += 16
            continue

        y = _draw_lines(image, draw, lines, x=outer_padding, y=y, minimum_height=28)
        y += 10

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
