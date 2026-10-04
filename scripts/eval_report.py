#!/usr/bin/env python3
"""The evaluation harness: (sources x skeletons) -> numbers with thresholds.

This is the number a client can re-run. For every (source, skeleton) pair it
measures, drafts, assembles, binds and proves, then reports:

* ``token coverage``     -- how much of the frozen token contract the kit fills
* ``slot coverage``      -- required and optional copy slots that got copy
* ``contrast``           -- the *minimum* enforced WCAG AA ratio in that kit
* ``tree unchanged``     -- the band list and repeat counts are identical after
                            the restyle (the harness fails if this is ever false)
* ``determinism``        -- the kit is rebuilt a second time and every artefact
                            must be byte-identical

The run **fails** (exit 1) if any threshold regresses, so it can be used as a CI
gate rather than a report nobody reads.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brandkit import apply as apply_mod  # noqa: E402
from brandkit import drafter, htmltree, measure, skeletons, tokens  # noqa: E402
from brandkit.assemble_kit import (  # noqa: E402
    assemble_kit,
    design_md_hex_problems,
    render_css,
    write_kit,
)
from brandkit.util import dumps_stable, sha256_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

THRESHOLDS = {
    "token_coverage": 1.0,          # every contract token present and non-empty
    "required_slot_coverage": 1.0,  # every required slot got copy
    "contrast_aa_rate": 1.0,        # every enforced pair clears WCAG AA
    "tree_unchanged_rate": 1.0,     # proved, per pair, not asserted
    "determinism_rate": 1.0,        # byte-identical on a second run
    "measured_token_ratio": 0.60,   # most tokens come straight from the source
    "kits": 12,                     # 3 sources x 4 skeletons, all of them
}


def discover(repo_root: Path) -> tuple[list[str], list[str]]:
    sources = sorted(p.stem for p in (repo_root / "sources").glob("*.html"))
    skeletons_found = sorted(p.name for p in skeletons.SKELETON_ROOT.iterdir()
                             if (p / "layout-base.html").is_file())
    return sources, skeletons_found


def evaluate_pair(source_path: Path, skeleton_id: str, workdir: Path) -> dict:
    metrics = measure.measure_source(source_path)
    skeleton = skeletons.load(skeleton_id)
    source_id = metrics["source"]["id"]

    draft = drafter.draft(skeleton, metrics)
    kit = assemble_kit(draft, metrics)

    css = render_css(kit)
    stem = f"{source_id}--{skeleton_id}"
    first = workdir / "kits"
    second = workdir / "determinism"
    write_kit(kit, first, stem)

    # determinism: everything again, from scratch
    draft_again = drafter.draft(skeleton, metrics)
    kit_again = assemble_kit(draft_again, metrics)
    write_kit(kit_again, second, stem)

    artefacts = ("{s}.kit.json", "{s}.kit.css", "{s}.tokens.csv", "{s}.DESIGN.md")
    stable = all(
        (first / pattern.format(s=stem)).read_bytes()
        == (second / pattern.format(s=stem)).read_bytes()
        for pattern in artefacts
    )

    proof = apply_mod.restyle(
        skeleton_id, css, kit["copy"],
        workdir / "restyled" / f"{stem}.html",
        workdir / "proofs" / f"{stem}.proof.json",
    )

    declared = skeleton.declared_tokens()
    tokens_ok = sum(
        1 for var in tokens.all_vars()
        if declared.get(var, "").strip() and f"{var}:" in css
    )
    plan = drafter.slot_plan(skeleton)
    required = [slot["key"] for slot in plan if slot["required"]]
    required_filled = [key for key in required if kit["copy"].get(key, "").strip()]
    optional_filled = [key for key in (s["key"] for s in plan) if kit["copy"].get(key, "").strip()]

    enforced = [data for data in kit["contrast"].values() if data["enforced"]]
    passing = [data for data in enforced if data["ratio"] >= data["floor"]]

    measured = sum(1 for value in kit["provenance"].values() if value == "measured")
    total_tokens = len(kit["provenance"])

    return {
        "source": source_id,
        "skeleton": skeleton_id,
        "declarations_measured": metrics["declarations"],
        "bands": len(skeleton.bands),
        "repeat_items": sum(skeleton.repeats.values()),
        "elements": len(list(htmltree.iter_elements(skeleton.root))),
        "token_coverage": round(tokens_ok / len(tokens.all_vars()), 4),
        "required_slot_coverage": round(len(required_filled) / max(1, len(required)), 4),
        "slot_coverage": round(len(optional_filled) / max(1, len(plan)), 4),
        "slots_total": len(plan),
        "slots_filled": len(optional_filled),
        "contrast_aa_rate": round(len(passing) / max(1, len(enforced)), 4),
        "contrast_min": min(data["ratio"] for data in enforced),
        "contrast_min_pair": _min_pair(kit),
        "measured_token_ratio": round(measured / total_tokens, 4),
        "guardrails": len(kit["guardrails"]),
        "guardrail_details": kit["guardrails"],
        "tree_unchanged": bool(proof["tree_unchanged"]),
        "tree_signature": proof["signature_after"][:16],
        "slots_written": proof["slots_written_count"],
        "deterministic": bool(stable),
        "determinism_hash": sha256_text(
            (first / f"{stem}.kit.json").read_text(encoding="utf-8")
            + (first / f"{stem}.kit.css").read_text(encoding="utf-8")
        )[:16],
        "token_fingerprint": kit["fingerprints"]["tokens"][:16],
        "design_md_problems": design_md_hex_problems(kit),
    }


def _min_pair(kit: dict) -> str:
    enforced = {key: data for key, data in kit["contrast"].items() if data["enforced"]}
    return min(enforced, key=lambda key: enforced[key]["ratio"])


def summarise(rows: list[dict]) -> dict:
    def mean(key: str) -> float:
        return round(sum(row[key] for row in rows) / max(1, len(rows)), 4)

    unique_sources = {row["source"] for row in rows}
    per_source_tokens = {source: set() for source in unique_sources}
    for row in rows:
        per_source_tokens[row["source"]].add(row["token_fingerprint"])

    return {
        "kits": len(rows),
        "sources": len(unique_sources),
        "skeletons": len({row["skeleton"] for row in rows}),
        "token_coverage": mean("token_coverage"),
        "required_slot_coverage": mean("required_slot_coverage"),
        "slot_coverage": mean("slot_coverage"),
        "contrast_aa_rate": mean("contrast_aa_rate"),
        "contrast_min": min(row["contrast_min"] for row in rows),
        "measured_token_ratio": mean("measured_token_ratio"),
        "tree_unchanged_rate": mean("tree_unchanged"),
        "determinism_rate": mean("deterministic"),
        "guardrails": sum(row["guardrails"] for row in rows),
        "bands_total": sum(row["bands"] for row in rows),
        "elements_total": sum(row["elements"] for row in rows),
        "design_md_consistent": all(not row["design_md_problems"] for row in rows),
        "one_kit_per_source": all(len(v) == 1 for v in per_source_tokens.values()),
        "tokens_per_source": {s: sorted(v)[0] for s, v in sorted(per_source_tokens.items())},
    }


def check_thresholds(summary: dict, rows: list[dict]) -> list[str]:
    failures: list[str] = []
    for key, floor in THRESHOLDS.items():
        actual = summary.get(key)
        if actual is None:
            failures.append(f"{key}: not measured")
            continue
        if key == "kits":
            if actual < floor:
                failures.append(f"{key}: {actual} < {floor}")
            continue
        if actual + 1e-9 < floor:
            failures.append(f"{key}: {actual} < {floor}")
    if not summary.get("design_md_consistent"):
        detail = [
            f"{row['source']}/{row['skeleton']}: {problem}"
            for row in rows for problem in row["design_md_problems"]
        ]
        failures.append("design_md_consistent: " + "; ".join(detail))
    return failures


def print_table(rows: list[dict]) -> None:
    head = (f"{'source':22} {'skeleton':24} {'tok':>5} {'req':>5} {'slot':>5} "
            f"{'AA':>5} {'min':>6} {'tree':>5} {'det':>4} {'guard':>5} {'hash':>16}")
    print(head)
    print("-" * len(head))
    for row in rows:
        print(
            f"{row['source']:22} {row['skeleton']:24} "
            f"{row['token_coverage']:5.2f} {row['required_slot_coverage']:5.2f} "
            f"{row['slot_coverage']:5.2f} {row['contrast_aa_rate']:5.2f} "
            f"{row['contrast_min']:6.2f} "
            f"{'yes' if row['tree_unchanged'] else 'NO':>5} "
            f"{'yes' if row['deterministic'] else 'NO':>4} "
            f"{row['guardrails']:5} {row['determinism_hash']:>16}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(REPO_ROOT), help="repository root")
    ap.add_argument("--workdir", default=str(REPO_ROOT / "out"), help="where artefacts go")
    ap.add_argument("--json-out", default=str(REPO_ROOT / "docs" / "eval.json"))
    ap.add_argument("--keep", action="store_true", help="keep the generated artefacts")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    source_ids, skeleton_ids = discover(repo_root)
    if not source_ids or not skeleton_ids:
        print("nothing to evaluate: no sources or no skeletons", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for source_id in source_ids:
        for skeleton_id in skeleton_ids:
            rows.append(evaluate_pair(repo_root / "sources" / f"{source_id}.html",
                                      skeleton_id, workdir))

    summary = summarise(rows)
    failures = check_thresholds(summary, rows)

    if not args.quiet:
        print_table(rows)
        print()
        print(f"kits evaluated            {summary['kits']} "
              f"({summary['sources']} sources x {summary['skeletons']} skeletons)")
        print(f"token coverage            {summary['token_coverage']:.4f}  "
              f"(floor {THRESHOLDS['token_coverage']})")
        print(f"required slot coverage    {summary['required_slot_coverage']:.4f}  "
              f"(floor {THRESHOLDS['required_slot_coverage']})")
        print(f"slot coverage (all)       {summary['slot_coverage']:.4f}")
        print(f"WCAG AA enforced pairs    {summary['contrast_aa_rate']:.4f}  "
              f"(floor {THRESHOLDS['contrast_aa_rate']}), worst {summary['contrast_min']}:1")
        print(f"tree unchanged rate       {summary['tree_unchanged_rate']:.4f}  "
              f"(floor {THRESHOLDS['tree_unchanged_rate']})")
        print(f"determinism rate          {summary['determinism_rate']:.4f}  "
              f"(floor {THRESHOLDS['determinism_rate']})")
        print(f"measured token ratio      {summary['measured_token_ratio']:.4f}  "
              f"(floor {THRESHOLDS['measured_token_ratio']})")
        print(f"one kit per source        {summary['one_kit_per_source']}")
        print(f"guardrails fired          {summary['guardrails']}")
        print(f"bands checked             {summary['bands_total']} "
              f"across {summary['elements_total']} elements")
        print()
        print("token fingerprints (one per source, identical across all skeletons):")
        for source_id, fingerprint in summary["tokens_per_source"].items():
            print(f"  {source_id:24} {fingerprint}")

    report = {
        "schema": "brandkit/eval@1",
        "repo": str(repo_root.name),
        "workdir": str(workdir.relative_to(repo_root)) if workdir.is_relative_to(repo_root)
        else str(workdir),
        "sources": source_ids,
        "skeletons": skeleton_ids,
        "thresholds": THRESHOLDS,
        "summary": summary,
        "rows": rows,
        "failures": failures,
        "passed": not failures,
    }
    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(dumps_stable(report), encoding="utf-8")

    if not args.quiet:
        print(f"\nwrote {json_out}")

    if not args.keep:
        shutil.rmtree(workdir / "determinism", ignore_errors=True)

    if failures:
        print("\nEVAL FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    if not args.quiet:
        print("\nEVAL PASSED: every threshold held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
