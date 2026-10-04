"""Which token may carry text, and which may not.

`kit.css` publishes a decorative `--accent` that is deliberately allowed to sit
below the WCAG AA floor: the whole point of the guardrail is that a brand's own
colour survives where colour is decoration. That decision is only defensible if
no skeleton ever paints text on it. These tests enforce the other half of the
bargain.
"""

from __future__ import annotations

import pytest

from brandkit import drafter, measure, skeletons, tokens
from brandkit.assemble_kit import AA_BODY, assemble_kit
from brandkit.util import contrast_ratio

#: Tokens that may appear as a *background* behind text in a skeleton.
MAY_CARRY_TEXT = {"paper", "paper-alt", "primary", "ink"}

#: Tokens that may only be used for decoration: rules, bars, chips, borders.
DECORATIVE_ONLY = {"accent", "border"}

ALL_SKELETONS = ("01-host-landing", "02-saas-marketing", "03-product-security",
                 "04-insurance-longform")


def rules_by_selector(html: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for selector, prop, value in measure.collect_declarations(html):
        out.setdefault(selector, {})[prop] = value
    return out


def test_no_skeleton_paints_text_on_a_decorative_token(skeleton_all):
    offenders = []
    for skeleton_id, skeleton in skeleton_all.items():
        for selector, decls in rules_by_selector(skeleton.html).items():
            background = next(
                (value for prop, value in decls.items()
                 if prop.startswith("background") and value.strip() != "none"),
                "",
            )
            carries_text = "color" in decls or "font-size" in decls
            for token in DECORATIVE_ONLY:
                if f"var(--{token})" in background and carries_text:
                    offenders.append(f"{skeleton_id}: {selector} puts text on var(--{token})")
    assert not offenders, offenders


def test_the_decorative_decision_is_worth_making(paired):
    """`--accent` really is below the floor for one brand, on purpose."""
    _draft, kit, _skeleton = paired()[("slate-assurance", "01-host-landing")]
    accent = kit["contrast"]["accent-on-paper"]["ratio"]
    assert accent < 4.5
    assert kit["contrast"]["accent-on-paper"]["enforced"] is False
    assert kit["tokens"]["color"]["accent"] == "#ffd400"


def test_enforced_pair_list_and_decorative_list_are_disjoint():
    assert not set(tokens.enforced_pairs()) & set(tokens.DECORATIVE_PAIRS)
    assert set(tokens.report_pairs()) == set(tokens.enforced_pairs()) | set(tokens.DECORATIVE_PAIRS)


@pytest.mark.parametrize("source_id", ["northwind-outfitters", "pulse-analytics", "slate-assurance"])
@pytest.mark.parametrize("skeleton_id", ALL_SKELETONS)
def test_text_tokens_clear_the_floor_on_every_surface(metrics_all, source_id, skeleton_id):
    """Body text and secondary text are legible on both surfaces of every kit."""
    metrics = metrics_all[source_id]
    kit = assemble_kit(drafter.draft(skeletons.load(skeleton_id), metrics), metrics)
    colors = kit["tokens"]["color"]
    surfaces = {"paper": colors["paper"], "paper-alt": colors["paper-alt"]}
    for surface_name, surface in surfaces.items():
        for token in ("ink", "ink-muted"):
            ratio = contrast_ratio(colors[token], surface)
            assert ratio >= AA_BODY, f"{source_id}/{skeleton_id}: {token} on {surface_name}"
