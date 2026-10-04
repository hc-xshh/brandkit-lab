"""Measurement: the stage that decides what the brand actually said.

The fixtures here are the three example sources, which between them cover a warm
serif brand, a cool SaaS brand and the deliberately awkward greyscale one.
"""

from __future__ import annotations

import pytest

from brandkit import measure, util
from brandkit.util import contrast_ratio

SOURCES = ("northwind-outfitters", "pulse-analytics", "slate-assurance")


def test_measurement_finds_a_coherent_palette(metrics_all):
    for source_id, metrics in metrics_all.items():
        roles = metrics["roles"]
        assert len(metrics["palette"]["counts"]) >= 5, source_id
        assert util.HEX_RE.match(roles["paper"])
        assert util.HEX_RE.match(roles["ink"])
        assert util.HEX_RE.match(roles["primary"])
        assert contrast_ratio(roles["ink"], roles["paper"]) >= 4.5, source_id


def test_the_page_surface_is_the_pages_own_surface(metrics_all):
    """A loud hero band must not become the paper colour of a cream site."""
    for source_id, metrics in metrics_all.items():
        page_colours = set(metrics["palette"]["page_surface_counts"])
        assert metrics["roles"]["paper"] in page_colours, source_id


def test_font_roles_are_separated(metrics_all):
    for source_id, metrics in metrics_all.items():
        roles = metrics["fonts"]["roles"]
        assert roles["heading-font"]
        assert roles["body-font"]
        assert roles["heading-font"] != roles["body-font"], source_id
        assert roles["heading-font"] in metrics["fonts"]["families"]


def test_radius_and_elevation_scales_are_measured(metrics_all):
    for source_id, metrics in metrics_all.items():
        assert metrics["radius"]["scale"], source_id
        for value in metrics["radius"]["scale"]:
            assert value.endswith("px")
        assert metrics["elevation"]["values"], source_id
        assert "rgba(" in metrics["elevation"]["roles"]["card"]


def test_a_multi_part_shadow_stays_one_elevation(metrics_all):
    """Two box-shadow components are one designer decision, not two."""
    card = metrics_all["northwind-outfitters"]["elevation"]["roles"]["card"]
    assert card.count("rgba(") == 2
    assert card.startswith("0 1px 2px")


def test_every_source_yields_every_copy_role(metrics_all):
    expected = {"h1", "h2", "body", "lead", "cta", "eyebrow", "meta", "footer"}
    for source_id, metrics in metrics_all.items():
        pool = metrics["copy_pool"]
        assert expected <= set(pool), f"{source_id} is missing {expected - set(pool)}"
        assert len(pool["h1"]) == 1, "a page has exactly one h1 in the pool"
        for key, values in pool.items():
            assert values, key
            assert len(values) == len(set(values)), f"{source_id}.{key} has duplicates"


def test_class_names_win_over_tag_names(metrics_all):
    """`<p class="eyebrow">` is an eyebrow, not a body paragraph."""
    pool = metrics_all["northwind-outfitters"]["copy_pool"]
    assert "Field-tested since 2011" in pool["eyebrow"]
    assert "Field-tested since 2011" not in pool["body"]


def test_the_derived_set_is_honest(metrics_all):
    for _source_id, metrics in metrics_all.items():
        derived = set(metrics["derived_tokens"])
        roles = metrics["roles"]
        if "paper-alt" in derived:
            assert roles["paper-alt"] not in metrics["palette"]["background_counts"]
        if "shadow-raised" in derived:
            assert metrics["elevation"]["roles"]["raised"] != metrics["elevation"]["roles"]["card"]


def test_measurement_is_reproducible(repo_root):
    for source_id in SOURCES:
        path = repo_root / "sources" / f"{source_id}.html"
        assert measure.measure_source(path) == measure.measure_source(path)


def test_spacing_scale_is_ordered_and_bounded(metrics_all):
    for source_id, metrics in metrics_all.items():
        spacing = metrics["spacing"]
        assert spacing == sorted(set(spacing), key=lambda v: float(v[:-2])), source_id
        assert len(spacing) <= 16, "a spacing scale should be a scale, not a dump"
        assert all(float(v[:-2]) >= 0 for v in spacing)


def test_measuring_a_url_is_opt_in_only():
    """No import-time network, and `--source-url` is the only path that fetches."""
    import brandkit.measure as module

    assert module.USER_AGENT.startswith("brandkit-lab/")
    # the URL path is reached only through the explicit CLI flag
    with pytest.raises(SystemExit):
        module.main(["--out", "/dev/null"])  # neither --source nor --source-url
    with pytest.raises(SystemExit):
        module.main(["--source", "sources/x.html", "--source-url", "https://example.com",
                     "--out", "/dev/null"])  # both at once is an error too


def test_a_font_shorthand_does_not_leak_its_size_into_the_family():
    """`font: 700 32px/1.2 "Iowan Old Style", serif` names one family.

    Splitting the shorthand on commas alone yields `32px/1.2 "Iowan Old Style"`,
    which would become a font token. A page measured from a real URL hits this
    on the very first declaration it owns.
    """
    html = """<html><head><style>
      body { font: 16px/1.6 system-ui, sans-serif; }
      h1 { font: italic small-caps 700 32px/1.2 "Iowan Old Style", Georgia, serif; }
      code { font-family: "B612 Mono", monospace; }
      p { font: 1rem serif; }
    </style></head><body><h1>Heading</h1><p>Body</p></body></html>"""
    metrics = measure.measure_html(html, "shorthand", "test", "inline")
    assert metrics["fonts"]["roles"]["heading-font"] == "Iowan Old Style"
    assert metrics["fonts"]["roles"]["body-font"] == "system-ui"
    assert "B612 Mono" in metrics["fonts"]["families"], "a digit in a real name is not a size"
    leaked = [f for f in metrics["fonts"]["families"] if "px" in f or "/" in f or "rem" in f]
    assert not leaked, f"shorthand leftovers in the font families: {leaked}"
