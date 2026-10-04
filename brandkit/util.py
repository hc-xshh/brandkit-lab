"""Small shared helpers: colour maths, CSS scraping, deterministic JSON."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
FUNC_COLOR_RE = re.compile(r"rgba?\(([^)]*)\)")
GENERIC_FAMILIES = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy",
    "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded",
    "math", "emoji", "fangsong", "inherit", "initial", "unset", "revert",
}


def norm_hex(value: str) -> str:
    """Normalise ``#abc`` / ``#abcd`` / ``#aabbcc`` / ``#aabbccdd`` to ``#aabbcc``."""
    raw = value.lstrip("#").lower()
    if len(raw) in (3, 4):
        raw = "".join(ch * 2 for ch in raw[:3])
    return "#" + raw[:6]


def parse_color(value: str) -> str | None:
    """Return a normalised hex for the first colour in ``value``, else ``None``."""
    m = HEX_RE.search(value)
    if m:
        return norm_hex(m.group(0))
    m = FUNC_COLOR_RE.search(value)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) >= 3:
            try:
                rgb = [max(0, min(255, int(float(p)))) for p in parts[:3]]
            except ValueError:
                return None
            return "#{:02x}{:02x}{:02x}".format(*rgb)
    return None


def _srgb_channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    h = norm_hex(hex_color).lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio, rounded to two decimals."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def saturation(hex_color: str) -> float:
    """HSV saturation in ``0..1``; 0 means greyscale."""
    h = norm_hex(hex_color).lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0.0
    return round((mx - mn) / mx, 4)


def mix(a: str, b: str, weight: float) -> str:
    """Blend ``a`` towards ``b`` by ``weight`` (0..1), in sRGB space."""
    wa = norm_hex(a).lstrip("#")
    wb = norm_hex(b).lstrip("#")
    out = []
    for i in (0, 2, 4):
        ca = int(wa[i : i + 2], 16)
        cb = int(wb[i : i + 2], 16)
        val = round(ca + (cb - ca) * weight)
        out.append(max(0, min(255, val)))
    return "#{:02x}{:02x}{:02x}".format(*out)


def darken(hex_color: str, factor: float, surface: str = "#000000") -> str:
    """Move ``hex_color`` towards ``surface`` by ``factor`` (0..1)."""
    return mix(hex_color, surface, factor)


def lighten(hex_color: str, factor: float, surface: str = "#ffffff") -> str:
    """Move ``hex_color`` towards ``surface`` by ``factor`` (0..1)."""
    return mix(hex_color, surface, factor)


def text_on(background: str, light: str = "#ffffff", dark: str = "#0b0b0c") -> str:
    """Pick whichever of ``light``/``dark`` contrasts more with ``background``."""
    return light if contrast_ratio(light, background) >= contrast_ratio(dark, background) else dark


def dumps_stable(obj: object) -> str:
    """Serialise to canonical JSON: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "source"
