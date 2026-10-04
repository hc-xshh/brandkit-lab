"""Bind a kit onto a skeleton without moving the DOM tree.

``apply`` does exactly two things to a page:

1. replaces the text between ``brandkit:tokens:start`` and ``brandkit:tokens:end``
   with the ``:root`` block from ``kit.css``
2. replaces the *text content* of elements carrying ``data-slot``

It does not re-serialise the document. It edits the original bytes, so anything
it does not mean to touch is byte-identical by construction -- and it proves
that, with a structural signature of every element (tag, structural attributes,
depth, sibling index) taken before and after. If the two signatures differ, the
write is refused and ``apply`` exits non-zero.

The proof is written to ``proof.json`` next to the restyled page:

``tree_unchanged``, ``bands_before``/``bands_after``, ``repeats_before``/``repeats_after``,
``elements_before``/``elements_after``, ``signature_before``/``signature_after``,
``slots_written``, ``slots_left_to_layout`` and the byte deltas.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import htmltree
from . import skeletons as skeletons_mod
from .util import dumps_stable, sha256_text

TOKEN_START = skeletons_mod.TOKEN_START
TOKEN_END = skeletons_mod.TOKEN_END
CSS_ROOT_RE = re.compile(r":root\s*\{(.*?)\}", re.S)
SLOT_RE = re.compile(
    r'(<(?P<tag>[a-zA-Z][a-zA-Z0-9-]*)\b(?P<before>[^>]*?data-slot="(?P<key>[^"]+)"[^>]*?)>)'
    r"(?P<text>.*?)(?P<close></(?P=tag)>)",
    re.S,
)


class ApplyError(Exception):
    """The page cannot be restyled safely."""


def esc(text: str) -> str:
    """Minimal HTML escaping: the copy pool may contain ``&`` or ``<``."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def extract_token_block(kit_css: str) -> str:
    """Pull the declarations out of a kit's ``:root`` block."""
    match = CSS_ROOT_RE.search(kit_css)
    if not match:
        raise ApplyError("kit.css carries no :root block")
    return match.group(1).strip("\n")


def render_token_block(declarations: str) -> str:
    return f"{TOKEN_START}\n  :root {{\n{declarations}\n  }}\n  {TOKEN_END}"


def bind_tokens(html: str, kit_css: str) -> str:
    start = html.find(TOKEN_START)
    end = html.find(TOKEN_END)
    if start == -1 or end == -1:
        raise ApplyError("the skeleton has no brandkit token markers")
    if html.count(TOKEN_START) != 1 or html.count(TOKEN_END) != 1:
        raise ApplyError("the skeleton has more than one pair of token markers")
    body = html[end + len(TOKEN_END):]
    return html[:start] + render_token_block(extract_token_block(kit_css)) + body


def bind_copy(html: str, copy: dict[str, str]) -> tuple[str, list[str]]:
    """Replace the text inside ``data-slot`` elements. Returns (html, keys written)."""
    written: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group("key")
        value = copy.get(key, "")
        # An unfilled or empty slot keeps whatever the layout already had.
        if not value.strip():
            return match.group(0)
        if "data-slot" in match.group("text"):
            return match.group(0)  # never rewrite a parent that contains slots
        written.append(key)
        indent = ""
        tail = match.group("text")
        stripped = tail.rstrip()
        if tail and not stripped:
            indent = tail  # keep pure whitespace as-is
        return f"{match.group(1)}{esc(value)}{indent}{match.group('close')}"

    return SLOT_RE.sub(replace, html), written


def bind(html: str, kit_css: str, copy: dict[str, str]) -> tuple[str, list[str]]:
    """Bind tokens and copy; return the new page and the slot keys that changed."""
    return bind_copy(bind_tokens(html, kit_css), copy)


def restyle(
    skeleton_id: str,
    kit_css: str,
    copy: dict[str, str],
    out_html: str | Path,
    proof_path: str | Path,
) -> dict:
    """Restyle a skeleton on disk and write both the page and its proof."""
    skeleton = skeletons_mod.load(skeleton_id)
    before_html = skeleton.html
    after_html, written = bind(before_html, kit_css, copy)

    before = htmltree.parse(before_html)
    after = htmltree.parse(after_html)

    bands_before = htmltree.band_list(before)
    bands_after = htmltree.band_list(after)
    repeats_before = htmltree.repeat_counts(before)
    repeats_after = htmltree.repeat_counts(after)
    sig_before = htmltree.signature_hash(before)
    sig_after = htmltree.signature_hash(after)

    proof = {
        "skeleton": skeleton_id,
        "source_sha256": sha256_text(before_html),
        "output_sha256": sha256_text(after_html),
        "tree_unchanged": sig_before == sig_after,
        "signature_before": sig_before,
        "signature_after": sig_after,
        "bands_before": bands_before,
        "bands_after": bands_after,
        "repeats_before": repeats_before,
        "repeats_after": repeats_after,
        "elements_before": htmltree.element_count(before),
        "elements_after": htmltree.element_count(after),
        "slots_written": sorted(written),
        "slots_written_count": len(written),
        "slots_left_to_layout": sorted(
            key for key in skeleton.slot_text() if key not in written
        ),
        "bytes_before": len(before_html.encode("utf-8")),
        "bytes_after": len(after_html.encode("utf-8")),
    }

    if not proof["tree_unchanged"]:
        raise ApplyError(
            f"refusing to write {out_html}: the structural signature changed "
            f"({sig_before[:12]} -> {sig_after[:12]}). A restyle may not move the DOM tree."
        )
    if bands_before != bands_after or repeats_before != repeats_after:
        raise ApplyError(f"refusing to write {out_html}: the band list or repeats moved")

    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(after_html, encoding="utf-8")
    proof_file = Path(proof_path)
    proof_file.parent.mkdir(parents=True, exist_ok=True)
    proof_file.write_text(dumps_stable(proof), encoding="utf-8")
    return proof


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bind a kit onto a skeleton.")
    ap.add_argument("--kit", required=True, help="path to a kit.json")
    ap.add_argument("--kit-css", help="path to a kit.css (default: sibling of --kit)")
    ap.add_argument("--skeleton", help="skeleton id (default: the kit's own skeleton)")
    ap.add_argument("--out", required=True, help="path of the restyled html")
    ap.add_argument("--proof", help="path of the proof json (default: <out>.proof.json)")
    args = ap.parse_args(argv)

    kit_path = Path(args.kit)
    kit = json.loads(kit_path.read_text(encoding="utf-8"))
    if args.kit_css:
        kit_css_path = Path(args.kit_css)
    else:
        kit_css_path = kit_path.with_name(kit_path.name.replace(".kit.json", ".kit.css"))
    if not kit_css_path.is_file():
        print(f"error: kit css not found at {kit_css_path}", file=sys.stderr)
        return 2
    kit_css = kit_css_path.read_text(encoding="utf-8")
    skeleton_id = args.skeleton or kit["skeleton"]
    if not skeleton_id:
        print("error: no skeleton given and the kit names none", file=sys.stderr)
        return 2
    proof_path = args.proof or str(Path(args.out).with_suffix(".proof.json"))

    try:
        proof = restyle(skeleton_id, kit_css, kit["copy"], args.out, proof_path)
    except (ApplyError, FileNotFoundError) as exc:
        print(f"apply refused: {exc}", file=sys.stderr)
        return 1

    print(f"restyled {skeleton_id} -> {args.out}")
    print(f"  tree unchanged: {proof['tree_unchanged']} "
          f"({proof['elements_before']} elements, "
          f"{len(proof['bands_before'])} bands, "
          f"{sum(proof['repeats_before'].values())} repeated items)")
    print(f"  copy slots written: {proof['slots_written_count']}, "
          f"left to the layout: {len(proof['slots_left_to_layout'])}")
    print(f"  signature {proof['signature_before'][:16]} == {proof['signature_after'][:16]}")
    print(f"wrote {proof_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
