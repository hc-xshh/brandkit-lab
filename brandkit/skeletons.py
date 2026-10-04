"""Load and validate the skeletons in ``skeletons/``.

A skeleton is a neutral landing page plus a contract: which bands it contains,
in which order, which registered block each band is, and how many times each
repeated unit appears. This module reads that contract back out of the HTML and
checks it against the registry, so a typo in a ``data-slot`` key fails the test
suite instead of silently dropping copy at restyle time.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from . import htmltree, tokens
from .blocks import DEFAULT, Registry

REPO_ROOT = Path(__file__).resolve().parent.parent
SKELETON_ROOT = REPO_ROOT / "skeletons"

TOKEN_START = "/* === brandkit:tokens:start === */"
TOKEN_END = "/* === brandkit:tokens:end === */"
SLOT_RE = re.compile(r"^(?P<block>[a-z0-9-]+)\.(?P<field>[a-z0-9-]+)(?:\[(?P<index>\d+)\])?$")


@dataclass
class Slot:
    key: str
    block: str
    field: str
    index: int | None
    text: str


@dataclass
class Skeleton:
    id: str
    path: Path
    html: str
    tree_path: Path

    @property
    def root(self) -> htmltree.Node:
        return htmltree.parse(self.html)

    @property
    def bands(self) -> list[dict[str, str]]:
        return htmltree.band_list(self.root)

    @property
    def repeats(self) -> dict[str, int]:
        return htmltree.repeat_counts(self.root)

    @property
    def slot_nodes(self) -> list[tuple[htmltree.Node, Slot]]:
        out = []
        for node in htmltree.iter_elements(self.root):
            raw = node.get("data-slot")
            if not raw:
                continue
            match = SLOT_RE.match(raw)
            if not match:
                raise ValueError(f"{self.id}: data-slot {raw!r} is not <block>.<field>[index]")
            out.append((
                node,
                Slot(
                    key=raw,
                    block=match.group("block"),
                    field=match.group("field"),
                    index=int(match.group("index")) if match.group("index") else None,
                    text=node.text(),
                ),
            ))
        return out

    @property
    def slots(self) -> list[Slot]:
        return [slot for _node, slot in self.slot_nodes]

    def slot_text(self) -> dict[str, str]:
        return {node.get("data-slot"): node.text() for node in htmltree.iter_elements(self.root)
                if node.get("data-slot")}

    @property
    def signature(self) -> str:
        return htmltree.signature_hash(self.root)

    def token_block(self) -> str:
        """The ``:root`` block between the brandkit markers, verbatim."""
        start = self.html.find(TOKEN_START)
        end = self.html.find(TOKEN_END)
        if start == -1 or end == -1:
            raise ValueError(f"{self.id}: token markers not found")
        if self.html.count(TOKEN_START) != 1 or self.html.count(TOKEN_END) != 1:
            raise ValueError(f"{self.id}: token markers must appear exactly once")
        return self.html[start + len(TOKEN_START):end]

    def declared_tokens(self) -> dict[str, str]:
        """``{'--paper': '#ffffff', ...}`` parsed out of the token block."""
        found: dict[str, str] = {}
        body = re.sub(r"/\*.*?\*/", "", self.token_block(), flags=re.S)
        for match in re.finditer(r"(--[a-zA-Z0-9-]+)\s*:\s*([^;]+)", body):
            found[match.group(1)] = match.group(2).strip()
        return found


def skeleton_dirs() -> list[Path]:
    if not SKELETON_ROOT.is_dir():
        return []
    return sorted(p for p in SKELETON_ROOT.iterdir() if (p / "layout-base.html").is_file())


def load(skeleton_id: str) -> Skeleton:
    path = SKELETON_ROOT / skeleton_id / "layout-base.html"
    if not path.is_file():
        raise FileNotFoundError(f"no skeleton {skeleton_id!r} at {path}")
    return Skeleton(
        id=skeleton_id,
        path=path,
        html=path.read_text(encoding="utf-8"),
        tree_path=path.parent / "TREE.md",
    )


def load_all() -> dict[str, Skeleton]:
    return {p.name: load(p.name) for p in skeleton_dirs()}


# --------------------------------------------------------------------------
def validate(skeleton: Skeleton, registry: Registry | None = None) -> list[str]:
    """Return a list of problems; empty means the skeleton honours the registry."""
    registry = registry or DEFAULT
    problems: list[str] = []

    bands = skeleton.bands
    if not bands:
        problems.append("no bands found (missing data-band attributes)")
        return problems

    # 1. token contract
    declared = skeleton.declared_tokens()
    for var in tokens.all_vars():
        if var not in declared:
            problems.append(f"token block is missing {var}")
        elif not declared[var]:
            problems.append(f"token {var} is empty")
    extra = sorted(set(declared) - set(tokens.all_vars()))
    for var in extra:
        problems.append(f"token {var} is not in the frozen contract (tokens.py)")

    # 2. bands and their blocks
    if skeleton.id in registry.skeletons:
        declared_blocks = registry.skeleton_blocks(skeleton.id)
        actual_blocks = [band["block"] for band in bands]
        if declared_blocks != actual_blocks:
            problems.append(
                "band list disagrees with the registry:\n"
                f"    html:     {actual_blocks}\n"
                f"    registry: {declared_blocks}"
            )
    for band in bands:
        if not band["block"]:
            problems.append(f"band {band['band']!r} has no data-block")
            continue
        if band["block"] not in registry:
            problems.append(f"band {band['band']!r} uses unregistered block {band['block']!r}")

    # 3. slots, requiredness and repeat counts
    slots_by_block: dict[str, list[Slot]] = {}
    for slot in skeleton.slots:
        slots_by_block.setdefault(slot.block, []).append(slot)

    for band in bands:
        block_id = band["block"]
        if block_id not in registry:
            continue
        block = registry.resolve(block_id)
        present = {slot.field for slot in slots_by_block.get(block_id, [])}
        for field in block.required:
            if field not in present:
                problems.append(f"{block_id}: required slot {field!r} is not in the skeleton")
        for field in present:
            if field not in block.all_fields:
                problems.append(f"{block_id}: slot {field!r} is not declared by the block")
        for slot in slots_by_block.get(block_id, []):
            if block.repeat and slot.field in block.repeat.fields:
                if slot.index is None:
                    problems.append(
                        f"{block_id}.{slot.field}: repeated field needs an [index]"
                    )
            elif slot.index is not None:
                problems.append(
                    f"{block_id}.{slot.field}: single-value slot must not carry an index"
                )
        if block.repeat:
            rule = block.repeat
            key = f"{block_id}.{rule.name}"
            count = skeleton.repeats.get(key)
            if count is None:
                problems.append(f"{block_id}: no data-repeat=\"{key}\" container")
                continue
            if not (rule.min <= count <= rule.max):
                problems.append(
                    f"{key}: skeleton repeats {count}x, outside the rule {rule.min}..{rule.max}"
                )
            for field in rule.fields:
                indices = sorted(
                    s.index for s in slots_by_block.get(block_id, []) if s.field == field
                )
                if indices != list(range(count)):
                    problems.append(
                        f"{key}.{field}: expected indices 0..{count - 1}, found {indices}"
                    )
        else:
            for other in skeleton.repeats:
                if other.startswith(block_id + "."):
                    problems.append(f"{block_id}: declares no repeat rule but has {other}")

    # 4. required copy must be filled in the base page, and slots must not nest
    text = skeleton.slot_text()
    for node, slot in skeleton.slot_nodes:
        inner = [n for n in htmltree.iter_elements(node) if n.get("data-slot")]
        if inner:
            problems.append(
                f"{slot.key}: a slot element must not contain another slot "
                f"({', '.join(n.get('data-slot') for n in inner)})"
            )
    for band in bands:
        block_id = band["block"]
        if block_id not in registry:
            continue
        block = registry.resolve(block_id)
        for field in block.required:
            keys = [k for k in text if k.startswith(f"{block_id}.{field}")]
            if not keys:
                continue
            if any(not text[k].strip() for k in keys):
                problems.append(f"{block_id}.{field}: required slot is empty in the base page")

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate skeletons against the block registry.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    import json

    skeletons = load_all()
    report = {}
    failed = False
    for skeleton_id, skeleton in skeletons.items():
        problems = validate(skeleton)
        report[skeleton_id] = {
            "path": str(skeleton.path.relative_to(REPO_ROOT)),
            "bands": skeleton.bands,
            "repeats": skeleton.repeats,
            "slots": len(skeleton.slots),
            "signature": skeleton.signature,
            "problems": problems,
        }
        failed = failed or bool(problems)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for skeleton_id, info in report.items():
            status = "OK  " if not info["problems"] else "FAIL"
            print(f"{status} {skeleton_id:24} {len(info['bands'])} bands, "
                  f"{info['slots']} copy slots, {len(info['repeats'])} repeats")
            for problem in info["problems"]:
                print(f"     - {problem}")
        print(f"\n{len(report)} skeletons validated, "
              f"{'problems found' if failed else 'no problems found'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
