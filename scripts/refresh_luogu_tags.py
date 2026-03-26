from __future__ import annotations

import json
from pathlib import Path
from pprint import pformat
from urllib.error import URLError
from urllib.request import (
    ProxyHandler,
    Request,
    build_opener,
)


TAGS_URL = "https://www.luogu.com.cn/_lfe/tags/zh-CN"
PROXY_URL = "http://127.0.0.1:7897"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "luogu" / "tag_catalog.py"
USER_AGENT = "Mozilla/5.0 (compatible; astrbot-luogu-fetcher/refresh-tags)"


def _fetch_payload(proxy_url: str | None = None) -> dict:
    handlers = []
    if proxy_url:
        handlers.append(ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = build_opener(*handlers)
    request = Request(TAGS_URL, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=20) as response:
        return json.load(response)


def _load_official_payload() -> tuple[dict, str]:
    try:
        return _fetch_payload(), "direct"
    except Exception as direct_error:
        print(f"Direct fetch failed: {direct_error}")

    try:
        return _fetch_payload(PROXY_URL), f"proxy {PROXY_URL}"
    except Exception as proxy_error:
        raise RuntimeError(
            "Failed to fetch Luogu tag feed via direct connection and proxy 7897."
        ) from proxy_error


def _render_module(payload: dict, fetched_via: str) -> str:
    header = [
        '"""Auto-generated official Luogu tag catalog.',
        "",
        f"Source: {TAGS_URL}",
        "Do not edit by hand; run `python scripts/refresh_luogu_tags.py` instead.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"OFFICIAL_TAG_SOURCE = {TAGS_URL!r}",
        f"OFFICIAL_TAG_FETCH_MODE = {fetched_via!r}",
        f"OFFICIAL_TAG_VERSION = {payload.get('_version')!r}",
        f"OFFICIAL_TAG_LOCALE = {payload.get('_locale')!r}",
        "",
        f"OFFICIAL_TAG_TYPES = {pformat(payload.get('types', []), width=100, sort_dicts=False)}",
        "",
        f"OFFICIAL_TAG_ROWS = {pformat(payload.get('tags', []), width=100, sort_dicts=False)}",
        "",
    ]
    return "\n".join(header)


def main() -> int:
    payload, fetched_via = _load_official_payload()
    tags = payload.get("tags")
    types = payload.get("types")
    if not isinstance(tags, list) or not isinstance(types, list):
        raise RuntimeError("Unexpected Luogu tag payload shape.")

    OUTPUT_PATH.write_text(_render_module(payload, fetched_via), encoding="utf-8")
    print(
        f"Wrote {OUTPUT_PATH} with {len(tags)} tags, {len(types)} types via {fetched_via}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
