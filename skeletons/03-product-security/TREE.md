# Tree — `03-product-security`

A neutral security-product page: centred hero, four headline numbers, a
three-up feature grid, a two-column control checklist and an FAQ.
**Band order, band count and repeat counts are frozen.**

| # | band | block | geometry | repeat |
|---|------|-------|----------|--------|
| 1 | `nav` | `nav-bar` | contained, 2 columns, space-between | `nav-item` x4 (3..6) |
| 2 | `hero` | `hero-center` | contained, 1 column, centred | — |
| 3 | `numbers` | `stat-band` | contained, 4 columns, centre | `stat` x4 (2..4) |
| 4 | `features` | `feature-grid-3` | contained, 3 columns, start | `feature` x3 (3..6) |
| 5 | `controls` | `checklist-band` | contained, 2 columns, start | `check` x6 (3..8) |
| 6 | `support` | `faq-list` | contained, 1 column, start | `entry` x3 (3..8) |
| 7 | `close` | `cta-banner` | full-bleed, 1 column, centre | — |
| 8 | `footer` | `footer-legal` | full-bleed, 2 columns, start | `nav-item` x3 (3..6) |

## Copy slots

| band | required | optional | repeated |
|------|----------|----------|----------|
| `nav-bar` | `brand` | `cta` | `nav-item[0..3]` |
| `hero-center` | `h1`, `lead` | `eyebrow`, `cta`, `cta-secondary`, `meta` | — |
| `stat-band` | `item-value` | `h2`, `item-label`, `meta` | `item-value[0..3]`, `item-label[0..3]` |
| `feature-grid-3` | `h2`, `item-title`, `item-body` | `eyebrow` | `item-title[0..2]`, `item-body[0..2]` |
| `checklist-band` | `h2`, `item-label` | `eyebrow`, `item-body`, `meta` | `item-label[0..5]`, `item-body[0..5]` |
| `faq-list` | `h2`, `item-q`, `item-a` | `eyebrow`, `meta` | `item-q[0..2]`, `item-a[0..2]` |
| `cta-banner` | `h2`, `cta` | `lead`, `meta` | — |
| `footer-legal` | `footer` | `meta` | `nav-item[0..2]` |

## Notes for the binder

* This skeleton has no `h2` on the `stat-band` band: the four numbers stand on
  their own. The slot is optional, and an unfilled optional slot keeps the
  skeleton's own markup untouched.
* `checklist-band` is the widest repeat in the repository (six entries). Its
  repeat rule tolerates up to eight, so a kit may supply more copy than the page
  has room for and the extra strings are simply not bound.
* `stat-band` here uses four entries while `01-host-landing` uses three: the
  repeat rule is a range, and the skeleton's own markup decides the count.
