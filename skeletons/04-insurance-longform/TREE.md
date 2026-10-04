# Tree — `04-insurance-longform`

A neutral long-form / regulated page: split hero with a fact panel, a prose
section, a key-facts table and an FAQ. This is the skeleton designed to look
boring, because boring is the requirement. **Band order, band count and repeat
counts are frozen.**

| # | band | block | geometry | repeat |
|---|------|-------|----------|--------|
| 1 | `nav` | `nav-bar` | contained, 2 columns, space-between | `nav-item` x4 (3..6) |
| 2 | `hero` | `hero-split` | contained, 2 columns, start, panel media | — |
| 3 | `conditions` | `longform-section` | contained, 1 column, start, 720px measure | `paragraph` x3 (1..4) |
| 4 | `facts` | `key-facts-table` | contained, 2 columns, start | `fact` x5 (3..8) |
| 5 | `support` | `faq-list` | contained, 1 column, start | `entry` x4 (3..8) |
| 6 | `close` | `cta-banner` | full-bleed, 1 column, centre | — |
| 7 | `footer` | `footer-legal` | full-bleed, 2 columns, start | `nav-item` x3 (3..6) |

## Copy slots

| band | required | optional | repeated |
|------|----------|----------|----------|
| `nav-bar` | `brand` | `cta` | `nav-item[0..3]` |
| `hero-split` | `h1`, `lead`, `cta` | `eyebrow`, `cta-secondary`, `meta` | — |
| `longform-section` | `h2`, `body` | `eyebrow`, `meta` | `body[0..2]` |
| `key-facts-table` | `h2`, `item-label`, `item-value` | `eyebrow`, `meta` | `item-label[0..4]`, `item-value[0..4]` |
| `faq-list` | `h2`, `item-q`, `item-a` | `eyebrow`, `meta` | `item-q[0..3]`, `item-a[0..3]` |
| `cta-banner` | `h2`, `cta` | `lead`, `meta` | — |
| `footer-legal` | `footer` | `meta` | `nav-item[0..2]` |

## Notes for the binder

* `longform-section` wraps its repeated paragraphs in a plain `div` carrying
  `data-repeat`; the heading and the meta line sit outside it, so they do not
  count as repeats.
* `key-facts-table` puts `data-repeat` on the `<tbody>`: the repeated unit is a
  row, and moving rows around is exactly what `apply.py` is forbidden to do.
* The 30-day cooling-off sentence and the tax treatment are on the page twice —
  once in prose, once in the fact table. They are separate copy slots, so a kit
  may keep them consistent or deliberately rank them differently. Nothing in
  the pipeline de-duplicates copy for you.
