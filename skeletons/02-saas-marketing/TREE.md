# Tree — `02-saas-marketing`

A neutral SaaS marketing page: split hero with a CSS panel, a price table, one
testimonial and an FAQ. **Band order, band count and repeat counts are frozen.**

| # | band | block | geometry | repeat |
|---|------|-------|----------|--------|
| 1 | `nav` | `nav-bar` | contained, 2 columns, space-between | `nav-item` x4 (3..6) |
| 2 | `hero` | `hero-split` | contained, 2 columns, start, panel media | — |
| 3 | `explain` | `split-media` | contained, 2 columns, start, panel media | — |
| 4 | `commercial` | `pricing-tiers` | contained, 3 columns, stretch | `tier` x3 (2..4) |
| 5 | `proof` | `testimonial-single` | contained, 1 column, centre, 720px measure | — |
| 6 | `support` | `faq-list` | contained, 1 column, start, 820px measure | `entry` x4 (3..8) |
| 7 | `close` | `cta-banner` | full-bleed, 1 column, centre | — |
| 8 | `footer` | `footer-legal` | full-bleed, 2 columns, start | `nav-item` x3 (3..6) |

## Copy slots

| band | required | optional | repeated |
|------|----------|----------|----------|
| `nav-bar` | `brand` | `cta` | `nav-item[0..3]` |
| `hero-split` | `h1`, `lead`, `cta` | `eyebrow`, `cta-secondary`, `meta` | — |
| `split-media` | `h2`, `body` | `eyebrow`, `cta`, `meta` | — |
| `pricing-tiers` | `h2`, `item-name`, `item-price`, `item-cta` | `eyebrow`, `item-body`, `item-meta` | `item-name[0..2]`, `item-price[0..2]`, `item-body[0..2]`, `item-cta[0..2]`, `item-meta[0..2]` |
| `testimonial-single` | `quote` | `attribution`, `meta` | — |
| `faq-list` | `h2`, `item-q`, `item-a` | `eyebrow`, `meta` | `item-q[0..3]`, `item-a[0..3]` |
| `cta-banner` | `h2`, `cta` | `lead`, `meta` | — |
| `footer-legal` | `footer` | `meta` | `nav-item[0..2]` |

## Notes for the binder

* `hero-split` and `split-media` reserve a `media` column that is drawn in CSS.
  A kit restyles the panel's surface, border, radius and shadow — it never
  inserts an image, so there is no asset to move.
* Prices are copy, not numbers. The kit carries the strings a designer wrote;
  nothing in the pipeline parses or reformats currency.
* The FAQ is static prose. There is no accordion, so no copy slot depends on
  JavaScript having run.
