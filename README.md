# brandkit-lab

**A brand source page in. A frozen design kit out. The layout does not move.**

`brandkit-lab` measures the design facts a brand page actually declares, freezes them into one
kit, renders `DESIGN.md` from that same kit, and then binds the kit onto neutral landing skeletons
— restyling the theme and the copy while proving, mechanically, that not a single band, wrapper or
repeat count moved.

No dependencies. `python3` and a browser for screenshots; nothing else.
204 tests, an eval harness that fails on regression, CI on Python 3.10/3.11/3.12, and the gallery
below is generated, not hand-maintained.

```
source.html ──▶ measure ──▶ metrics.json ──▶ draft (LLM seam) ──▶ assemble_kit ──▶ kit.json
                                                                            │        kit.css
                                                                            │        tokens.csv
                                                                            │        DESIGN.md
                                                                            ▼
                                     skeleton + kit ──▶ apply ──▶ restyled.html + proof.json
```

| | |
|---|---|
| **Gallery (live)** | https://hc-xshh.github.io/brandkit-lab/ |
| **Kit hashes** | one kit per brand, identical on all four skeletons (`22154ef0e7146259`, `d24e19983a058d99`, `8813880cf89bb8b1`) |
| **License** | MIT — every example page in this repository is fictional and written for it |

---

## What is real, and what is a seam

I would rather label this myself than have a reader find it later.

| Component | Status |
|---|---|
| `measure.py` (source → `metrics.json`) | **Real.** Parses the page's own `<style>` blocks and inline `style=` attributes with the stdlib only: colour frequencies, the font families actually referenced, the radius scale, elevation declarations, the spacing list, and copy-slot candidates classified by tag/class. Heuristic, and it says so: it reads *declared* CSS, so it cannot see a page whose palette only exists at runtime. |
| `drafter.py` (default) | **Real, offline, deterministic.** A rule-based drafter that reuses the source's *own* measured sentences. It does not invent copy — which is why nav labels are left to the layout (see Limitations). |
| `drafter.py --drafter openai:<model>` | **A seam.** A real `urllib` call to any OpenAI-compatible endpoint, `temperature=0`, validated output. **Inert unless explicitly requested**, refuses to run without a key, and is deliberately not exercised in CI. Not verified end to end by this repository's automated checks. |
| `blocks.py` (registry) | **Real.** 15 blocks, each with id, geometry, required slots, optional slots and a repeat rule; skeletons may only use registered blocks, and the registry refuses a malformed block or an unknown id. |
| `assemble_kit.py` (single writer) | **Real.** The only code that writes a token, and the only place a kit can be refused. Nothing ships that fails the contract or the WCAG AA gate. |
| `apply.py` (single binder) | **Real.** Rewrites only the `:root` token block and the `data-slot` text, and returns a proof: the band list, per-band repeat counts and the element count, byte-identical before and after. |
| `scripts/eval_report.py` | **Real.** The numbers below come from it, and it exits non-zero when a threshold regresses. |
| `docs/index.html` + `docs/img/*.png` | **Real.** Rendered by headless Chrome against the local `file://` pages; the gallery HTML is generated from `docs/eval.json`. |

---

## Measured results

`make eval` — 3 sources × 4 skeletons = 12 kits, every kit built twice and restyled onto a real
copy of the skeleton. This is the tail of the actual run on Python 3.11:

```
source                 skeleton                   tok   req  slot    AA    min  tree  det guard             hash
----------------------------------------------------------------------------------------------------------------
northwind-outfitters   01-host-landing           1.00  1.00  0.84  1.00   5.19   yes  yes     0 a4d53894783bdbe3
northwind-outfitters   02-saas-marketing         1.00  1.00  0.88  1.00   5.19   yes  yes     0 6c577c388b752d32
northwind-outfitters   03-product-security       1.00  1.00  0.89  1.00   5.19   yes  yes     0 988d3f87c17da547
northwind-outfitters   04-insurance-longform     1.00  1.00  0.86  1.00   5.19   yes  yes     0 76285c1b141fde68
pulse-analytics        01-host-landing           1.00  1.00  0.84  1.00   5.75   yes  yes     0 da539de7a31355a2
pulse-analytics        02-saas-marketing         1.00  1.00  0.88  1.00   5.75   yes  yes     0 df9908cd1463a443
pulse-analytics        03-product-security       1.00  1.00  0.89  1.00   5.75   yes  yes     0 95075f01f07db3b8
pulse-analytics        04-insurance-longform     1.00  1.00  0.86  1.00   5.75   yes  yes     0 ed06b97b255383f6
slate-assurance        01-host-landing           1.00  1.00  0.84  1.00   4.71   yes  yes     2 a2b54807daec725e
slate-assurance        02-saas-marketing         1.00  1.00  0.88  1.00   4.71   yes  yes     2 1e6538956255b65c
slate-assurance        03-product-security       1.00  1.00  0.89  1.00   4.71   yes  yes     2 52ab138e6865a20c
slate-assurance        04-insurance-longform     1.00  1.00  0.86  1.00   4.71   yes  yes     2 2eb3778a778ed8df

kits evaluated            12 (3 sources x 4 skeletons)
token coverage            1.0000  (floor 1.0)
required slot coverage    1.0000  (floor 1.0)
slot coverage (all)       0.8670
WCAG AA enforced pairs    1.0000  (floor 1.0), worst 4.71:1
tree unchanged rate       1.0000  (floor 1.0)
determinism rate          1.0000  (floor 1.0)
measured token ratio      0.8889  (floor 0.6)
one kit per source        True
guardrails fired          8
bands checked             90 across 1362 elements
```

What each column means: `tok` = fraction of the frozen token contract that the kit fills, `req` =
required copy slots filled, `slot` = all slots filled, `AA` = fraction of enforced contrast pairs
clearing 4.5:1, `min` = the worst ratio in that kit, `tree` = the tree-unchanged proof, `det` = the
kit is byte-identical when built twice, `guard` = how many contrast guardrails fired, `hash` =
fingerprint of `kit.json` + `kit.css`.

Reading it: **12/12 kits rebuilt their tree byte-identically, 12/12 were deterministic, every
enforced contrast pair cleared WCAG AA, and 88.9% of token values came straight off the source
page** — the rest were derived siblings (a second surface, a raised elevation, a repaired
contrast).

`pytest` — `204 passed in 9.89s`.

---

## The two-model invariant

The client-side ask this repository is built around: *two different models must produce the same
kit.* Here is the honest version of that claim, and it is a test, not a paragraph.

`tests/test_two_models.py` drafts the same source/skeleton pair through two different drafters
(`classic-v1` and `alt-v1`, which walk the copy pools in opposite directions) and asserts:

* every **measured** colour, font, radius and shadow is identical in both kits — the models cannot
  touch a fact;
* `kit.css` is byte-identical between the two kits, because a token block does not contain copy;
* the two kits differ **only** in `copy`, and differ there for real (`assert a != b`, so the test
  cannot pass by both models being trivially broken);
* both kits satisfy the same contract, the same contrast gate and the same tree-unchanged proof.

That last point is the point. The model writes words; `assemble_kit()` writes tokens. The
separation is enforced by the type of the input, not by asking the model nicely.

---

## The awkward brand

`slate-assurance` exists to break a naive pipeline: greyscale, with a single bright accent, and it
declares that accent as a *text* colour on white. Copying the brand colour into the link colour
ships unreadable text. With the guardrail:

| token | measured | as shipped | why |
|---|---|---|---|
| `--accent` | `#ffd400` | `#ffd400` | kept exactly — it is used for bars, rules and chips, never for text |
| `--primary` | `#ffd400` (1.43:1 on paper, 1.28:1 on the alternate surface) | `#806a00` (4.71:1 worst case) | text and buttons need to be readable |
| `--ink-muted` | `#767676` (4.06:1 on the alternate surface) | `#6a6a6a` (4.83:1 worst case) | secondary text is still text |

The kit does not throw the brand's colour away — it demotes it to where colour is decoration. If an
enforced pair *cannot* be repaired, `assemble_kit()` raises instead of writing a file:
`tests/test_contrast_guardrail.py::test_an_unsatisfiable_palette_is_refused_not_shipped` proves it
with a mid-grey palette that fails in both directions.

---

## Four skeletons, three brands

Each skeleton is a neutral page authored for this repository, with its own neutral theme, its own
copy and no external assets — system font stacks only, so the pages render offline and in CI.

| Skeleton | Bands | Shape |
|---|---|---|
| `01-host-landing` | 7 | nav, centred hero, proof strip, 3-up feature grid, stats, closing CTA, footer |
| `02-saas-marketing` | 8 | nav, split hero + panel, prose, 3 pricing tiers, quote, FAQ, closing CTA, footer |
| `03-product-security` | 8 | nav, centred hero, 4 stats, 3 pillars, 6-item check list, FAQ, closing CTA, footer |
| `04-insurance-longform` | 7 | nav, split hero, 3 prose sections, key-facts table, FAQ, closing CTA, footer (EU long-form) |

`TREE.md` in each skeleton directory is the frozen band order, the repeat counts and the slot list.
`brandkit.skeletons` fails if the markup and the document disagree.

The three brands are `northwind-outfitters` (warm, serif headings), `pulse-analytics` (cool, dark
UI) and `slate-assurance` (the awkward one). They are fictional pages written for this repo, which
is what makes the whole thing license-clean and runnable offline.

---

## Reproduce it

```bash
make help                  # what exists
make lint                  # offline lint: no third-party imports, no remote assets, no secrets
make test                  # 204 tests (pytest is the only test-only dependency)
make eval                  # the table above; writes docs/eval.json, exits 1 on regression
make gallery               # re-render pages in headless Chrome + rebuild docs/index.html
```

One brand, by hand:

```bash
python3 -m brandkit.measure --source sources/slate-assurance.html --out out/metrics/slate.json
python3 -m brandkit.assemble_kit --metrics out/metrics/slate.json --skeleton 02-saas-marketing \
    --out out/kits
python3 -m brandkit.apply --kit out/kits/slate-assurance--02-saas-marketing.kit.json \
    --out out/restyled/slate-assurance--02-saas-marketing.html
# open out/restyled/slate-assurance--02-saas-marketing.html
```

The kit you get is four files: `kit.json` (facts, provenance and a fingerprint per group),
`kit.css` (CSS custom properties on `:root`, between the two markers a binder is allowed to touch),
`tokens.csv` and `DESIGN.md`.

`tokens.csv` carries a `Token,Color,Font,Value` header — the `Color` and `Font` columns a design
tool's token import expects, plus the token name and a value column so radii and shadows survive
the round trip instead of being silently dropped.

---

## Pointing it at a real brand URL

```bash
python3 -m brandkit.measure --source-url https://example.com/ --out out/metrics/example.json
```

That does **one** GET with a plain identifying User-Agent (`brandkit-lab/1.0 (+measured facts only; no crawling)`), no crawling,
no link following, and it is opt-in only: nothing in this repository reaches the network unless you
pass `--source-url` or `--drafter openai:...`. Respect the target's `robots.txt` and terms; the
three example brands are here precisely so you never have to scrape anything to try this out.

What you should expect from a real URL: a good palette and font read if the page ships its CSS in
the document, weaker results for runtime-injected styles, no logo or image extraction at all
(images are out of scope — this is a token kit, not an asset scraper), and copy candidates that
are only as good as the page's class naming.

---

## Limitations, plainly

* **The token contract is frozen on purpose.** 8 colours, 4 type slots, 3 radii, 2 shadows. Adding
  one means editing `brandkit/tokens.py`, and `tests/test_design_consistency.py` fails if `kit.css`
  ever publishes a token the contract does not know.
* **Fonts are names, not files.** A kit names the families the brand declares; the skeleton falls
  back through the stack if the machine does not have them, and no webfont is fetched. That is the
  right trade for an offline, reproducible repo — and it does mean a restyled page can look
  different from the brand's own site.
* **`measure.py` is heuristic.** It reads declared CSS, not computed style. A page that builds its
  palette in JavaScript will measure poorly.
* **The default drafter recycles the source's own sentences.** Copy is placeholder-grade by design;
  the LLM seam is where real copy comes from. Nav labels are left untouched by the default drafter
  for the same reason — see `CHROME_SLOTS` in `brandkit/drafter.py`.
* **The LLM seam is not covered by CI.** There is no key in CI, and the repository is designed to
  be verifiable without one. The seam is inert by default and its output is validated against the
  slot plan before it can reach a kit.
* **12 kits is not a benchmark.** It is 3 fictional brands × 4 skeletons, enough to prove the
  invariants, not enough to publish accuracy numbers.
* **Screenshots depend on the local Chrome.** Full-page PNGs are captured through the DevTools
  protocol with a hand-rolled websocket client (no `playwright`, no `websocket-client`); a
  different browser build can render a page one pixel differently.

---

## What the tests actually prove

| File | Claim |
|---|---|
| `test_registry.py` | the registry rejects malformed blocks and unknown ids; every skeleton binds only known blocks |
| `test_blocks_binding.py` | a newly registered block binds without touching the old ones; an id invented on an old skeleton is rejected |
| `test_tree_unchanged.py` | band list, repeat counts and element count are byte-identical after restyling; a deliberate tree mutation is caught |
| `test_determinism.py` | same input twice = identical kit bytes; the fingerprint is over facts, not copy |
| `test_design_consistency.py` | `DESIGN.md`'s tables and `kit.css` agree in both directions; a guardrail's discarded colour is really discarded |
| `test_two_models.py` | the invariant above, including that the two drafts really do differ in copy |
| `test_contrast_guardrail.py` | the naive path really fails, the shipped kit does not, and an unsatisfiable palette is refused |
| `test_token_usage.py` | no skeleton paints text on a decorative token; text tokens clear AA on every surface |
| `test_empty_slots.py` | an empty string means "leave the layout's own text", not "write nothing" |
| `test_measure.py` | the measurement heuristics against a known page, including provenance honesty |
| `test_drafter_seam.py` | the LLM seam is inert without a key and rejects a draft that invents slots |

---

## CI

`.github/workflows/ci.yml`:

* **lint + test** on Python 3.10, 3.11 and 3.12 — `scripts/check_lint.py` (no third-party imports
  anywhere, no network module outside the two allow-listed files, no remote assets in any page, no
  secret-shaped strings), `ruff check`, the test suite, and a smoke run of every CLI entry point.
* **eval gates** on 3.12 — runs the harness, fails if any threshold regresses, and fails if
  `docs/eval.json` in the repository is stale versus a fresh run. The numbers in this README are
  therefore re-checked on every push.
* The gallery is verified to reference only images that exist and to match a fresh render of
  `docs/eval.json`.

## Layout

```
brandkit/            tokens.py (the frozen contract)  measure.py  drafter.py
                     blocks.py (registry)  skeletons.py  assemble_kit.py (the only writer)
                     apply.py (the only binder)  util.py  htmltree.py
skeletons/           4 neutral landing pages + TREE.md each
sources/             3 fictional brand pages + README
tests/               204 tests
scripts/             eval_report.py  check_lint.py  shoot.py (CDP screenshots)  build_gallery.py
docs/                index.html (the gallery)  eval.json  img/*.png
```

## Author

**Shuo Zhao** — built as reference work for real front-end engineering with AI in the loop: the
model drafts words, the code owns the facts, and the invariants are tests.

MIT licensed.
