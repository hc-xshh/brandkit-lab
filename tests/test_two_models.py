"""The invariant the whole design exists for.

Two *different* drafts -- standing in for two different models, or the same model
run twice on different days -- must produce **identical measured-fact tokens**.
They may disagree about every sentence; they may not disagree about a hex, a
font, a radius or a shadow, because neither of them is allowed to write one.

`assemble_kit` is the only writer, and it raises `DraftContractError` if a draft
tries to carry design facts. This file tests the invariant from both ends.
"""

from __future__ import annotations

import re

import pytest

from brandkit import drafter, skeletons
from brandkit.assemble_kit import (
    DraftContractError,
    assemble_kit,
    render_css,
    render_design_md,
    render_tokens_csv,
)

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
MODEL_A = "rules-v1"
MODEL_B = "alt-v1"


def test_the_two_rule_models_really_do_disagree_about_the_words(metrics_all):
    """A meaningless invariant if the two drafts are secretly the same draft."""
    skeleton = skeletons.load("02-saas-marketing")
    metrics = metrics_all["pulse-analytics"]
    a = drafter.draft(skeleton, metrics, model=MODEL_A)
    b = drafter.draft(skeleton, metrics, model=MODEL_B)
    assert a["copy"] != b["copy"]
    assert set(a["copy"]) == set(b["copy"]), "both models must fill the same slots"


@pytest.mark.parametrize("source_id", ["northwind-outfitters", "pulse-analytics", "slate-assurance"])
@pytest.mark.parametrize(
    "skeleton_id",
    ["01-host-landing", "02-saas-marketing", "03-product-security", "04-insurance-longform"],
)
def test_two_models_produce_identical_tokens(metrics_all, source_id, skeleton_id):
    metrics = metrics_all[source_id]
    skeleton = skeletons.load(skeleton_id)

    kit_a = assemble_kit(drafter.draft(skeleton, metrics, model=MODEL_A), metrics)
    kit_b = assemble_kit(drafter.draft(skeleton, metrics, model=MODEL_B), metrics)

    # 1. the tokens themselves, byte for byte
    assert kit_a["tokens"] == kit_b["tokens"]
    assert kit_a["provenance"] == kit_b["provenance"]
    assert kit_a["contrast"] == kit_b["contrast"]
    assert kit_a["guardrails"] == kit_b["guardrails"]
    assert kit_a["fingerprints"]["tokens"] == kit_b["fingerprints"]["tokens"]

    # 2. everything downstream of the tokens
    assert render_css(kit_a) == render_css(kit_b)
    assert render_tokens_csv(kit_a) == render_tokens_csv(kit_b)
    assert set(HEX.findall(render_design_md(kit_a))) == set(HEX.findall(render_design_md(kit_b)))

    # 3. and the only difference is the copy
    differing = {key for key in kit_a if kit_a[key] != kit_b[key]}
    assert differing <= {"copy", "draft", "fingerprints"}
    assert kit_a["copy"] != kit_b["copy"]

    # 4. the drafts themselves carried no design facts
    for draft in (drafter.draft(skeleton, metrics, model=MODEL_A),
                  drafter.draft(skeleton, metrics, model=MODEL_B)):
        assert "tokens" not in draft and "css" not in draft


@pytest.mark.parametrize("smuggled", ["tokens", "css", "theme", "palette", "fonts"])
def test_a_draft_cannot_smuggle_design_facts(metrics_all, smuggled):
    metrics = metrics_all["northwind-outfitters"]
    skeleton = skeletons.load("01-host-landing")
    draft = drafter.draft(skeleton, metrics)
    draft[smuggled] = {"paper": "#ff00ff"}
    with pytest.raises(DraftContractError):
        assemble_kit(draft, metrics)


def test_tokens_come_from_the_source_not_from_the_draft(metrics_all, paired):
    """A model that changes a string changes a string, and nothing else."""
    metrics = metrics_all["pulse-analytics"]
    skeleton = skeletons.load("01-host-landing")
    draft = drafter.draft(skeleton, metrics)
    baseline = assemble_kit(draft, metrics)

    edited = dict(draft)
    edited["copy"] = {key: value.upper() for key, value in draft["copy"].items()}
    edited["model"] = "a-different-model-entirely"
    after = assemble_kit(edited, metrics)

    assert after["tokens"] == baseline["tokens"]
    assert render_css(after) == render_css(baseline)


def test_the_same_source_gives_the_same_tokens_on_every_skeleton(paired):
    """One brand kit is one kit: the layout it lands on does not change it."""
    by_source: dict[str, set[str]] = {}
    for (source_id, _skeleton_id), (_draft, kit, _skeleton) in paired().items():
        by_source.setdefault(source_id, set()).add(kit["fingerprints"]["tokens"])
    for source_id, fingerprints in by_source.items():
        assert len(fingerprints) == 1, (
            f"{source_id} produced {len(fingerprints)} different token sets across skeletons"
        )


def test_kit_json_differs_between_models_only_in_copy(metrics_all):
    import json

    from brandkit.util import dumps_stable

    metrics = metrics_all["slate-assurance"]
    skeleton = skeletons.load("04-insurance-longform")
    kit_a = assemble_kit(drafter.draft(skeleton, metrics, model=MODEL_A), metrics)
    kit_b = assemble_kit(drafter.draft(skeleton, metrics, model=MODEL_B), metrics)

    text_a = dumps_stable(kit_a)
    text_b = dumps_stable(kit_b)
    assert text_a != text_b
    for key in ("tokens", "provenance", "contrast", "guardrails", "metrics_summary"):
        assert json.loads(text_a)[key] == json.loads(text_b)[key]
