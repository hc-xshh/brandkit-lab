"""The frozen token contract.

Every kit produced by :mod:`brandkit.assemble_kit` publishes exactly these CSS
custom properties.  The contract is code, not documentation, so that the kit
builder, the evaluation harness and the test-suite all agree on the same list.

Token provenance is always one of:

``measured``
    copied from a fact found in the source page (a hex, a font stack, a radius,
    a shadow) by :mod:`brandkit.measure`.
``derived``
    computed by the kit builder because the source did not declare it (for
    example a muted ink or a raised elevation when only one shadow exists).

Nothing else may write a token: the LLM seam is copy-only, see
:mod:`brandkit.drafter`.
"""

from __future__ import annotations

COLOR_TOKENS: tuple[str, ...] = (
    "paper",
    "paper-alt",
    "ink",
    "ink-muted",
    "primary",
    "primary-ink",
    "border",
    "accent",
)

FONT_TOKENS: tuple[str, ...] = ("heading-font", "body-font")

RADIUS_TOKENS: tuple[str, ...] = ("cta", "card", "pill")

SHADOW_TOKENS: tuple[str, ...] = ("card", "raised")

GROUPS: dict[str, tuple[str, ...]] = {
    "color": COLOR_TOKENS,
    "font": FONT_TOKENS,
    "radius": RADIUS_TOKENS,
    "shadow": SHADOW_TOKENS,
}

#: CSS custom property prefix, e.g. ``--radius-cta``.
PREFIX: dict[str, str] = {
    "color": "",
    "font": "",
    "radius": "radius-",
    "shadow": "shadow-",
}


def css_var(group: str, token: str) -> str:
    """Return the CSS custom property name for ``group``/``token``."""
    return "--" + PREFIX[group] + token


def all_tokens() -> list[tuple[str, str]]:
    """Flat ``(group, token)`` list in contract order."""
    return [(group, token) for group, tokens in GROUPS.items() for token in tokens]


def all_vars() -> list[str]:
    """Flat list of every CSS custom property the contract requires."""
    return [css_var(group, token) for group, token in all_tokens()]


#: Text/background pairs that must satisfy WCAG AA body contrast (>= 4.5).
#: `assemble_kit` refuses to write a kit where one of these fails. Every text
#: token is checked against *both* surfaces the skeletons paint text on: an
#: inverted or tinted band is still a band with words in it.
BODY_CONTRAST_PAIRS: tuple[tuple[str, str], ...] = (
    ("ink", "paper"),
    ("ink", "paper-alt"),
    ("ink-muted", "paper"),
    ("ink-muted", "paper-alt"),
    ("primary", "paper"),
    ("primary", "paper-alt"),
    ("primary-ink", "primary"),
)

#: Which surfaces each text token is checked against, and in which order.
#: `assemble_kit` repairs a token against the worse of its surfaces.
TEXT_ON_SURFACES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ink", ("paper", "paper-alt")),
    ("ink-muted", ("paper", "paper-alt")),
    ("primary", ("paper", "paper-alt")),
)

#: Non-text pairs. A hairline rule and a decorative accent are measured and
#: reported, but deliberately not enforced: forcing a brand's yellow to reach
#: 4.5:1 on white would destroy the colour the brand actually uses. Text sits on
#: `--ink`, `--primary` or `--primary-ink`, never on these.
DECORATIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("accent", "paper"),
    ("border", "paper"),
)

#: Non-text floor used when reporting decorative pairs (WCAG AA, large/UI).
AA_LARGE = 3.0


def report_pairs() -> tuple[tuple[str, str], ...]:
    """Every pair a kit reports, enforced or not."""
    return (*BODY_CONTRAST_PAIRS, *DECORATIVE_PAIRS)


def enforced_pairs() -> tuple[tuple[str, str], ...]:
    """The pairs that can block a kit from being written."""
    return BODY_CONTRAST_PAIRS
