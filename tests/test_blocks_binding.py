"""Binding rules: new skeletons may grow the registry, old ones may not.

These are the three rules the brief is most likely to be tested on, so they are
tested directly against a throwaway registry -- `DEFAULT` is never mutated by the
suite.
"""

from __future__ import annotations

import pytest

from brandkit.blocks import (
    DEFAULT,
    RegistryError,
    UnknownBlockError,
    build_default_registry,
)

NEW_BLOCK = {
    "id": "timeline-band",
    "geometry": {"band": "contained", "columns": 1, "align": "start", "media": "none"},
    "required": ("h2", "item-label"),
    "optional": ("eyebrow", "item-body"),
    "repeat": {"name": "step", "fields": ("item-label", "item-body"),
               "min": 2, "max": 6, "default": 4},
    "notes": "A vertical timeline; invented by a new skeleton, registered on demand.",
}


@pytest.fixture()
def registry() -> build_default_registry:  # type: ignore[valid-type]
    return build_default_registry()


def test_a_known_block_binds_into_a_known_skeleton(registry):
    block = registry.bind("02-saas-marketing", "faq-list")
    assert block.id == "faq-list"
    assert registry.skeleton_blocks("02-saas-marketing").count("faq-list") == 1


def test_unknown_block_on_a_new_skeleton_is_registered_then_bound(registry):
    block = registry.bind(
        "05-timeline-landing", NEW_BLOCK["id"], skeleton_is_new=True, definition=NEW_BLOCK
    )
    assert block.id == "timeline-band"
    assert block.repeat.name == "step"
    assert "timeline-band" in registry
    assert registry.skeleton_blocks("05-timeline-landing") == ["timeline-band"]


def test_unknown_block_invented_on_an_old_skeleton_is_rejected(registry):
    with pytest.raises(UnknownBlockError) as excinfo:
        registry.bind("01-host-landing", NEW_BLOCK["id"], definition=NEW_BLOCK)
    assert "frozen" in str(excinfo.value)
    assert "timeline-band" not in registry, "a rejected bind must not mutate the registry"
    assert "timeline-band" not in registry.skeleton_blocks("01-host-landing")


def test_an_old_skeleton_may_still_use_blocks_that_already_exist(registry):
    registry.bind("01-host-landing", "faq-list")
    assert registry.skeleton_blocks("01-host-landing")[-1] == "faq-list"


def test_an_unknown_block_without_a_definition_is_rejected(registry):
    with pytest.raises(UnknownBlockError):
        registry.bind("05-brand-new", "made-up-band", skeleton_is_new=True)


def test_a_new_skeleton_may_not_steal_an_existing_id(registry):
    with pytest.raises(RegistryError):
        registry.bind("01-host-landing", "faq-list", skeleton_is_new=True)


def test_a_new_skeleton_may_not_redefine_an_existing_block(registry):
    with pytest.raises(RegistryError):
        registry.bind(
            "05-other", "faq-list", skeleton_is_new=True,
            definition={"geometry": {"band": "contained", "columns": 1}},
        )


def test_registering_the_same_id_twice_is_a_bug(registry):
    with pytest.raises(RegistryError):
        registry.register("faq-list", geometry={"band": "contained", "columns": 1})
    registry.register("faq-list", geometry={"band": "contained", "columns": 1}, replace=True)


def test_binding_requires_declared_skeleton_blocks(registry):
    with pytest.raises(UnknownBlockError):
        registry.skeleton_blocks("99-does-not-exist")


def test_the_default_registry_is_untouched_by_the_suite():
    """Whatever the tests do to their own registries, the shipped one is intact."""
    assert "timeline-band" not in DEFAULT
    assert DEFAULT.skeleton_blocks("01-host-landing") == [
        "nav-bar", "hero-center", "logo-strip", "feature-grid-3", "stat-band",
        "cta-banner", "footer-legal",
    ]
    assert len(DEFAULT.known()) == 15


def test_geometry_is_carried_through_registration(registry):
    block = registry.bind("05-x", "timeline-band", skeleton_is_new=True,
                          definition=NEW_BLOCK)
    assert block.geometry["band"] == "contained"
    assert block.geometry["columns"] == 1
    assert block.required == ("h2", "item-label")
    assert block.optional == ("eyebrow", "item-body")


def test_bad_definitions_are_rejected(registry):
    with pytest.raises(RegistryError):
        registry.bind(
            "05-y", "no-geometry-band", skeleton_is_new=True,
            definition={"geometry": {}, "required": ("h2",)},
        )
    with pytest.raises(RegistryError):
        registry.bind(
            "05-z", "overlapping-band", skeleton_is_new=True,
            definition={"geometry": {"band": "contained"},
                        "required": ("h2",), "optional": ("h2",)},
        )
    with pytest.raises(RegistryError):
        registry.bind(
            "05-w", "bad-repeat-band", skeleton_is_new=True,
            definition={"geometry": {"band": "contained"}, "required": ("h2",),
                        "repeat": {"name": "x", "fields": ("nope",), "min": 1, "max": 2,
                                   "default": 1}},
        )
