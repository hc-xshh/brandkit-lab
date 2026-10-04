"""The block registry — the contract between skeletons and copy.

Every band in every skeleton is an instance of a registered block. A block
declares:

``geometry``
    how the band lays out (band width, column count, alignment, media).
``required``
    copy slots that must be filled with a non-empty string.
``optional``
    copy slots that may be empty; an empty slot keeps whatever the skeleton
    already had there.
``repeat``
    the repeat rule for the block's repeated unit: which slots repeat, and the
    minimum/maximum number of repeats the skeleton may contain.

The three rules that matter operationally:

1. **Unknown id on a new skeleton** -> :func:`Registry.bind` registers the block
   from the supplied definition and binds it in one call.
2. **Unknown id invented on an old skeleton** -> rejected. Existing skeletons are
   frozen: you cannot make one of them reference a block nobody defined.
3. **Redefining a known id** -> rejected. Registering an id twice is a bug, not a
   feature; pass ``replace=True`` explicitly if you really mean it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


class BlockError(Exception):
    """Base class for registry failures."""


class UnknownBlockError(BlockError):
    """An id was used that the registry does not know."""


class RegistryError(BlockError):
    """A definition was rejected (duplicate id, bad id, bad geometry)."""


@dataclass(frozen=True)
class RepeatRule:
    """How a block repeats its unit inside a page.

    ``name`` is the public name of the repeated unit; ``fields`` are the copy
    slots that repeat with it. ``min``/``max`` bound what the layout tolerates;
    ``default`` is what the drafter emits when nothing else dictates a count.
    A skeleton's own repeated markup always wins over ``default``.
    """

    name: str
    fields: tuple[str, ...]
    min: int
    max: int
    default: int

    def __post_init__(self) -> None:
        if not KEBAB_RE.match(self.name):
            raise RegistryError(f"repeat name {self.name!r} is not kebab-case")
        if not self.fields:
            raise RegistryError(f"repeat {self.name!r} declares no fields")
        if self.min < 1 or self.max < self.min:
            raise RegistryError(
                f"repeat {self.name!r} has an impossible range {self.min}..{self.max}"
            )
        if not (self.min <= self.default <= self.max):
            raise RegistryError(
                f"repeat {self.name!r} default {self.default} outside "
                f"{self.min}..{self.max}"
            )

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "fields": list(self.fields),
            "min": self.min,
            "max": self.max,
            "default": self.default,
        }


@dataclass(frozen=True)
class Block:
    id: str
    geometry: dict
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    repeat: RepeatRule | None = None
    notes: str = ""

    @property
    def slots(self) -> tuple[str, ...]:
        """Single-value slots (everything that is not part of a repeat)."""
        repeated = set(self.repeat.fields) if self.repeat else set()
        return tuple(s for s in (*self.required, *self.optional) if s not in repeated)

    @property
    def all_fields(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.required, *self.optional)))

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "geometry": dict(self.geometry),
            "required": list(self.required),
            "optional": list(self.optional),
            "repeat": self.repeat.to_json() if self.repeat else None,
            "notes": self.notes,
        }


@dataclass
class Registry:
    """A mutable block registry. ``DEFAULT`` is the one the pipeline uses."""

    blocks: dict[str, Block] = field(default_factory=dict)
    skeletons: dict[str, list[str]] = field(default_factory=dict)

    # -- blocks ------------------------------------------------------------
    def register(
        self,
        block_id: str,
        *,
        geometry: dict,
        required: Iterable[str] = (),
        optional: Iterable[str] = (),
        repeat: RepeatRule | None = None,
        notes: str = "",
        replace: bool = False,
    ) -> Block:
        if not KEBAB_RE.match(block_id):
            raise RegistryError(f"block id {block_id!r} is not kebab-case")
        if not geometry or "band" not in geometry:
            raise RegistryError(f"block {block_id!r}: geometry needs at least a 'band'")
        if block_id in self.blocks and not replace:
            raise RegistryError(f"block {block_id!r} is already registered")
        required = tuple(dict.fromkeys(required))
        optional = tuple(dict.fromkeys(optional))
        overlap = set(required) & set(optional)
        if overlap:
            raise RegistryError(f"block {block_id!r}: {sorted(overlap)} both required and optional")
        if repeat:
            declared = set(required) | set(optional)
            missing = [f for f in repeat.fields if f not in declared]
            if missing:
                raise RegistryError(
                    f"block {block_id!r}: repeat fields {missing} are not declared as slots"
                )
        block = Block(block_id, dict(geometry), required, optional, repeat, notes)
        self.blocks[block_id] = block
        return block

    def resolve(self, block_id: str) -> Block:
        try:
            return self.blocks[block_id]
        except KeyError:
            raise UnknownBlockError(
                f"unknown block {block_id!r}; known: {', '.join(self.known())}"
            ) from None

    def known(self) -> list[str]:
        return sorted(self.blocks)

    def __contains__(self, block_id: object) -> bool:
        return block_id in self.blocks

    # -- skeletons ---------------------------------------------------------
    def register_skeleton(self, skeleton_id: str, block_ids: Iterable[str]) -> list[str]:
        """Declare a skeleton and the blocks it is allowed to use."""
        ids = list(block_ids)
        for block_id in ids:
            self.resolve(block_id)
        self.skeletons[skeleton_id] = ids
        return ids

    def is_known_skeleton(self, skeleton_id: str) -> bool:
        return skeleton_id in self.skeletons

    def skeleton_blocks(self, skeleton_id: str) -> list[str]:
        if skeleton_id not in self.skeletons:
            raise UnknownBlockError(f"unknown skeleton {skeleton_id!r}")
        return list(self.skeletons[skeleton_id])

    def bind(
        self,
        skeleton_id: str,
        block_id: str,
        *,
        skeleton_is_new: bool = False,
        definition: dict | None = None,
    ) -> Block:
        """Bind ``block_id`` into ``skeleton_id``.

        * known block + known skeleton   -> returns the block, binding recorded
        * known block + new skeleton     -> binds (a new skeleton may reuse blocks)
        * unknown block + new skeleton + definition -> registers, then binds
        * unknown block + known skeleton -> ``UnknownBlockError``
        """
        known_skeleton = self.is_known_skeleton(skeleton_id)
        if skeleton_is_new and known_skeleton:
            raise RegistryError(
                f"skeleton {skeleton_id!r} is already registered; "
                "a new skeleton cannot claim an existing id"
            )

        if block_id in self.blocks:
            if definition:
                raise RegistryError(
                    f"block {block_id!r} already exists; a definition may only be "
                    "supplied for a genuinely new block"
                )
            block = self.blocks[block_id]
        else:
            if known_skeleton and not skeleton_is_new:
                raise UnknownBlockError(
                    f"skeleton {skeleton_id!r} is frozen: it cannot reference the "
                    f"undefined block {block_id!r}. Define the block first, or bind it "
                    "from a new skeleton."
                )
            if not definition:
                raise UnknownBlockError(
                    f"unknown block {block_id!r} on a new skeleton needs a definition "
                    "(geometry/required/optional/repeat) to be registered"
                )
            block = self.register(
                block_id,
                geometry=definition["geometry"],
                required=definition.get("required", ()),
                optional=definition.get("optional", ()),
                repeat=RepeatRule(**definition["repeat"]) if definition.get("repeat") else None,
                notes=definition.get("notes", ""),
            )

        if not self.is_known_skeleton(skeleton_id):
            if not skeleton_is_new:
                raise RegistryError(
                    f"skeleton {skeleton_id!r} is not registered; pass "
                    "skeleton_is_new=True to create it"
                )
            self.skeletons[skeleton_id] = []
        if block_id not in self.skeletons[skeleton_id]:
            self.skeletons[skeleton_id].append(block_id)
        return block

    def reset(self) -> None:
        self.blocks.clear()
        self.skeletons.clear()


# --------------------------------------------------------------------------
# Seed: the blocks the four skeletons in this repository actually use.
# --------------------------------------------------------------------------
SEED_BLOCKS: tuple[dict, ...] = (
    {
        "id": "nav-bar",
        "geometry": {"band": "contained", "columns": 2, "align": "space-between",
                     "media": "none", "role": "chrome"},
        "required": ("brand",),
        "optional": ("nav-item", "cta"),
        "repeat": {"name": "nav-item", "fields": ("nav-item",), "min": 3, "max": 6, "default": 4},
        "notes": "Site chrome. Never carries the page's primary heading.",
    },
    {
        "id": "hero-center",
        "geometry": {"band": "contained", "columns": 1, "align": "center",
                     "media": "none", "max_width": "760px", "role": "hero"},
        "required": ("h1", "lead"),
        "optional": ("eyebrow", "cta", "cta-secondary", "meta"),
        "repeat": None,
        "notes": "Centred hero. One headline, one promise, one action.",
    },
    {
        "id": "hero-split",
        "geometry": {"band": "contained", "columns": 2, "align": "start",
                     "media": "panel", "role": "hero"},
        "required": ("h1", "lead", "cta"),
        "optional": ("eyebrow", "cta-secondary", "meta"),
        "repeat": None,
        "notes": "Text left, CSS-drawn panel right. No image assets, ever.",
    },
    {
        "id": "logo-strip",
        "geometry": {"band": "contained", "columns": "flow", "align": "start",
                     "media": "none", "role": "proof"},
        "required": ("eyebrow", "nav-item"),
        "optional": ("meta",),
        "repeat": {"name": "nav-item", "fields": ("nav-item",), "min": 3, "max": 6, "default": 5},
        "notes": "Row of short proofs: customers, certifications, press.",
    },
    {
        "id": "feature-grid-3",
        "geometry": {"band": "contained", "columns": 3, "align": "start",
                     "media": "none", "role": "features"},
        "required": ("h2", "item-title", "item-body"),
        "optional": ("eyebrow",),
        "repeat": {"name": "feature", "fields": ("item-title", "item-body"),
                   "min": 3, "max": 6, "default": 3},
        "notes": "Three-up feature grid; the repeat rule tolerates up to six.",
    },
    {
        "id": "stat-band",
        "geometry": {"band": "contained", "columns": 3, "align": "center",
                     "media": "none", "role": "proof"},
        "required": ("item-value",),
        "optional": ("h2", "item-label", "meta"),
        "repeat": {"name": "stat", "fields": ("item-value", "item-label"),
                   "min": 2, "max": 4, "default": 3},
        "notes": "Numbers with optional labels. Values are strings, not numbers: "
                 "'92%' and '11,400' are both valid.",
    },
    {
        "id": "checklist-band",
        "geometry": {"band": "contained", "columns": 2, "align": "start",
                     "media": "none", "role": "features"},
        "required": ("h2", "item-label"),
        "optional": ("eyebrow", "item-body", "meta"),
        "repeat": {"name": "check", "fields": ("item-label", "item-body"),
                   "min": 3, "max": 8, "default": 6},
        "notes": "Two-column list of short labels with optional explanations.",
    },
    {
        "id": "split-media",
        "geometry": {"band": "contained", "columns": 2, "align": "start",
                     "media": "panel", "role": "explain"},
        "required": ("h2", "body"),
        "optional": ("eyebrow", "cta", "meta"),
        "repeat": None,
        "notes": "Prose beside a CSS-drawn panel; the panel is never an asset.",
    },
    {
        "id": "longform-section",
        "geometry": {"band": "contained", "columns": 1, "align": "start",
                     "media": "none", "max_width": "720px", "role": "prose"},
        "required": ("h2", "body"),
        "optional": ("eyebrow", "meta"),
        "repeat": {"name": "paragraph", "fields": ("body",),
                   "min": 1, "max": 4, "default": 3},
        "notes": "Long-form prose block for regulated / EU style pages.",
    },
    {
        "id": "pricing-tiers",
        "geometry": {"band": "contained", "columns": 3, "align": "stretch",
                     "media": "none", "role": "commercial"},
        "required": ("h2", "item-name", "item-price", "item-cta"),
        "optional": ("eyebrow", "item-body", "item-meta"),
        "repeat": {"name": "tier", "fields": ("item-name", "item-price", "item-body",
                                             "item-cta", "item-meta"),
                   "min": 2, "max": 4, "default": 3},
        "notes": "Price cards. The price is a copy slot, never a computed value.",
    },
    {
        "id": "key-facts-table",
        "geometry": {"band": "contained", "columns": 2, "align": "start",
                     "media": "none", "role": "facts"},
        "required": ("h2", "item-label", "item-value"),
        "optional": ("eyebrow", "meta"),
        "repeat": {"name": "fact", "fields": ("item-label", "item-value"),
                   "min": 3, "max": 8, "default": 5},
        "notes": "Definitions table: the EU 'key information' pattern.",
    },
    {
        "id": "testimonial-single",
        "geometry": {"band": "contained", "columns": 1, "align": "center",
                     "media": "none", "max_width": "720px", "role": "proof"},
        "required": ("quote",),
        "optional": ("attribution", "meta"),
        "repeat": None,
        "notes": "One quoted sentence. No star ratings, no fake faces.",
    },
    {
        "id": "faq-list",
        "geometry": {"band": "contained", "columns": 1, "align": "start",
                     "media": "none", "max_width": "820px", "role": "support"},
        "required": ("h2", "item-q", "item-a"),
        "optional": ("eyebrow", "meta"),
        "repeat": {"name": "entry", "fields": ("item-q", "item-a"),
                   "min": 3, "max": 8, "default": 4},
        "notes": "Question/answer pairs rendered as static prose (no JS).",
    },
    {
        "id": "cta-banner",
        "geometry": {"band": "full-bleed", "columns": 1, "align": "center",
                     "media": "none", "role": "close"},
        "required": ("h2", "cta"),
        "optional": ("lead", "meta"),
        "repeat": None,
        "notes": "Closing band, full-bleed with its own surface colour.",
    },
    {
        "id": "footer-legal",
        "geometry": {"band": "full-bleed", "columns": 2, "align": "start",
                     "media": "none", "role": "chrome"},
        "required": ("footer",),
        "optional": ("meta", "nav-item"),
        "repeat": {"name": "nav-item", "fields": ("nav-item",), "min": 3, "max": 6, "default": 3},
        "notes": "Legal footer. Carries the brand line and the fine print.",
    },
)

SEED_SKELETONS: dict[str, tuple[str, ...]] = {
    "01-host-landing": (
        "nav-bar",
        "hero-center",
        "logo-strip",
        "feature-grid-3",
        "stat-band",
        "cta-banner",
        "footer-legal",
    ),
    "02-saas-marketing": (
        "nav-bar",
        "hero-split",
        "split-media",
        "pricing-tiers",
        "testimonial-single",
        "faq-list",
        "cta-banner",
        "footer-legal",
    ),
    "03-product-security": (
        "nav-bar",
        "hero-center",
        "stat-band",
        "feature-grid-3",
        "checklist-band",
        "faq-list",
        "cta-banner",
        "footer-legal",
    ),
    "04-insurance-longform": (
        "nav-bar",
        "hero-split",
        "longform-section",
        "key-facts-table",
        "faq-list",
        "cta-banner",
        "footer-legal",
    ),
}


def build_default_registry() -> Registry:
    """A fresh registry seeded with this repository's blocks and skeletons."""
    registry = Registry()
    for definition in SEED_BLOCKS:
        registry.register(
            definition["id"],
            geometry=definition["geometry"],
            required=definition["required"],
            optional=definition["optional"],
            repeat=RepeatRule(**definition["repeat"]) if definition["repeat"] else None,
            notes=definition.get("notes", ""),
        )
    for skeleton_id, block_ids in SEED_SKELETONS.items():
        registry.register_skeleton(skeleton_id, block_ids)
    return registry


#: The registry the pipeline uses.
DEFAULT = build_default_registry()


# --- module level convenience API -----------------------------------------
def register(block_id: str, **kwargs) -> Block:
    return DEFAULT.register(block_id, **kwargs)


def resolve(block_id: str) -> Block:
    return DEFAULT.resolve(block_id)


def bind(skeleton_id: str, block_id: str, **kwargs) -> Block:
    return DEFAULT.bind(skeleton_id, block_id, **kwargs)


def known_blocks() -> list[str]:
    return DEFAULT.known()


def main(argv: list[str] | None = None) -> int:
    """``python -m brandkit.blocks`` prints the registry as JSON or a table."""
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Inspect the block registry.")
    ap.add_argument("--json", action="store_true", help="dump the registry as JSON")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(
            {
                "blocks": [b.to_json() for b in (DEFAULT.resolve(i) for i in DEFAULT.known())],
                "skeletons": dict(sorted(DEFAULT.skeletons.items())),
            },
            indent=2,
            sort_keys=True,
        ))
        return 0

    print(f"{len(DEFAULT.blocks)} blocks, {len(DEFAULT.skeletons)} skeletons\n")
    head = f"{'id':20} {'band':11} {'cols':>4}  {'repeat rule':28} required slots"
    print(head)
    print("-" * len(head))
    for block_id in DEFAULT.known():
        block = DEFAULT.resolve(block_id)
        repeat = "-"
        if block.repeat:
            r = block.repeat
            repeat = f"{r.name} x{r.min}..{r.max} (default {r.default})"
        print(
            f"{block.id:20} {block.geometry['band']:11} "
            f"{str(block.geometry.get('columns', '-')):>4}  {repeat:28} "
            f"{', '.join(block.required)}"
        )
    print()
    for skeleton_id, block_ids in sorted(DEFAULT.skeletons.items()):
        print(f"{skeleton_id}: {', '.join(block_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
