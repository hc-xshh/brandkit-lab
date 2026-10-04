"""A kit that fills fewer slots than the layout has is a valid kit.

Optional slots are optional. When copy is missing -- a source with two H2s and a
skeleton with five, a model that returns nothing for a meta line -- the layout
keeps its own text, the tree does not move, and the kit is still complete.
"""

from __future__ import annotations

import pytest

from brandkit import apply as apply_mod
from brandkit import drafter, htmltree, skeletons
from brandkit.assemble_kit import KitError, assemble_kit, render_css


def _required(draft: dict, skeleton) -> dict:
    required = {slot["key"] for slot in drafter.slot_plan(skeleton) if slot["required"]}
    return {key: value for key, value in draft["copy"].items() if key in required}


def test_a_required_only_draft_is_enough(metrics_all):
    metrics = metrics_all["northwind-outfitters"]
    skeleton = skeletons.load("02-saas-marketing")
    draft = drafter.draft(skeleton, metrics)
    draft["copy"] = _required(draft, skeleton)
    kit = assemble_kit(draft, metrics)
    assert len(kit["copy"]) < len(drafter.slot_plan(skeleton))
    assert kit["tokens"]["color"]["paper"] == metrics["roles"]["paper"]


def test_missing_optional_copy_leaves_the_layouts_own_text(metrics_all):
    metrics = metrics_all["pulse-analytics"]
    skeleton = skeletons.load("01-host-landing")
    draft = drafter.draft(skeleton, metrics)
    stripped = _required(draft, skeleton)
    draft["copy"] = stripped

    out, written = apply_mod.bind_copy(skeleton.html, draft["copy"])
    proof_before = htmltree.signature_hash(htmltree.parse(skeleton.html))
    assert htmltree.signature_hash(htmltree.parse(out)) == proof_before

    existing = skeleton.slot_text()
    for key in existing:
        if key not in stripped:
            assert existing[key] in out, f"{key} lost its original text"


def test_empty_strings_are_treated_as_unfilled(metrics_all):
    metrics = metrics_all["pulse-analytics"]
    skeleton = skeletons.load("01-host-landing")
    draft = drafter.draft(skeleton, metrics)
    draft["copy"] = dict(draft["copy"])
    key = "stat-band.meta"  # optional on this block
    assert key in draft["copy"]
    draft["copy"][key] = "   "
    kit = assemble_kit(draft, metrics)
    out, written = apply_mod.bind_copy(skeleton.html, kit["copy"])
    assert key not in written
    assert skeleton.slot_text()[key] in out


def test_whitespace_copy_cannot_satisfy_a_required_slot(metrics_all):
    metrics = metrics_all["pulse-analytics"]
    skeleton = skeletons.load("01-host-landing")
    draft = drafter.draft(skeleton, metrics)
    draft["copy"] = dict(draft["copy"])
    draft["copy"]["hero-center.h1"] = "\n\t "
    with pytest.raises(KitError):
        assemble_kit(draft, metrics)


def test_a_draft_that_skips_a_required_slot_is_refused(metrics_all):
    metrics = metrics_all["pulse-analytics"]
    skeleton = skeletons.load("04-insurance-longform")
    draft = drafter.draft(skeleton, metrics)
    for slot in drafter.slot_plan(skeleton):
        if slot["required"]:
            draft["copy"].pop(slot["key"], None)
            break
    with pytest.raises(KitError) as excinfo:
        assemble_kit(draft, metrics)
    assert "requires copy" in str(excinfo.value)


def test_metrics_without_a_copy_pool_cannot_be_drafted():
    with pytest.raises(drafter.DraftError):
        drafter.draft(skeletons.load("01-host-landing"),
                      {"source": {"id": "empty"}, "copy_pool": {}})


def test_an_empty_slot_survives_a_full_restyle(tmp_path, metrics_all):
    """End to end: a kit with gaps still produces a provably unmoved tree."""
    metrics = metrics_all["slate-assurance"]
    skeleton_id = "01-host-landing"
    skeleton = skeletons.load(skeleton_id)
    draft = drafter.draft(skeleton, metrics)
    draft["copy"] = _required(draft, skeleton)
    kit = assemble_kit(draft, metrics)

    proof = apply_mod.restyle(skeleton_id, render_css(kit), kit["copy"],
                             tmp_path / "partial.html", tmp_path / "partial.proof.json")
    assert proof["tree_unchanged"] is True
    assert proof["slots_left_to_layout"]
    assert proof["slots_written_count"] == len(draft["copy"])
