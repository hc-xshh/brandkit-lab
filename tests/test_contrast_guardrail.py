"""The awkward source, and the guardrail that rescues it.

`slate-assurance.html` is greyscale with one accent colour, and it declares that
accent as a *text* colour on white. The naive pipeline -- brand colour in, brand
colour out -- produces 1.28:1 links. These tests assert both halves: that naive
really fails, and that the shipped kit does not.
"""

from __future__ import annotations

import pytest

from brandkit import drafter, skeletons, util
from brandkit.assemble_kit import assemble_kit, render_design_md
from brandkit.util import contrast_ratio

AWKWARD = "slate-assurance"


def test_the_naive_approach_really_does_fail(metrics_all):
    """If this ever passes without a guardrail, the example has lost its point."""
    colors = metrics_all[AWKWARD]["roles"]
    raw = util.contrast_ratio(colors["primary"], colors["paper"])
    assert raw < 1.5, "the awkward source is no longer awkward"
    assert colors["accent"] == "#ffd400"


def test_the_kits_primary_is_readable_and_the_accent_is_preserved(metrics_all):
    metrics = metrics_all[AWKWARD]
    skeleton = skeletons.load("01-host-landing")
    kit = assemble_kit(drafter.draft(skeleton, metrics), metrics)
    colors = kit["tokens"]["color"]

    assert colors["accent"] == "#ffd400", "the measured brand colour must survive"
    assert colors["primary"] != "#ffd400"
    assert contrast_ratio(colors["primary"], colors["paper"]) >= 4.5
    assert kit["provenance"]["color.primary"] == "derived"


def test_the_guardrail_explains_itself(metrics_all):
    metrics = metrics_all[AWKWARD]
    roles = metrics["roles"]
    kit = assemble_kit(drafter.draft(skeletons.load("01-host-landing"), metrics), metrics)
    by_token = {item["token"]: item for item in kit["guardrails"]}
    assert set(by_token) == {"primary", "ink-muted"}, sorted(by_token)

    item = by_token["primary"]
    assert item["before"] == "#ffd400"
    assert item["kept_as"] == "accent"
    assert item["contrast_before"] < 1.5
    worst = min(contrast_ratio(roles["primary"], roles[name]) for name in ("paper", "paper-alt"))
    assert str(worst) in item["reason"], item["reason"]
    assert item["after"] in render_design_md(kit)
    # The reason must describe the state *before* the repair, never after it.
    assert item["contrast_before"] < item["contrast_after"]
    assert item["contrast_after"] >= 4.5

    muted = by_token["ink-muted"]
    assert muted["before"] == roles["ink-muted"]
    assert muted["contrast_before"] < 4.5 <= muted["contrast_after"]


@pytest.mark.parametrize("source_id", ["northwind-outfitters", "pulse-analytics", "slate-assurance"])
def test_every_enforced_pair_clears_aa(metrics_all, source_id):
    metrics = metrics_all[source_id]
    for skeleton_id in ("01-host-landing", "04-insurance-longform"):
        kit = assemble_kit(
            drafter.draft(skeletons.load(skeleton_id), metrics), metrics
        )
        for pair, data in kit["contrast"].items():
            if not data["enforced"]:
                continue
            assert data["ratio"] >= data["floor"], f"{source_id} {skeleton_id} {pair}"


def test_well_behaved_sources_do_not_get_a_guardrail(metrics_all):
    """The guardrail must be quiet when nothing is wrong with the brand."""
    for source_id in ("northwind-outfitters", "pulse-analytics"):
        metrics = metrics_all[source_id]
        kit = assemble_kit(
            drafter.draft(skeletons.load("02-saas-marketing"), metrics), metrics
        )
        assert kit["guardrails"] == [], source_id
        assert kit["provenance"]["color.primary"] == "measured"


def test_a_dark_brand_is_handled_by_moving_the_other_way(metrics_all):
    """Contrast repair must lighten on a dark surface, not darken."""
    from brandkit.assemble_kit import apply_contrast_guardrail

    colors = {
        "paper": "#0b0b0f", "paper-alt": "#15151b", "ink": "#0d0d10",
        "ink-muted": "#1a1a20", "primary": "#0a0a12", "primary-ink": "#ffffff",
        "border": "#22222a", "accent": "#4b4b57",
    }
    derived: set = set()
    guardrails: list = []
    fixed = apply_contrast_guardrail(colors, guardrails, derived)
    assert util.relative_luminance(fixed["ink"]) > util.relative_luminance(colors["ink"])
    assert contrast_ratio(fixed["ink"], fixed["paper"]) >= 4.5
    assert guardrails


def test_an_unsatisfiable_palette_is_refused_not_shipped(metrics_all):
    """Mid grey cannot carry text at 4.5:1 in either direction: refuse the kit."""
    from brandkit.assemble_kit import KitError

    metrics = dict(metrics_all["pulse-analytics"])
    metrics["roles"] = dict(
        metrics["roles"], paper="#808080", **{"paper-alt": "#808080", "ink": "#808080",
                                              "primary": "#808080", "ink-muted": "#808080"}
    )
    with pytest.raises(KitError) as excinfo:
        assemble_kit(drafter.draft(skeletons.load("01-host-landing"), metrics), metrics)
    assert "contrast gate failed" in str(excinfo.value)
