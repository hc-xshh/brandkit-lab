"""DESIGN.md is rendered from the same kit that renders kit.css.

If a colour, a radius or a shadow appears in the design document but not in the
stylesheet, the document is lying to whoever reads it. This file makes that
impossible to ship.
"""

from __future__ import annotations

import re

import pytest

from brandkit import tokens
from brandkit.assemble_kit import (
    design_md_hex_problems,
    render_css,
    render_design_md,
    render_tokens_csv,
)

PAIRS = [
    (source, skeleton)
    for source in ("northwind-outfitters", "pulse-analytics", "slate-assurance")
    for skeleton in ("01-host-landing", "02-saas-marketing", "03-product-security",
                     "04-insurance-longform")
]

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
RADIUS = re.compile(r"`(--radius-[a-z]+)` \| `([^`]+)`")
SHADOW = re.compile(r"`(--shadow-[a-z]+)` \| `([^`]+)`")
#: A row of a DESIGN.md token table: ``| `--paper` | #ffffff | measured |``
TABLE_ROW = re.compile(r"^\|\s*`--[a-z-]+`")


def design_token_tables(design: str) -> str:
    """Only the token tables, not the prose.

    The Guardrails section deliberately quotes the colour a guardrail threw
    away, so a whole-document hex scan would be wrong: it would flag the
    *discarded* measurement as an inconsistency. The tables are the part that
    must agree with the stylesheet byte for byte.
    """
    return "\n".join(line for line in design.splitlines() if TABLE_ROW.match(line))


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_every_hex_in_the_design_tables_is_in_the_css(paired, source_id, skeleton_id):
    _draft, kit, _skeleton = paired()[(source_id, skeleton_id)]
    # One implementation, shared with the eval harness, so the two can never
    # disagree about what "DESIGN.md matches kit.css" means.
    assert design_md_hex_problems(kit) == []
    # And the tables really are the part being compared.
    tables = design_token_tables(render_design_md(kit))
    assert HEX.findall(tables), "the token tables should contain hexes"


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_a_guardrail_either_keeps_the_measured_colour_or_drops_it(paired, source_id, skeleton_id):
    """The document must not claim a colour is available when it was dropped."""
    _draft, kit, _skeleton = paired()[(source_id, skeleton_id)]
    css = render_css(kit)
    colors = kit["tokens"]["color"]
    for item in kit["guardrails"]:
        if item.get("kept_as"):
            assert colors[item["kept_as"]] == item["before"]
        else:
            assert item["before"] not in css, (
                f"{item['token']}: DESIGN.md says {item['before']} was replaced but kit.css "
                "still ships it"
            )
        assert item["after"] in css


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_radius_and_shadow_values_agree(paired, source_id, skeleton_id):
    _draft, kit, _skeleton = paired()[(source_id, skeleton_id)]
    design = render_design_md(kit)
    css = render_css(kit)
    for var, value in RADIUS.findall(design) + SHADOW.findall(design):
        assert f"{var}: {value};" in css, f"{var} is {value!r} in DESIGN.md, missing in CSS"


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_css_publishes_exactly_the_frozen_contract(paired, source_id, skeleton_id):
    _draft, kit, _skeleton = paired()[(source_id, skeleton_id)]
    css = render_css(kit)
    published = set(re.findall(r"(--[a-z-]+):", css))
    assert published == set(tokens.all_vars()), sorted(set(tokens.all_vars()) ^ published)


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_tokens_csv_matches_the_css(paired, source_id, skeleton_id):
    import csv
    import io

    _draft, kit, _skeleton = paired()[(source_id, skeleton_id)]
    csv_text = render_tokens_csv(kit)
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == ["Token", "Color", "Font", "Value"]
    css = render_css(kit)
    seen = set()
    for row in rows[1:]:
        var, color, font, value = row
        seen.add(var)
        assert f"{var}:" in css
        filled = [cell for cell in (color, font, value) if cell]
        assert len(filled) == 1, f"{var} should fill exactly one column: {row}"
    assert seen == set(tokens.all_vars())


def test_design_md_names_the_fingerprint_it_was_rendered_from(paired):
    _draft, kit, _skeleton = paired()[("northwind-outfitters", "01-host-landing")]
    design = render_design_md(kit)
    assert kit["fingerprints"]["tokens"][:16] in design
    assert kit["source"]["sha256"][:16] in design


def test_design_md_reports_the_guardrail_it_applied(paired):
    _draft, kit, _skeleton = paired()[("slate-assurance", "01-host-landing")]
    design = render_design_md(kit)
    assert kit["guardrails"], "the awkward source must trip the guardrail"
    for item in kit["guardrails"]:
        assert item["before"] in design and item["after"] in design
