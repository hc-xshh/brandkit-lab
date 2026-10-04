# Example brand sources

Three self-contained HTML pages that stand in for "a brand source URL". All three
were **authored for this repository**: the brands are fictional, the copy is
original, and there are no third-party assets, fonts, trackers or network
requests anywhere in them.

| File | Source id | What it exercises |
|---|---|---|
| `northwind-outfitters.html` | `northwind-outfitters` | Warm outdoor brand: serif headings, deep pine + clay, two declared shadows, pill radius. |
| `pulse-analytics.html` | `pulse-analytics` | B2B SaaS: cool indigo + cyan accent, 10/16/24px radius scale, one declared shadow (the raised elevation has to be derived). |
| `slate-assurance.html` | `slate-assurance` | The awkward case. **Entirely greyscale with one accent colour** (`#ffd400`) declared as a text colour on white — 1.28:1 against the paper. A naive pipeline ships unreadable links; `assemble_kit` has to catch it. |

## Measuring one

```bash
python3 -m brandkit.measure --source sources/northwind-outfitters.html \
    --out out/metrics/northwind-outfitters.json
```

## Pointing it at a real brand URL

```bash
python3 -m brandkit.measure --source-url https://example.com \
    --out out/metrics/example.json --save-html sources/fetched/example.html
```

`--source-url` performs exactly one GET with a plain `brandkit-lab/1.0` user
agent. There is no crawling, no retry loop and no rendering of JavaScript, so
treat it as a way to measure a page you are allowed to measure — not as a
scraper.
