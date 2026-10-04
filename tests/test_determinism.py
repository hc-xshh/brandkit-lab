"""Same input, same bytes. Every stage, not just the last one.

Determinism is not a nicety here: the two-model invariant and the CI eval gate
both compare artefacts byte for byte, so any hidden clock, dict ordering or
iteration-order dependency has to fail loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brandkit import drafter, measure, skeletons, util
from brandkit.assemble_kit import assemble_kit, render_css, write_kit

PAIRS = [
    (source, skeleton)
    for source in ("northwind-outfitters", "pulse-analytics", "slate-assurance")
    for skeleton in ("01-host-landing", "02-saas-marketing", "03-product-security",
                     "04-insurance-longform")
]


def test_measuring_twice_gives_identical_json(repo_root):
    for source in ("northwind-outfitters", "pulse-analytics", "slate-assurance"):
        path = repo_root / "sources" / f"{source}.html"
        first = util.dumps_stable(measure.measure_source(path))
        second = util.dumps_stable(measure.measure_source(path))
        assert first == second


def test_measurement_json_is_canonical(repo_root):
    """Sorted keys and a trailing newline, so a diff means a real change."""
    metrics = measure.measure_source(repo_root / "sources" / "pulse-analytics.html")
    text = util.dumps_stable(metrics)
    assert text.endswith("\n")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2,
                              ensure_ascii=False) + "\n"


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_kit_bytes_are_stable(metrics_all, source_id, skeleton_id, tmp_path):
    metrics = metrics_all[source_id]
    skeleton = skeletons.load(skeleton_id)

    first = tmp_path / "first"
    second = tmp_path / "second"
    write_kit(assemble_kit(drafter.draft(skeleton, metrics), metrics), first, "kit")
    write_kit(assemble_kit(drafter.draft(skeleton, metrics), metrics), second, "kit")

    for name in ("kit.kit.json", "kit.kit.css", "kit.tokens.csv", "kit.DESIGN.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_draft_fingerprint_is_stable(metrics_all):
    skeleton = skeletons.load("03-product-security")
    metrics = metrics_all["northwind-outfitters"]
    a = drafter.draft(skeleton, metrics)
    b = drafter.draft(skeleton, metrics)
    assert a == b
    assert a["copy_fingerprint"] == b["copy_fingerprint"]


def test_repeated_runs_keep_the_kit_fingerprint(metrics_all):
    """A kit's identity must not depend on how many kits were built before it."""
    metrics = metrics_all["slate-assurance"]
    fingerprints = set()
    for skeleton_id in ("01-host-landing", "03-product-security", "01-host-landing"):
        skeleton = skeletons.load(skeleton_id)
        kit = assemble_kit(drafter.draft(skeleton, metrics), metrics)
        fingerprints.add(kit["fingerprints"]["tokens"])
    assert len(fingerprints) == 1

def test_a_kit_fingerprint_does_not_depend_on_the_checkout_path(tmp_path, monkeypatch):
    """Same brand, different working directory: the same kit.

    The fingerprint is over facts. A path that leaks into `metrics.json` would
    make the same brand hash differently in CI than on a laptop, which would
    quietly turn every downstream "the two models agree" check into a
    comparison of directory names.
    """
    repo = Path(__file__).resolve().parent.parent
    source = repo / "sources" / "northwind-outfitters.html"
    skeleton = skeletons.load("01-host-landing")

    monkeypatch.chdir(repo)
    here = measure.measure_source(source.relative_to(repo))
    monkeypatch.chdir(tmp_path)
    elsewhere = measure.measure_source(source)

    assert here["source"]["reference"] == "sources/northwind-outfitters.html"
    assert "/" not in elsewhere["source"]["reference"].lstrip("/") or \
        elsewhere["source"]["reference"] == str(source)
    assert here["source"]["sha256"] == elsewhere["source"]["sha256"]

    kit_a = assemble_kit(drafter.draft(skeleton, here), here)
    kit_b = assemble_kit(drafter.draft(skeleton, elsewhere), elsewhere)
    assert kit_a["fingerprints"]["tokens"] == kit_b["fingerprints"]["tokens"]
    assert render_css(kit_a) == render_css(kit_b)
