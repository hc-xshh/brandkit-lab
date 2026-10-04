"""Measure a brand source page into ``metrics.json``.

This is the only module that looks at the outside world: either a local HTML
file, or -- when explicitly asked with ``--source-url`` -- a single polite GET
with a plain user agent. Nothing here needs a network, a browser or a
third-party parser.

What is measured (all of it from declarations the page itself makes):

* palette           -- hex frequencies, split by how the colour is used
* font roles        -- the families actually referenced by heading/body rules
* radius scale      -- distinct ``border-radius`` values
* elevation         -- distinct ``box-shadow`` values
* spacing           -- distinct padding/margin/gap lengths
* copy slots        -- h1 / h2s / leads / bodies / ctas / eyebrows / meta / footer

Output is byte-stable: no timestamps, sorted keys, canonical JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from . import htmltree
from .util import (
    GENERIC_FAMILIES,
    contrast_ratio,
    norm_hex,
    parse_color,
    saturation,
    sha256_text,
    slugify,
    text_on,
)

USER_AGENT = "brandkit-lab/1.0 (+measured facts only; no crawling)"
DEFAULT_TIMEOUT = 20

HEADING_SELECTOR_RE = re.compile(r"\b(h1|h2|h3|heading|display|title|hero)\b", re.I)
BODY_SELECTOR_RE = re.compile(r"\b(html|body|p|main|:root|text|copy|paragraph)\b", re.I)
CTA_CLASS_HINTS = ("cta", "btn", "button")
LEAD_CLASS_HINTS = ("lead", "lede", "sub", "intro", "deck")
EYEBROW_CLASS_HINTS = ("eyebrow", "kicker", "tag", "label", "pill", "badge")
META_CLASS_HINTS = ("meta", "date", "note", "caption", "byline")

LENGTH_RE = re.compile(r"(-?\d*\.?\d+)(px|rem|em)", re.I)


# --------------------------------------------------------------------------
# CSS scraping
# --------------------------------------------------------------------------
def style_blocks(html: str) -> list[str]:
    return re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S | re.I)


def inline_styles(html: str) -> list[str]:
    return re.findall(r'style="([^"]*)"', html, flags=re.I)


def iter_declarations(css: str):
    """Yield ``(selector, property, value)`` for a plain CSS string."""
    cleaned = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    cleaned = re.sub(r"@(media|supports|layer|container)[^{]*\{", "", cleaned, flags=re.I)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", cleaned):
        selector = " ".join(match.group(1).split())
        for decl in match.group(2).split(";"):
            if ":" not in decl:
                continue
            prop, _, value = decl.partition(":")
            yield selector, prop.strip().lower(), value.strip()


def collect_declarations(html: str) -> list[tuple[str, str, str]]:
    decls: list[tuple[str, str, str]] = []
    for css in style_blocks(html):
        decls.extend(iter_declarations(css))
    root = htmltree.parse(html)
    for node in htmltree.iter_elements(root):
        inline = node.get("style")
        if inline:
            for decl in inline.split(";"):
                if ":" in decl:
                    prop, _, value = decl.partition(":")
                    decls.append((node.tag, prop.strip().lower(), value.strip()))
    return decls


def split_top_level(value: str, sep: str = ",") -> list[str]:
    """Split on ``sep``, ignoring separators inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def split_font_stack(value: str) -> list[str]:
    """Split a ``font-family`` value into individual families, quotes removed."""
    return [f.strip().strip("'\"") for f in split_top_level(value) if f.strip()]


#: One token of a `font` shorthand that is *not* a family: a size with a unit,
#: a line-height, a weight or a style keyword.
SHORTHAND_SIZE_RE = re.compile(
    r"^[\d.]+(?:px|rem|em|pt|%|vw|vh|ch|ex)?(?:\s*/\s*[\d.]+\S*)?$"
    r"|^(?:italic|oblique|small-caps|bold|bolder|lighter|normal)$"
)


def families_from_shorthand(value: str) -> list[str]:
    """Families from a ``font`` shorthand, skipping size, weight and line-height.

    `font: 700 32px/1.2 "Iowan Old Style", Georgia, serif` names one family in
    its first segment, and it is the part after the size. Splitting the segment
    on commas alone would hand the kit `32px/1.2 "Iowan Old Style"` as a font
    family and ship a nonsense token.

    The family is whatever follows the *last* shorthand token, so a family whose
    name happens to contain digits ("B612 Mono") survives: only tokens that look
    like a size, a weight, a style or a line-height are skipped.
    """
    first, *rest = split_top_level(value)
    tokens = first.split()
    start = 0
    for index, token in enumerate(tokens):
        if SHORTHAND_SIZE_RE.match(token):
            start = index + 1
    first = " ".join(tokens[start:])
    return [f.strip().strip("'\"") for f in (first, *rest) if f.strip()]


def measure_palette(decls: list[tuple[str, str, str]]) -> dict:
    background = Counter()
    foreground = Counter()
    borders = Counter()
    page_surface = Counter()
    page_text = Counter()
    page_selector = re.compile(r"^(html|body|:root|html\s*,\s*body)$", re.I)
    for selector, prop, value in decls:
        found = [norm_hex(h) for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", value)]
        if not found:
            color = parse_color(value)
            found = [color] if color and "gradient" not in value else []
        on_page_element = bool(page_selector.match(selector))
        if prop.startswith("background") or prop in ("fill", "outline-color"):
            background.update(found)
            if on_page_element:
                page_surface.update(found)
        elif prop in ("color", "caret-color", "text-decoration-color") or prop.startswith("--"):
            foreground.update(found)
            if on_page_element:
                page_text.update(found)
        elif prop.startswith("border") or prop in ("box-shadow", "outline"):
            borders.update(found)
    every = Counter()
    for counter in (background, foreground, borders):
        every.update(counter)
    by_count = lambda counter: dict(  # noqa: E731 - tiny local sort key
        sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return {
        "counts": by_count(every),
        "background_counts": by_count(background),
        "foreground_counts": by_count(foreground),
        "border_counts": by_count(borders),
        "page_surface_counts": by_count(page_surface),
        "page_text_counts": by_count(page_text),
    }


def resolve_color_roles(palette: dict) -> tuple[dict[str, str], list[str]]:
    """Turn raw colour frequencies into the eight colour roles we need.

    The page surface is whatever ``html``/``body``/``:root`` declares -- not the
    loudest colour on the page. Getting this wrong is how a dark hero section
    ends up as the paper colour of an otherwise cream site.
    """
    derived: list[str] = []
    backgrounds = list(palette["background_counts"]) or ["#ffffff"]
    foregrounds = list(palette["foreground_counts"]) or ["#111111"]
    borders = list(palette["border_counts"])
    every = list(palette["counts"])

    page_surfaces = list(palette.get("page_surface_counts", {}))
    page_texts = list(palette.get("page_text_counts", {}))
    paper = page_surfaces[0] if page_surfaces else backgrounds[0]

    siblings = [
        c
        for c in backgrounds
        if c != paper and (_is_light(c) == _is_light(paper))
    ]
    if siblings:
        paper_alt = siblings[0]
    else:
        # A brand that declares exactly one surface: derive a sibling surface
        # by tinting the paper towards its own ink.
        paper_alt = _blend_towards(paper, "#000000", 0.05)
        derived.append("paper-alt")

    if page_texts:
        ink = page_texts[0]
    else:
        ink = next(
            (c for c in foregrounds if contrast_ratio(c, paper) >= 4.5),
            foregrounds[0],
        )
    if contrast_ratio(ink, paper) < 4.5:
        derived.append("ink")
    ink_muted = next((c for c in foregrounds if c != ink), "")
    if not ink_muted or contrast_ratio(ink_muted, paper) < 3.0:
        ink_muted = _blend_towards(ink, paper, 0.42)
        derived.append("ink-muted")

    chroma_candidates = [c for c in every if saturation(c) >= 0.10 and c != paper]
    if chroma_candidates:
        def score(color: str) -> tuple[float, int]:
            return (saturation(color) * 10 + palette["counts"][color], palette["counts"][color])

        primary = max(chroma_candidates, key=score)
    else:
        primary = ink
        derived.append("primary")

    primary_ink = text_on(primary)
    border = borders[0] if borders else _blend_towards(paper, ink, 0.14)
    if not borders:
        derived.append("border")

    # The accent is the *second* chromatic colour when the brand has two, and
    # the brand's only colour when the page is otherwise greyscale. Colours that
    # already hold an ink/surface role are not candidates.
    taken = {ink, ink_muted, paper, paper_alt}
    chroma_candidates = [
        c for c in chroma_candidates if c not in taken
    ]
    if primary in taken and chroma_candidates:
        primary = max(chroma_candidates, key=score)
    secondary = [c for c in chroma_candidates if c != primary]
    if secondary:
        accent = secondary[0]
    elif saturation(primary) >= 0.10:
        accent = primary
    else:
        accent = _blend_towards(ink, "#ffffff", 0.1)
        derived.append("accent")

    return (
        {
            "paper": paper,
            "paper-alt": paper_alt,
            "ink": ink,
            "ink-muted": ink_muted,
            "primary": primary,
            "primary-ink": primary_ink,
            "border": border,
            "accent": accent,
        },
        sorted(set(derived)),
    )


def _is_light(color: str) -> bool:
    from .util import relative_luminance

    return relative_luminance(color) > 0.5


def _blend_towards(a: str, b: str, weight: float) -> str:
    from .util import mix

    return mix(a, b, weight)


# --------------------------------------------------------------------------
# typography, radius, elevation, spacing
# --------------------------------------------------------------------------
def measure_fonts(decls: list[tuple[str, str, str]]) -> dict:
    heading_counter: Counter = Counter()
    body_counter: Counter = Counter()
    all_families: Counter = Counter()
    for selector, prop, value in decls:
        if prop not in ("font-family", "font"):
            continue
        # `font` is a shorthand and mixes size, weight and line-height into the
        # value; `font-family` is not. Only the shorthand needs the extra pass.
        splitter = families_from_shorthand if prop == "font" else split_font_stack
        families = [f for f in splitter(value) if f]
        if not families:
            continue
        all_families.update(families)
        named = [f for f in families if f.lower() not in GENERIC_FAMILIES]
        if not named:
            continue
        if HEADING_SELECTOR_RE.search(selector):
            heading_counter[named[0]] += 1
        elif BODY_SELECTOR_RE.search(selector):
            body_counter[named[0]] += 1
    derived: list[str] = []
    heading = heading_counter.most_common(1)[0][0] if heading_counter else ""
    body = body_counter.most_common(1)[0][0] if body_counter else ""
    if not heading:
        heading = body or "system-ui"
        derived.append("heading-font")
    if not body:
        body = heading
        derived.append("body-font")
    return {
        "families": [f for f, _ in all_families.most_common()],
        "roles": {"heading-font": heading, "body-font": body},
        "derived": sorted(derived),
    }


def measure_radius(decls: list[tuple[str, str, str]]) -> dict:
    values: list[float] = []
    for _selector, prop, value in decls:
        if "border-radius" not in prop:
            continue
        for num, unit in LENGTH_RE.findall(value):
            if unit.lower() == "px":
                values.append(abs(float(num)))
        if "50%" in value:
            values.append(9999.0)
    distinct = sorted({round(v, 2) for v in values})
    non_pill = [v for v in distinct if v < 100]
    pill_declared = any(v >= 100 for v in distinct)
    derived: list[str] = []
    if non_pill:
        cta = non_pill[0]
        card = non_pill[-1]
    else:
        cta = card = 0.0
        derived.extend(["radius-cta", "radius-card"])
    return {
        "scale": [f"{v:g}px" for v in distinct],
        "roles": {"cta": f"{cta:g}px", "card": f"{card:g}px", "pill": "9999px"},
        "pill_declared": pill_declared,
        "derived": sorted(derived + ([] if pill_declared else ["radius-pill"])),
    }


def measure_elevation(decls: list[tuple[str, str, str]]) -> dict:
    """One elevation value per ``box-shadow`` declaration.

    A designer's idea of "card elevation" is the whole declaration the designer
    wrote -- the tight ring plus the ambient blur together -- not each of its
    components. Declarations are ranked by how loud they are, quietest first.
    """
    declared: list[str] = []
    for _selector, prop, value in decls:
        if prop != "box-shadow":
            continue
        candidate = " ".join(value.split())
        if not candidate or candidate.lower() == "none":
            continue
        if candidate not in declared:
            declared.append(candidate)
    derived: list[str] = []
    if declared:
        ordered = sorted(declared, key=lambda s: (_shadow_weight(s), s))
        card = ordered[0]
        if len(ordered) > 1:
            raised = ordered[-1]
        else:
            raised = _scale_shadow(card, 1.9)
            derived.append("shadow-raised")
    else:
        card = "0 1px 2px rgba(16,18,24,0.06), 0 8px 24px rgba(16,18,24,0.08)"
        raised = "0 2px 4px rgba(16,18,24,0.08), 0 16px 40px rgba(16,18,24,0.14)"
        derived.extend(["shadow-card", "shadow-raised"])
    return {"values": declared, "roles": {"card": card, "raised": raised}, "derived": sorted(derived)}


def _shadow_weight(shadow: str) -> float:
    """Total length of a shadow's offsets and blurs -- a proxy for loudness."""
    return round(sum(abs(float(num)) for num, _unit in LENGTH_RE.findall(shadow)), 2)


def _scale_shadow(shadow: str, factor: float) -> str:
    def bump(match: re.Match[str]) -> str:
        return f"{round(float(match.group(1)) * factor)}px"

    return re.sub(r"(-?\d*\.?\d+)px", bump, shadow)


def measure_spacing(decls: list[tuple[str, str, str]]) -> list[str]:
    sizes: set[float] = set()
    for _selector, prop, value in decls:
        if not prop.startswith(("padding", "margin", "gap", "row-gap", "column-gap")):
            continue
        for num, unit in LENGTH_RE.findall(value):
            amount = float(num)
            if unit.lower() == "rem":
                amount *= 16
            if 0 <= amount <= 160:
                sizes.add(round(amount, 2))
    return [f"{v:g}px" for v in sorted(sizes)]


# --------------------------------------------------------------------------
# copy slots
# --------------------------------------------------------------------------
def classify_copy(tag: str, classes: str, in_footer: bool) -> str | None:
    """Map an element onto a copy role.

    Class names win over tag names: ``<p class="eyebrow">`` is an eyebrow, not a
    body paragraph. Tag names are the fallback.
    """
    cls = classes.lower()
    if any(h in cls for h in EYEBROW_CLASS_HINTS):
        return "eyebrow"
    if any(h in cls for h in META_CLASS_HINTS):
        return "meta"
    if in_footer:
        return "footer"
    if tag == "h1":
        return "h1"
    if tag == "h2":
        return "h2"
    if tag == "h3":
        return "h3"
    if tag in ("a", "button"):
        return "cta" if any(h in cls for h in CTA_CLASS_HINTS) else "link"
    if tag == "p":
        return "lead" if any(h in cls for h in LEAD_CLASS_HINTS) else "body"
    if tag == "li":
        return "body"
    if tag in ("span", "small", "div", "strong", "em", "label", "figcaption"):
        return None
    if tag == "time":
        return "meta"
    return None


def measure_copy_pool(html: str) -> dict[str, list[str]]:
    root = htmltree.parse(html)
    pools: dict[str, list[str]] = {}
    footers = set()
    for footer in root.find_all(tag="footer"):
        for node in [footer, *htmltree.iter_elements(footer)]:
            footers.add(id(node))

    def rec(node: htmltree.Node, in_footer: bool) -> None:
        for child in node.elements():
            inside = in_footer or child.tag == "footer" or id(child) in footers
            key = classify_copy(child.tag, child.get("class"), inside)
            if key and not child.find_all(tag="h1") and not child.find_all(tag="h2"):
                text = child.text().strip()
                if text and len(text) <= 480:
                    pool = pools.setdefault(key, [])
                    if text not in pool:
                        pool.append(text)
            rec(child, inside)

    rec(root, False)
    return dict(sorted(pools.items()))


# --------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------
def measure_html(html: str, source_id: str, kind: str, reference: str) -> dict:
    decls = collect_declarations(html)
    palette = measure_palette(decls)
    colors, color_derived = resolve_color_roles(palette)
    fonts = measure_fonts(decls)
    radius = measure_radius(decls)
    elevation = measure_elevation(decls)
    derived = sorted(
        set(color_derived) | set(fonts["derived"]) | set(radius["derived"]) | set(elevation["derived"])
    )
    return {
        "schema": "brandkit/metrics@1",
        "source": {
            "id": source_id,
            "kind": kind,
            "reference": reference,
            "sha256": sha256_text(html),
            "bytes": len(html.encode("utf-8")),
        },
        "palette": palette,
        "roles": colors,
        "fonts": {"families": fonts["families"], "roles": fonts["roles"]},
        "radius": {"scale": radius["scale"], "roles": radius["roles"]},
        "elevation": {"values": elevation["values"], "roles": elevation["roles"]},
        "spacing": measure_spacing(decls),
        "copy_pool": measure_copy_pool(html),
        "derived_tokens": derived,
        "declarations": len(decls),
    }


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """One polite GET. No retries, no crawling, no cookie games."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 (explicit user request)
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, "replace")


def measure_source(path: str | Path) -> dict:
    """Measure a local HTML file; convenience wrapper for tests and eval.

    The recorded ``reference`` is made relative to the working directory when
    that is possible: a kit's fingerprint must describe the brand, not the
    directory somebody happened to check the repository out into.
    """
    p = Path(path)
    html = p.read_text(encoding="utf-8")
    reference = str(p)
    if p.is_absolute():
        try:
            reference = str(p.relative_to(Path.cwd()))
        except ValueError:
            reference = str(p)
    return measure_html(html, slugify(p.stem), "file", reference)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure brand facts from an HTML source page.")
    ap.add_argument("--source", help="local HTML file to measure")
    ap.add_argument("--source-url", help="fetch exactly one URL and measure it instead")
    ap.add_argument("--id", help="source id (default: file stem / host)")
    ap.add_argument("--out", required=True, help="path of the metrics.json to write")
    ap.add_argument("--save-html", help="also save the fetched/read HTML here")
    args = ap.parse_args(argv)

    if bool(args.source) == bool(args.source_url):
        ap.error("give exactly one of --source / --source-url")

    if args.source:
        path = Path(args.source)
        html = path.read_text(encoding="utf-8")
        source_id = args.id or slugify(path.stem)
        kind, reference = "file", str(path)
    else:
        try:
            html = fetch(args.source_url)
        except urllib.error.URLError as exc:  # pragma: no cover - network path
            print(f"error: could not fetch {args.source_url}: {exc}", file=sys.stderr)
            return 2
        from urllib.parse import urlparse

        source_id = args.id or slugify(urlparse(args.source_url).netloc or "url")
        kind, reference = "url", args.source_url

    metrics = measure_html(html, source_id, kind, reference)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    if args.save_html:
        Path(args.save_html).write_text(html, encoding="utf-8")

    print(f"measured {source_id}: {metrics['source']['bytes']} bytes, "
          f"{len(metrics['palette']['counts'])} colours, "
          f"{len(metrics['fonts']['families'])} families, "
          f"{sum(len(v) for v in metrics['copy_pool'].values())} copy candidates")
    print(f"  paper {metrics['roles']['paper']}  ink {metrics['roles']['ink']}  "
          f"primary {metrics['roles']['primary']}  "
          f"heading {metrics['fonts']['roles']['heading-font']!r}  "
          f"derived tokens: {metrics['derived_tokens']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
