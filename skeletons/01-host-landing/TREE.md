# Tree — `01-host-landing`

A neutral landing page for a hosting/product business. The tree below is the
whole contract: **band order, band count and repeat counts are frozen**, and
`brandkit/apply.py` refuses to bind a kit if any of them change.

Dom order = band order. Every band carries `data-band` (its place in the page)
and `data-block` (its registered block id).

| # | band | block | geometry | repeat |
|---|------|-------|----------|--------|
| 1 | `nav` | `nav-bar` | contained, 2 columns, space-between | `nav-item` x4 (3..6) |
| 2 | `hero` | `hero-center` | contained, 1 column, centred, 760px measure | — |
| 3 | `proof` | `logo-strip` | contained, flow, start | `nav-item` x5 (3..6) |
| 4 | `features` | `feature-grid-3` | contained, 3 columns, start | `feature` x3 (3..6) |
| 5 | `numbers` | `stat-band` | contained, 3 columns, centre | `stat` x3 (2..4) |
| 6 | `close` | `cta-banner` | full-bleed, 1 column, centre | — |
| 7 | `footer` | `footer-legal` | full-bleed, 2 columns, start | `nav-item` x3 (3..6) |

## Copy slots

`data-slot="<block>.<field>"` for single values, `data-slot="<block>.<field>[i]"`
for the i-th repeat of a repeated field. Required vs optional is declared in
`brandkit/blocks.py`; the table below is the same information at page level.

| band | required | optional | repeated |
|------|----------|----------|----------|
| `nav-bar` | `brand` | `cta` | `nav-item[0..3]` |
| `hero-center` | `h1`, `lead` | `eyebrow`, `cta`, `cta-secondary`, `meta` | — |
| `logo-strip` | `eyebrow`, `nav-item` | `meta` | `nav-item[0..4]` |
| `feature-grid-3` | `h2`, `item-title`, `item-body` | `eyebrow` | `item-title[0..2]`, `item-body[0..2]` |
| `stat-band` | `item-value` | `h2`, `item-label`, `meta` | `item-value[0..2]`, `item-label[0..2]` |
| `cta-banner` | `h2`, `cta` | `lead`, `meta` | — |
| `footer-legal` | `footer` | `meta` | `nav-item[0..2]` |

## What a restyle may change

* the `:root` block between `brandkit:tokens:start` and `brandkit:tokens:end`
* the text inside elements that carry `data-slot`

Nothing else. `apply.py` writes a `proof.json` next to every restyled page with
the structural signature before and after; the two must be byte-identical.

## Asset policy

No images, no webfonts, no CDN, no `<script>`. Panels are drawn with CSS
gradients and borders so the page renders identically offline, in CI, and in a
headless screenshot.
