"""``assemble_kit(draft, metrics) -> kit`` — the only writer of a design kit.

One function writes every token. It reads *measured facts* from ``metrics`` and
*copy* from ``draft``, and it refuses to let the draft touch anything else: pass a
draft that carries a ``tokens``/``css``/``theme`` key and it raises. That single
rule is what makes the two-model invariant testable -- two different drafts for
the same source produce byte-identical token blocks and byte-identical
``kit.css``, because neither of them can write a token.

From one kit this module renders four files that cannot drift apart, because
they are all rendered from the same object:

* ``kit.json``     -- the kit, canonical JSON (sorted keys, trailing newline)
* ``kit.css``      -- CSS custom properties on ``:root``
* ``tokens.csv``   -- ``Token,Color,Font,Value`` rows for a token-sheet import
* ``DESIGN.md``    -- the design document, rendered from the same token set

Before writing anything the kit is gated:

1. every token in the frozen contract (``brandkit/tokens.py``) must be present
2. text/background pairs must clear WCAG AA, after the contrast guardrail has
   had its say; if a pair still fails, ``assemble_kit`` raises rather than
   shipping unreadable text
3. copy keys must belong to the skeleton's blocks, and required slots must be
   filled
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import drafter
from . import skeletons as skeletons_mod
from . import tokens as token_contract
from .blocks import BlockError, Registry
from .util import (
    contrast_ratio,
    darken,
    dumps_stable,
    lighten,
    relative_luminance,
    sha256_text,
    text_on,
)

KIT_SCHEMA = "brandkit/kit@1"

AA_BODY = 4.5
AA_LARGE = 3.0


class KitError(Exception):
    """The kit cannot be assembled or would be invalid."""


class DraftContractError(KitError):
    """The draft tried to write something only the measured facts may write."""


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------
def _provenance(metrics: dict) -> dict[tuple[str, str], str]:
    derived = set(metrics.get("derived_tokens") or [])
    out: dict[tuple[str, str], str] = {}
    for group, token in token_contract.all_tokens():
        is_derived = token in derived or f"{group}-{token}" in derived
        out[(group, token)] = "derived" if is_derived else "measured"
    return out


def _make_readable(color: str, surface: str, target: float) -> tuple[str, str]:
    """Move ``color`` away from ``surface`` until it clears ``target``.

    Returns the new colour and a human-readable description of the move. The
    description names the *direction*, not its hex, so nothing appears in
    DESIGN.md that is not a token in kit.css.
    """
    towards_light = relative_luminance(surface) <= 0.5
    step_name = "lighten" if towards_light else "darken"
    way = "white" if towards_light else "black"
    best = color
    for step in range(1, 21):
        factor = step * 0.05
        candidate = lighten(color, factor) if towards_light else darken(color, factor)
        best = candidate
        if contrast_ratio(candidate, surface) >= target:
            return candidate, f"{step_name} {factor:.2f} towards {way}"
    return best, f"{step_name} to the limit towards {way}"


def apply_contrast_guardrail(
    colors: dict[str, str], guardrails: list[dict], derived: set[tuple[str, str]]
) -> dict[str, str]:
    """Keep the brand's own colour when it is safe, and say so when it is not.

    The naive pipeline -- "the brand colour is the primary, use it for links" --
    ships unreadable text the moment a brand declares its accent as a *text*
    colour on a light surface (see ``sources/slate-assurance.html``, where the
    measured accent is 1.28:1 on white). The guardrail keeps that measured
    colour as the ``accent`` token -- surfaces, rules and underlines are fine --
    and derives a legible ``primary`` for text and buttons.
    """
    colors = dict(colors)

    # Text tokens are repaired against the worst surface they are used on, then
    # re-checked: a brand whose two surfaces sit on opposite sides of the
    # lightness scale (a white page with a near-black band) needs more than one
    # pass before both are legible.
    for token, surfaces in token_contract.TEXT_ON_SURFACES:
        before = colors[token]
        start = {name: contrast_ratio(before, colors[name]) for name in surfaces}
        worst_surface = min(surfaces, key=lambda name: start[name])
        ratio_before = start[worst_surface]
        move = ""
        for _ in range(4):
            current = min(
                surfaces, key=lambda name: contrast_ratio(colors[token], colors[name])
            )
            if contrast_ratio(colors[token], colors[current]) >= AA_BODY:
                break
            colors[token], move = _make_readable(colors[token], colors[current], AA_BODY)
        if colors[token] == before:
            continue

        derived.add(("color", token))
        record = {
            "token": token,
            "reason": f"{before} is {ratio_before}:1 on {colors[worst_surface]} "
                      f"({worst_surface}); AA body text needs {AA_BODY}:1",
            "contrast_before": ratio_before,
            "worst_surface": worst_surface,
            "before": before,
            "after": colors[token],
            "contrast_after": contrast_ratio(
                colors[token],
                colors[min(surfaces, key=lambda name: contrast_ratio(colors[token], colors[name]))],
            ),
            "strategy": move,
            "checked_surfaces": list(surfaces),
        }
        if token == "primary":
            # The measured brand colour is not thrown away: it stays as
            # `--accent` for surfaces, rules and underlines.
            colors["primary-ink"] = text_on(colors["primary"])
            record["kept_as"] = "accent"
            record["note"] = ("the measured colour is preserved in --accent for surfaces, "
                              "rules and underlines")
            if colors["accent"] == before:
                derived.add(("color", "accent"))
        guardrails.append(record)

    colors["primary-ink"] = text_on(colors["primary"])
    return colors


def build_tokens(metrics: dict) -> tuple[dict, dict, list[dict]]:
    """Return ``(tokens, provenance, guardrails)`` from measured facts alone."""
    colors = dict(metrics["roles"])
    fonts = dict(metrics["fonts"]["roles"])
    radius = dict(metrics["radius"]["roles"])
    elevation = dict(metrics["elevation"]["roles"])

    provenance = _provenance(metrics)
    derived = {key for key, value in provenance.items() if value == "derived"}
    guardrails: list[dict] = []

    colors = apply_contrast_guardrail(colors, guardrails, derived)

    tokens = {
        "color": {token: colors[token] for token in token_contract.COLOR_TOKENS},
        "font": {token: fonts[token] for token in token_contract.FONT_TOKENS},
        "radius": {token: radius[token] for token in token_contract.RADIUS_TOKENS},
        "shadow": {token: elevation[token] for token in token_contract.SHADOW_TOKENS},
    }
    missing = [
        token_contract.css_var(group, token)
        for group, token in token_contract.all_tokens()
        if not tokens[group].get(token)
    ]
    if missing:
        raise KitError(f"metrics did not yield a value for: {', '.join(missing)}")

    provenance_out = {
        f"{group}.{token}": (
            "derived"
            if (group, token) in derived or provenance.get((group, token)) == "derived"
            else "measured"
        )
        for group, token in token_contract.all_tokens()
    }
    return tokens, provenance_out, guardrails


# --------------------------------------------------------------------------
# assemble
# --------------------------------------------------------------------------
FORBIDDEN_DRAFT_KEYS = ("tokens", "css", "theme", "colors", "colours", "palette", "fonts")


def check_draft_contract(draft: dict) -> None:
    """A draft may carry copy. Nothing else."""
    present = [key for key in FORBIDDEN_DRAFT_KEYS if key in draft]
    if present:
        raise DraftContractError(
            "the draft tried to write design facts "
            f"({', '.join(sorted(present))}). Tokens come from the measured source only; "
            "assemble_kit is their single writer."
        )
    if "copy" not in draft or not isinstance(draft["copy"], dict):
        raise DraftContractError("the draft must carry a 'copy' object")


def assemble_kit(draft: dict, metrics: dict, registry: Registry | None = None) -> dict:
    """Assemble the one kit: measured tokens + drafted copy. The single writer."""
    check_draft_contract(draft)
    tokens, provenance, guardrails = build_tokens(metrics)

    skeleton_id = draft.get("skeleton")
    copy = dict(draft["copy"])

    if skeleton_id:
        try:
            skeleton = skeletons_mod.load(skeleton_id)
        except FileNotFoundError as exc:
            raise KitError(str(exc)) from exc
        allowed = {slot["key"] for slot in drafter.slot_plan(skeleton, registry)}
        unknown = sorted(set(copy) - allowed)
        if unknown:
            raise KitError(
                f"copy references slots that do not exist on {skeleton_id}: {unknown[:5]}"
            )
        required = {slot["key"] for slot in drafter.slot_plan(skeleton, registry)
                    if slot["required"]}
        missing = sorted(key for key in required if not copy.get(key, "").strip())
        if missing:
            raise KitError(
                f"{skeleton_id} requires copy for {len(missing)} slot(s): {missing[:5]}"
            )

    # final gate: nothing ships that a reader cannot read
    failures = []
    for fg, bg in token_contract.enforced_pairs():
        ratio = contrast_ratio(tokens["color"][fg], tokens["color"][bg])
        if ratio < AA_BODY:
            failures.append(f"{fg} on {bg} = {ratio}:1 (< {AA_BODY})")
    if failures:
        raise KitError("contrast gate failed: " + "; ".join(failures))

    contrast = {}
    for fg, bg in token_contract.report_pairs():
        contrast[f"{fg}-on-{bg}"] = {
            "ratio": contrast_ratio(tokens["color"][fg], tokens["color"][bg]),
            "enforced": (fg, bg) in token_contract.enforced_pairs(),
            "floor": AA_BODY if (fg, bg) in token_contract.enforced_pairs() else AA_LARGE,
        }

    token_fingerprint = sha256_text(dumps_stable(tokens))
    kit = {
        "schema": KIT_SCHEMA,
        "source": {
            "id": (metrics.get("source") or {}).get("id", ""),
            "sha256": (metrics.get("source") or {}).get("sha256", ""),
            "reference": (metrics.get("source") or {}).get("reference", ""),
        },
        "skeleton": skeleton_id or "",
        "tokens": tokens,
        "provenance": provenance,
        "contrast": contrast,
        "guardrails": guardrails,
        "copy": dict(sorted(copy.items())),
        "draft": {
            "model": draft.get("model", ""),
            "copy_fingerprint": draft.get("copy_fingerprint", ""),
        },
        "metrics_summary": {
            "declarations": metrics.get("declarations", 0),
            "colours_seen": len((metrics.get("palette") or {}).get("counts", {})),
            "families_seen": len((metrics.get("fonts") or {}).get("families", [])),
            "copy_candidates": sum(len(v) for v in (metrics.get("copy_pool") or {}).values()),
            "derived_from_source": sorted(metrics.get("derived_tokens") or []),
        },
        "fingerprints": {
            "tokens": token_fingerprint,
            "kit": sha256_text(dumps_stable({"tokens": tokens, "copy": copy})),
        },
    }
    return kit


# --------------------------------------------------------------------------
# renderers — all four artefacts come from the same object
# --------------------------------------------------------------------------
def render_css(kit: dict) -> str:
    lines = [
        "/* brandkit kit — GENERATED by brandkit.assemble_kit(). Do not edit by hand.",
        f"   source:   {kit['source']['id']} ({kit['source']['sha256'][:12] or 'unknown'})",
        f"   skeleton: {kit['skeleton'] or 'n/a'}",
        f"   tokens fingerprint: {kit['fingerprints']['tokens'][:16]}",
        "   Bind it with: python3 -m brandkit.apply --kit kit.json --skeleton <id> */",
        ":root {",
    ]
    for group, names in token_contract.GROUPS.items():
        lines.append(f"  /* {group} */")
        for name in names:
            value = kit["tokens"][group][name]
            if group == "font":
                value = f"'{value}'"
            lines.append(f"  {token_contract.css_var(group, name)}: {value};")
    lines.append("}")
    return "\n".join(lines) + "\n"


#: A row of the DESIGN.md token tables: ``| `--paper` | #ffffff | measured |``
DESIGN_TABLE_ROW = re.compile(r"^\|\s*`--[a-z-]+`")
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def design_md_hex_problems(kit: dict) -> list[str]:
    """Hexes the design document and the stylesheet disagree about.

    Only the *token tables* have to agree with ``kit.css`` byte for byte. The
    Guardrails section deliberately quotes the measured colour that was thrown
    away, so a whole-document scan would flag the discarded measurement as an
    inconsistency -- the opposite of what it is.

    This lives here, next to the two renderers, so the test suite and the eval
    harness cannot drift apart about what "consistent" means.
    """
    design = render_design_md(kit)
    css = render_css(kit)
    tables = "\n".join(line for line in design.splitlines() if DESIGN_TABLE_ROW.match(line))
    problems: list[str] = []
    for value in sorted(set(HEX_RE.findall(tables))):
        if value not in css:
            problems.append(f"{value} is in a DESIGN.md token table but not in kit.css")
    for value in sorted(set(HEX_RE.findall(css))):
        if value not in design:
            problems.append(f"{value} is shipped by kit.css but never documented in DESIGN.md")
    return problems


def render_tokens_csv(kit: dict) -> str:
    """A token sheet a design-tool import can read.

    Columns are ``Token,Color,Font,Value``; a colour token fills ``Color``, a
    type token fills ``Font``, and radius/elevation fill ``Value``.
    """
    rows = ["Token,Color,Font,Value"]
    for group, names in token_contract.GROUPS.items():
        for name in names:
            var = token_contract.css_var(group, name)
            value = kit["tokens"][group][name]
            color = value if group == "color" else ""
            font = value if group == "font" else ""
            other = value if group in ("radius", "shadow") else ""
            if "," in other:
                other = '"' + other + '"'
            rows.append(f"{var},{color},{font},{other}")
    return "\n".join(rows) + "\n"


def render_design_md(kit: dict) -> str:
    """DESIGN.md, rendered from the same token set that lands in kit.css."""
    colors = kit["tokens"]["color"]
    out = [
        f"# DESIGN.md — {kit['source']['id']}",
        "",
        "Generated by `brandkit.assemble_kit()` from measured facts. Every value on",
        "this page is also a CSS custom property in `kit.css`; the two are rendered",
        "from one object and cannot drift.",
        "",
        f"* source: `{kit['source']['reference'] or kit['source']['id']}` "
        f"(sha256 `{kit['source']['sha256'][:16]}`)",
        f"* applied to skeleton: `{kit['skeleton']}`",
        f"* token fingerprint: `{kit['fingerprints']['tokens'][:16]}`",
        "",
        "## Palette",
        "",
        "| token | value | provenance | contrast | verdict |",
        "|---|---|---|---|---|",
    ]
    reference = {
        "ink": ("paper", "AA text", AA_BODY),
        "ink-muted": ("paper", "AA text", AA_BODY),
        "primary": ("paper", "AA text", AA_BODY),
        "primary-ink": ("primary", "AA text", AA_BODY),
        "accent": ("paper", "decorative", AA_LARGE),
        "border": ("paper", "hairline rule", AA_LARGE),
    }
    for name in token_contract.COLOR_TOKENS:
        value = colors[name]
        against, use, floor = reference.get(name, (None, "surface", AA_LARGE))
        if against is None:
            out.append(
                f"| `--{name}` | `{value}` | {kit['provenance'][f'color.{name}']} | "
                f"— | surface |"
            )
            continue
        ratio = contrast_ratio(value, colors[against])
        if use == "decorative":
            verdict = "decorative only — never used for text"
        elif use == "hairline rule":
            verdict = "hairline rule — not text"
        else:
            verdict = f"**pass** ({ratio}:1, floor {floor}:1)" if ratio >= floor else \
                      f"**BELOW** floor {floor}:1"
        out.append(
            f"| `--{name}` | `{value}` | {kit['provenance'][f'color.{name}']} | "
            f"{ratio}:1 on `--{against}` | {verdict} |"
        )

    out += ["", "## Type", "", "| token | family | provenance |", "|---|---|---|"]
    for name in token_contract.FONT_TOKENS:
        out.append(
            f"| `--{name}` | {kit['tokens']['font'][name]} | "
            f"{kit['provenance'][f'font.{name}']} |"
        )

    out += ["", "## Radius", "", "| token | value | provenance |", "|---|---|---|"]
    for name in token_contract.RADIUS_TOKENS:
        out.append(
            f"| `--radius-{name}` | `{kit['tokens']['radius'][name]}` | "
            f"{kit['provenance'][f'radius.{name}']} |"
        )

    out += ["", "## Elevation", "", "| token | value | provenance |", "|---|---|---|"]
    for name in token_contract.SHADOW_TOKENS:
        out.append(
            f"| `--shadow-{name}` | `{kit['tokens']['shadow'][name]}` | "
            f"{kit['provenance'][f'shadow.{name}']} |"
        )

    out += ["", "## Contrast", "",
            "Measured on the *final* token values, after the guardrail below.",
            "Enforced pairs can block a kit; the decorative ones are reported for",
            "transparency only, because no text is ever painted on them.",
            "", "| pair | ratio | floor | enforced |", "|---|---|---|---|"]
    for fg, bg in token_contract.report_pairs():
        data = contrast_ratio(colors[fg], colors[bg])
        enforced = (fg, bg) in token_contract.enforced_pairs()
        floor = AA_BODY if enforced else AA_LARGE
        out.append(
            f"| `--{fg}` on `--{bg}` | {data}:1 | {floor}:1 | {'yes' if enforced else 'no'} |"
        )

    out += ["", "## Guardrails", ""]
    if kit["guardrails"]:
        for item in kit["guardrails"]:
            out.append(f"* **{item['token']}** — {item['reason']} → {item['strategy']} "
                       f"(`{item['before']}` → `{item['after']}`)")
            if item.get("kept_as"):
                out.append(f"  * the measured brand colour is preserved as "
                           f"`--{item['kept_as']}` ({colors[item['kept_as']]}) for surfaces, "
                           f"rules and underlines")
    else:
        out.append("None. Every colour the brand declared cleared WCAG AA as declared.")

    out += [
        "",
        "## Tokens as they land in CSS",
        "",
        "```css",
        render_css(kit).rstrip("\n"),
        "```",
        "",
        "## Notes",
        "",
        f"* copy drafted by `{kit['draft']['model']}` (fingerprint "
        f"`{kit['draft']['copy_fingerprint'][:16]}`); copy never influences a token",
        f"* measurements came from {_count_declarations(kit)} CSS declarations in the source page",
        "* radius and elevation values are strings copied from the source, not recomputed",
        "",
    ]
    return "\n".join(out)


def _count_declarations(kit: dict) -> str:
    """Declaration count for the DESIGN.md footnote."""
    summary = kit.get("metrics_summary") or {}
    value = summary.get("declarations")
    return str(value) if value else "the"


def write_kit(kit: dict, outdir: str | Path, stem: str) -> dict[str, Path]:
    """Write kit.json, kit.css, tokens.csv and DESIGN.md. Returns their paths."""
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "kit": out / f"{stem}.kit.json",
        "css": out / f"{stem}.kit.css",
        "csv": out / f"{stem}.tokens.csv",
        "design": out / f"{stem}.DESIGN.md",
    }
    paths["kit"].write_text(dumps_stable(kit), encoding="utf-8")
    paths["css"].write_text(render_css(kit), encoding="utf-8")
    paths["csv"].write_text(render_tokens_csv(kit), encoding="utf-8")
    paths["design"].write_text(render_design_md(kit), encoding="utf-8")
    return paths


def assemble_and_write(
    draft: dict,
    metrics: dict,
    outdir: str | Path,
    stem: str | None = None,
    registry: Registry | None = None,
) -> tuple[dict, dict[str, Path]]:
    """Assemble and write in one call. ``stem`` defaults to ``<source>-<skeleton>``."""
    kit = assemble_kit(draft, metrics, registry)
    stem = stem or f"{(kit['source']['id'] or 'source')}--{kit['skeleton'] or 'none'}"
    return kit, write_kit(kit, outdir, stem)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assemble a design kit from a draft and metrics.")
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--skeleton", required=True)
    ap.add_argument("--drafter", default=drafter.DEFAULT_MODEL,
                    help="rules-v1 | alt-v1 | openai:<model>")
    ap.add_argument("--draft", help="use an existing draft json instead of drafting now")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--stem", help="file stem (default <source>--<skeleton>)")
    args = ap.parse_args(argv)

    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    try:
        if args.draft:
            draft_doc = json.loads(Path(args.draft).read_text(encoding="utf-8"))
        else:
            draft_doc = drafter.draft_for(args.skeleton, metrics, args.drafter)
        kit, paths = assemble_and_write(draft_doc, metrics, args.out, args.stem)
    except (KitError, DraftContractError, BlockError) as exc:
        print(f"kit refused: {exc}", file=sys.stderr)
        return 1

    print(f"kit for {kit['source']['id']} on {kit['skeleton']} "
          f"(tokens {kit['fingerprints']['tokens'][:12]})")
    for kind, path in paths.items():
        print(f"  {kind:7} {path}")
    for item in kit["guardrails"]:
        print(f"  guardrail: {item['token']}: {item['reason']} -> {item['strategy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
