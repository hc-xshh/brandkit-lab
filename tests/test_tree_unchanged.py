"""A restyle changes the theme and the words. It does not move the page.

Every (source, skeleton) pair is bound for real, and the proof written next to
the page is checked. Then the guard is attacked: if a mutation *does* move the
tree, `apply` must refuse rather than write.
"""

from __future__ import annotations

import json

import pytest

from brandkit import apply as apply_mod
from brandkit import htmltree
from brandkit.assemble_kit import render_css

PAIRS = [
    (source, skeleton)
    for source in ("northwind-outfitters", "pulse-analytics", "slate-assurance")
    for skeleton in ("01-host-landing", "02-saas-marketing", "03-product-security",
                     "04-insurance-longform")
]


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_restyle_keeps_the_tree(metrics_all, paired, tmp_path, source_id, skeleton_id):
    _draft, kit, skeleton = paired()[(source_id, skeleton_id)]
    out = tmp_path / f"{source_id}--{skeleton_id}.html"
    proof_file = tmp_path / f"{source_id}--{skeleton_id}.proof.json"

    proof = apply_mod.restyle(skeleton_id, render_css(kit), kit["copy"], out, proof_file)

    assert proof["tree_unchanged"] is True
    assert proof["signature_before"] == proof["signature_after"]
    assert proof["bands_before"] == proof["bands_after"]
    assert proof["repeats_before"] == proof["repeats_after"]
    assert proof["elements_before"] == proof["elements_after"]

    # the band list is not merely equal, it is the skeleton's own band list
    assert proof["bands_after"] == skeleton.bands
    assert json.loads(proof_file.read_text(encoding="utf-8")) == proof

    # and the file on disk really is the page the proof describes
    written = out.read_text(encoding="utf-8")
    assert htmltree.signature_hash(htmltree.parse(written)) == proof["signature_after"]
    assert proof["slots_written"] and proof["slots_written_count"] > 0


@pytest.mark.parametrize("source_id,skeleton_id", PAIRS)
def test_every_band_and_repeat_survives(metrics_all, paired, source_id, skeleton_id):
    _draft, kit, skeleton = paired()[(source_id, skeleton_id)]
    after_html, _written = apply_mod.bind(skeleton.html, render_css(kit), kit["copy"])
    after = htmltree.parse(after_html)
    assert htmltree.band_list(after) == skeleton.bands
    assert htmltree.repeat_counts(after) == skeleton.repeats
    assert htmltree.element_count(after) == htmltree.element_count(skeleton.root)
    assert htmltree.slot_keys(after) == htmltree.slot_keys(skeleton.root)


def test_guard_refuses_when_a_mutation_moves_the_tree(monkeypatch, metrics_all, paired, tmp_path):
    """The proof is not decoration: a structural change must abort the write."""
    _draft, kit, skeleton = paired()[("pulse-analytics", "02-saas-marketing")]
    real_bind_copy = apply_mod.bind_copy

    def sneaky_bind_copy(html, copy):
        out, written = real_bind_copy(html, copy)
        # a "cosmetic" change that is in fact a change to the tree
        return out.replace("</body>", "<div class=\"sneaky\"></div></body>", 1), written

    monkeypatch.setattr(apply_mod, "bind_copy", sneaky_bind_copy)
    out = tmp_path / "moved.html"
    with pytest.raises(apply_mod.ApplyError):
        apply_mod.restyle("02-saas-marketing", render_css(kit), kit["copy"], out,
                          tmp_path / "moved.proof.json")
    assert not out.exists(), "a refused restyle must not leave a file behind"


def test_signature_detects_reordering():
    before = htmltree.parse("<body><section data-band='a'></section>"
                            "<section data-band='b'></section></body>")
    after = htmltree.parse("<body><section data-band='b'></section>"
                           "<section data-band='a'></section></body>")
    assert htmltree.signature_hash(before) != htmltree.signature_hash(after)


def test_signature_ignores_text_but_not_attributes():
    a = htmltree.parse("<p data-slot='x.h1'>hello</p>")
    b = htmltree.parse("<p data-slot='x.h1'>goodbye, and a much longer string</p>")
    c = htmltree.parse("<p data-slot='x.h2'>hello</p>")
    assert htmltree.signature_hash(a) == htmltree.signature_hash(b)
    assert htmltree.signature_hash(a) != htmltree.signature_hash(c)


def test_token_binding_replaces_only_the_marked_block(skeleton_all):
    skeleton = skeleton_all["01-host-landing"]
    kit_css = ":root {\n  --paper: #123456;\n}\n"
    bound = apply_mod.bind_tokens(skeleton.html, kit_css)
    assert "--paper: #123456;" in bound
    assert bound.count(apply_mod.TOKEN_START) == 1
    # everything outside the markers is untouched
    assert bound.split(apply_mod.TOKEN_END)[1] == skeleton.html.split(apply_mod.TOKEN_END)[1]
    assert bound[:bound.index(apply_mod.TOKEN_START)] == \
        skeleton.html[:skeleton.html.index(apply_mod.TOKEN_START)]


def test_marker_problems_are_refused(skeleton_all):
    skeleton = skeleton_all["01-host-landing"]
    with pytest.raises(apply_mod.ApplyError):
        apply_mod.bind_tokens("<html><body>no markers</body></html>", ":root{}")
    doubled = skeleton.html.replace(apply_mod.TOKEN_END,
                                   apply_mod.TOKEN_END + apply_mod.TOKEN_START, 1)
    assert doubled.count(apply_mod.TOKEN_START) == 2
    with pytest.raises(apply_mod.ApplyError):
        apply_mod.bind_tokens(doubled, ":root{}")
    with pytest.raises(apply_mod.ApplyError):
        apply_mod.extract_token_block("body { color: red }")


def test_copy_is_escaped_not_interpreted(skeleton_all):
    skeleton = skeleton_all["01-host-landing"]
    out, written = apply_mod.bind_copy(
        skeleton.html, {"hero-center.h1": "Fish & chips <script>alert(1)</script>"}
    )
    assert written == ["hero-center.h1"]
    assert "Fish &amp; chips &lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "<script>" not in out
