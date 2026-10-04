"""The registry has to be internally consistent, and the skeletons have to agree
with it. A drift between `blocks.py`, the skeletons' markup and their `TREE.md`
is the failure mode this file exists to catch.
"""

from __future__ import annotations

import re

import pytest

from brandkit import skeletons
from brandkit.blocks import (
    DEFAULT,
    Registry,
    RegistryError,
    RepeatRule,
    UnknownBlockError,
    build_default_registry,
)

KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def test_registry_ids_are_kebab_and_unique():
    ids = DEFAULT.known()
    assert ids == sorted(set(ids)), "block ids must be unique and sorted"
    for block_id in ids:
        assert KEBAB.match(block_id), f"{block_id} is not kebab-case"


def test_every_block_declares_geometry_and_some_slot():
    for block_id in DEFAULT.known():
        block = DEFAULT.resolve(block_id)
        assert block.geometry.get("band") in ("contained", "full-bleed")
        assert block.geometry.get("columns")
        assert block.all_fields, f"{block_id} declares no copy slots"


def test_required_and_optional_do_not_overlap():
    for block_id in DEFAULT.known():
        block = DEFAULT.resolve(block_id)
        assert not set(block.required) & set(block.optional), block_id


def test_repeat_rules_are_sane_and_reference_declared_fields():
    for block_id in DEFAULT.known():
        block = DEFAULT.resolve(block_id)
        if not block.repeat:
            continue
        rule = block.repeat
        assert KEBAB.match(rule.name)
        assert rule.min <= rule.default <= rule.max
        assert rule.min >= 1
        for field in rule.fields:
            assert field in block.all_fields, f"{block_id}: {field} is not a slot"


def test_repeat_rule_rejects_impossible_ranges():
    with pytest.raises(RegistryError):
        RepeatRule(name="x", fields=("a",), min=5, max=2, default=3)
    with pytest.raises(RegistryError):
        RepeatRule(name="x", fields=(), min=1, max=2, default=1)
    with pytest.raises(RegistryError):
        RepeatRule(name="NotKebab", fields=("a",), min=1, max=2, default=1)


def test_every_seed_block_is_used_by_at_least_one_skeleton():
    used = {block for blocks in DEFAULT.skeletons.values() for block in blocks}
    assert used == set(DEFAULT.known()), (
        f"unused blocks: {sorted(set(DEFAULT.known()) - used)}; "
        f"undefined bindings: {sorted(used - set(DEFAULT.known()))}"
    )


def test_every_skeleton_is_registered_and_binds_only_known_blocks():
    assert set(skeletons.load_all()) == set(DEFAULT.skeletons)
    for _skeleton_id, block_ids in DEFAULT.skeletons.items():
        for block_id in block_ids:
            assert block_id in DEFAULT


def test_skeletons_validate_against_the_registry(skeleton_all):
    problems: dict[str, list[str]] = {}
    for skeleton_id, skeleton in skeleton_all.items():
        found = skeletons.validate(skeleton)
        if found:
            problems[skeleton_id] = found
    assert not problems, problems


def test_html_bands_match_the_registry_order(skeleton_all):
    for skeleton_id, skeleton in skeleton_all.items():
        assert [band["block"] for band in skeleton.bands] == DEFAULT.skeleton_blocks(
            skeleton_id
        ), skeleton_id


def test_tree_md_matches_the_html(skeleton_all):
    """`TREE.md` is documentation, so it has to be true documentation."""
    for skeleton_id, skeleton in skeleton_all.items():
        tree = skeleton.tree_path.read_text(encoding="utf-8")
        for band in skeleton.bands:
            assert f"`{band['band']}`" in tree, f"{skeleton_id}: band {band['band']} missing"
            assert f"`{band['block']}`" in tree, (
                f"{skeleton_id}: block {band['block']} missing from TREE.md"
            )
        rows = re.findall(r"^\|\s*\d+\s*\|", tree, flags=re.M)
        assert len(rows) == len(skeleton.bands), (
            f"{skeleton_id}: TREE.md lists {len(rows)} bands, the page has {len(skeleton.bands)}"
        )


def test_token_contract_is_declared_in_every_skeleton(skeleton_all):
    from brandkit import tokens

    for skeleton_id, skeleton in skeleton_all.items():
        declared = skeleton.declared_tokens()
        assert sorted(declared) == sorted(tokens.all_vars()), skeleton_id


def test_a_fresh_registry_is_independent_of_the_default():
    other = build_default_registry()
    other.register(
        "sandbox-band",
        geometry={"band": "contained", "columns": 1},
        required=("h2",),
    )
    assert "sandbox-band" not in DEFAULT
    assert "sandbox-band" in other


def test_registry_resolve_rejects_unknown_ids():
    with pytest.raises(UnknownBlockError):
        DEFAULT.resolve("no-such-block")
    with pytest.raises(RegistryError):
        Registry().register("Bad_ID", geometry={"band": "contained"})
    with pytest.raises(RegistryError):
        Registry().register("no-geometry", geometry={})
