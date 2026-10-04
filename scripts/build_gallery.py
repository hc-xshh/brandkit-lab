#!/usr/bin/env python3
"""Render docs/index.html — the GitHub Pages gallery.

One file, no CDN, no JavaScript, no webfonts: it renders offline and it renders
on Pages. The numbers come from ``docs/eval.json``, which is written by
``scripts/eval_report.py``; the screenshots come from ``docs/img/``, which is
written by ``scripts/shoot.py`` running a real headless Chrome at the ``file://``
pages. Nothing on the page is typed by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

GALLERY_SKELETONS = ("01-host-landing", "02-saas-marketing", "03-product-security")
GALLERY_KITS = ("northwind-outfitters", "slate-assurance")
KIT_LABELS = {
    "northwind-outfitters": "Northwind Outfitters",
    "pulse-analytics": "Pulse Analytics",
    "slate-assurance": "Slate Assurance",
}
SKELETON_LABELS = {
    "01-host-landing": "01 · Host / landing",
    "02-saas-marketing": "02 · SaaS marketing",
    "03-product-security": "03 · Product security",
    "04-insurance-longform": "04 · Insurance long-form (EU)",
}
SKELETON_NOTES = {
    "01-host-landing": "nav · centred hero · proof strip · 3-up grid · stats · close · footer",
    "02-saas-marketing": "nav · split hero · prose + panel · 3 price tiers · quote · FAQ · close · footer",
    "03-product-security": "nav · centred hero · 4 stats · 3 pillars · 6 checks · FAQ · close · footer",
    "04-insurance-longform": "nav · split hero · prose ×3 · key-facts table · FAQ · close · footer",
}

CSS = """
:root {
  --ink: #0d1117; --ink-2: #4a5568; --line: #e2e8f0; --paper: #ffffff;
  --paper-2: #f6f8fb; --accent: #1f5df6; --accent-ink: #ffffff;
  --ok: #0f7b52; --warn: #a45a00; --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.62 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 0 28px; }
header.top {
  background: linear-gradient(160deg, #0b1120 0%, #131c31 60%, #1b2740 100%);
  color: #eef2fb; padding: 64px 0 56px; border-bottom: 1px solid #22304d;
}
header.top h1 { font-size: 2.5rem; line-height: 1.1; margin: 0 0 .5rem; letter-spacing: -0.02em; }
header.top p.lede { font-size: 1.12rem; color: #b9c6dd; max-width: 72ch; margin: 0 0 1.4rem; }
.kicker {
  font: 600 .74rem/1 system-ui, sans-serif; letter-spacing: .16em; text-transform: uppercase;
  color: #8fa6cc; margin: 0 0 .9rem;
}
.pipeline {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  font-family: var(--mono); font-size: .84rem; color: #cbd7ec;
}
.pipeline span { border: 1px solid #2c3b5c; border-radius: 999px; padding: 5px 12px; background: #16203a; }
.pipeline b { color: #7d93b8; font-weight: 400; }
section { padding: 56px 0; border-bottom: 1px solid var(--line); }
section:last-of-type { border-bottom: 0; }
h2 { font-size: 1.6rem; margin: 0 0 .4rem; letter-spacing: -0.01em; }
h2 + p.sub { color: var(--ink-2); margin: 0 0 2rem; max-width: 84ch; }
h3 { font-size: 1.05rem; margin: 0 0 .35rem; }
.grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.stat { border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; background: var(--paper-2); }
.stat b { display: block; font: 600 1.9rem/1.1 var(--mono); letter-spacing: -0.02em; }
.stat span { color: var(--ink-2); font-size: .84rem; }
.stat small { display: block; color: #7a869a; font-size: .74rem; margin-top: .3rem; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line); }
th { font-weight: 620; color: var(--ink-2); font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; }
td.num, th.num { font-family: var(--mono); text-align: right; }
.pass { color: var(--ok); font-weight: 600; }
.warn { color: var(--warn); font-weight: 600; }
.shotgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.shot { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: var(--paper-2); }
.shot .cap {
  padding: 11px 14px; border-bottom: 1px solid var(--line); background: var(--paper);
  font-size: .82rem; display: flex; justify-content: space-between; gap: 8px; align-items: baseline;
}
.shot .cap b { font-weight: 620; }
.shot .cap span { color: #7a869a; font-family: var(--mono); font-size: .74rem; }
.shot .frame {
  max-height: 540px; overflow: hidden; background: var(--paper);
  -webkit-mask-image: linear-gradient(to bottom, #000 78%, transparent 100%);
  mask-image: linear-gradient(to bottom, #000 78%, transparent 100%);
}
.shot img { width: 100%; display: block; }
.shot .open { padding: 10px 14px; font-size: .78rem; color: var(--ink-2); }
.shot .open a { color: var(--accent); }
.skeleton-block { margin-bottom: 40px; }
.skeleton-block h3 { display: flex; gap: 10px; align-items: baseline; }
.skeleton-block h3 span { color: var(--ink-2); font-weight: 400; font-size: .84rem; }
.swatches { display: flex; flex-wrap: wrap; gap: 10px; }
.swatch {
  border: 1px solid var(--line); border-radius: 10px; overflow: hidden; min-width: 118px;
  font-family: var(--mono); font-size: .72rem;
}
.swatch .chip { height: 44px; }
.swatch .meta { padding: 7px 9px; background: var(--paper); }
.swatch .meta b { display: block; font-weight: 600; }
.callout {
  border: 1px solid #f0d9a8; background: #fff9ec; border-radius: 12px; padding: 18px 20px; margin: 18px 0 0;
}
.callout h3 { color: #7a4a00; }
.callout code { font-family: var(--mono); font-size: .85rem; background: #fff; padding: 1px 5px; border-radius: 4px; border: 1px solid #f0e2c4; }
pre {
  background: #0b1120; color: #d7e2f5; border-radius: 12px; padding: 18px 20px; overflow-x: auto;
  font-family: var(--mono); font-size: .84rem; line-height: 1.55;
}
pre .c { color: #7f93b5; }
footer { padding: 36px 0 56px; color: var(--ink-2); font-size: .86rem; }
footer b { color: var(--ink); }
@media (max-width: 960px) {
  .grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .shotgrid { grid-template-columns: 1fr; }
}
"""


def load_report(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(
            f"missing {path}. Run `make eval` (or scripts/eval_report.py) first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def row_by(report: dict, source: str, skeleton: str) -> dict:
    for row in report["rows"]:
        if row["source"] == source and row["skeleton"] == skeleton:
            return row
    raise SystemExit(f"eval.json has no row for {source} x {skeleton}; re-run `make eval`")


def check_images(img_dir: Path, skeletons, kits) -> list[str]:
    needed = [f"before-{s}.png" for s in skeletons]
    needed += [f"after-{k}--{s}.png" for k in kits for s in skeletons]
    missing = [name for name in needed if not (img_dir / name).is_file()]
    if missing:
        raise SystemExit(
            "missing screenshots: "
            + ", ".join(missing)
            + "\nRun `make gallery` (it calls scripts/shoot.py), or scripts/shoot.py directly."
        )
    return needed


def build(report: dict, img_dir: Path) -> str:
    summary = report["summary"]
    kits_fingerprint = summary["tokens_per_source"]
    rows = report["rows"]

    def stat_block(value: str, label: str, note: str) -> str:
        return f'<div class="stat"><b>{value}</b><span>{label}</span><small>{note}</small></div>'

    stats = "".join([
        stat_block(f"{summary['kits']}", "kits produced",
                   f"{summary['sources']} sources × {summary['skeletons']} skeletons"),
        stat_block(f"{summary['tree_unchanged_rate'] * 100:.0f}%", "tree unchanged",
                   "band list + repeats byte-identical"),
        stat_block(f"{summary['contrast_min']:.2f}:1", "worst enforced contrast",
                   "WCAG AA floor is 4.50:1"),
        stat_block(f"{summary['determinism_rate'] * 100:.0f}%", "byte-identical reruns",
                   f"{summary['bands_total']} bands, {summary['elements_total']} elements"),
    ])

    # per-kit table
    table_rows = "".join(
        f"<tr><td>{r['source']}</td><td>{r['skeleton']}</td>"
        f"<td class='num'>{r['slots_filled']}/{r['slots_total']}</td>"
        f"<td class='num'>{r['contrast_min']:.2f}:1</td>"
        f"<td class='num'>{r['bands']}</td>"
        f"<td class='num'>{r['repeat_items']}</td>"
        f"<td class='num'>{r['guardrails']}</td>"
        f"<td class='num'>{'yes' if r['tree_unchanged'] else 'NO'}</td>"
        f"<td class='num'>{'yes' if r['deterministic'] else 'NO'}</td>"
        f"<td class='num'>{r['determinism_hash']}</td></tr>"
        for r in rows
    )

    # screenshots, grouped by skeleton
    shots = []
    for skeleton in GALLERY_SKELETONS:
        cells = [(
            "before",
            "Skeleton, untouched",
            f"before-{skeleton}.png",
            0,
        )]
        for kit in GALLERY_KITS:
            row = row_by(report, kit, skeleton)
            cells.append((
                KIT_LABELS[kit],
                f"{row['contrast_min']:.2f}:1 worst · {row['slots_filled']} slots",
                f"after-{kit}--{skeleton}.png",
                row["guardrails"],
            ))
        cards = "".join(
            f'<figure class="shot" style="margin:0">'
            f'<div class="cap"><b>{label}</b><span>{note}</span></div>'
            f'<div class="frame"><img src="img/{name}" alt="{label} on {skeleton}" loading="lazy"></div>'
            f'<div class="open"><a href="img/{name}">open full page PNG</a>'
            + (f' · guardrail fired ({count})' if count else "")
            + "</div></figure>"
            for label, note, name, count in cells
        )
        shots.append(
            f'<div class="skeleton-block"><h3>{SKELETON_LABELS[skeleton]}'
            f'<span>{SKELETON_NOTES[skeleton]}</span></h3>'
            f'<div class="shotgrid">{cards}</div></div>'
        )

    # palette swatches for one kit per source
    swatch_groups = []
    for source in kits_fingerprint:
        row = row_by(report, source, "01-host-landing")
        kit_json = REPO_ROOT / "out" / "kits" / f"{source}--01-host-landing.kit.json"
        if not kit_json.is_file():
            continue
        kit = json.loads(kit_json.read_text(encoding="utf-8"))
        chips = "".join(
            f'<div class="swatch"><div class="chip" style="background:{value}"></div>'
            f'<div class="meta"><b>--{name}</b>{value}'
            f'<br>{kit["provenance"][f"color.{name}"]}</div></div>'
            for name, value in kit["tokens"]["color"].items()
        )
        fonts = kit["tokens"]["font"]
        swatch_groups.append(
            f'<h3 style="margin-top:26px">{KIT_LABELS.get(source, source)}'
            f'<span style="color:var(--ink-2);font-weight:400;font-size:.84rem">'
            f' · {kit["tokens"]["radius"]["cta"]} CTA radius'
            f' · {fonts["heading-font"]} / {fonts["body-font"]}</span></h3>'
            f'<div class="swatches">{chips}</div>'
        )

    guardrail_rows = [
        r for r in rows if r.get("guardrails")
    ]
    guardrail_html = ""
    if guardrail_rows:
        first = guardrail_rows[0]
        # Tell the story of the guardrail that had to *replace* a colour: that is
        # the one with a `kept_as` token. Every other guardrail is a value shift.
        detail = next(
            (item for item in first["guardrail_details"] if item.get("kept_as")),
            first["guardrail_details"][0],
        )
        guardrail_html = f"""
<section>
  <div class="wrap">
    <h2>The case that fails naively, and the guardrail that catches it</h2>
    <p class="sub">Slate Assurance is greyscale with a single accent colour, declared as a
    <em>text</em> colour on white. The measured brand colour is
    <code>{detail['before']}</code>, which sits at <b>{detail['contrast_before']}:1</b>
    on the page surface. A pipeline that copies the brand colour into the link colour ships
    unreadable text; this one keeps the measured colour where colour is decoration and derives a
    legible primary for anything that carries words.</p>
    <div class="callout">
      <h3>Guardrail · {detail['token']}</h3>
      <p><b>{detail['before']}</b> → <b>{detail['after']}</b> ({detail['strategy']},
      {detail['contrast_before']}:1 → {detail['contrast_after']}:1 on the worst surface).
      The measured colour survives as <code>--{detail['kept_as']}</code>, which is used for
      surfaces, rules and underlines but never for text.</p>
      <p style="margin:0">Every kit in this gallery is gated on that rule: if an enforced pair
      cannot reach 4.5:1, <code>assemble_kit()</code> raises instead of writing a kit.</p>
    </div>
  </div>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>brandkit-lab — measured brand kits, unbroken layouts</title>
<meta name="description" content="A brand source page becomes a frozen token kit and a DESIGN.md,
then restyles neutral landing skeletons without moving the DOM tree. Generated evidence, no CDN.">
<style>{CSS}</style>
</head>
<body>

<header class="top">
  <div class="wrap">
    <p class="kicker">brandkit-lab · dependency-free Python · generated gallery</p>
    <h1>A brand page in. A frozen kit out. The layout does not move.</h1>
    <p class="lede">One measurable pipeline: measure the facts a brand source actually declares,
    draft only the words, assemble a single kit that is the sole writer of every token, and bind it
    onto neutral landing skeletons while proving the band list and repeat counts are unchanged.</p>
    <div class="pipeline">
      <span>source.html</span><b>→</b><span>measure</span><b>→</b><span>metrics.json</span>
      <b>→</b><span>draft (LLM seam)</span><b>→</b><span>assemble_kit</span><b>→</b>
      <span>kit.json · kit.css · tokens.csv · DESIGN.md</span><b>→</b><span>apply + proof.json</span>
    </div>
  </div>
</header>

<section>
  <div class="wrap">
    <h2>What the harness measured, not what the README claims</h2>
    <p class="sub">Written by <code>scripts/eval_report.py</code> into <code>docs/eval.json</code>.
    The same script exits non-zero if any of these thresholds regress, so this table is a gate,
    not a souvenir.</p>
    <div class="grid-4">{stats}</div>
    <table style="margin-top:26px">
      <thead><tr>
        <th>source</th><th>skeleton</th><th class="num">slots</th><th class="num">worst contrast</th>
        <th class="num">bands</th><th class="num">repeats</th><th class="num">guardrails</th>
        <th class="num">tree</th><th class="num">determin.</th><th class="num">kit hash</th>
      </tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
    <p class="sub" style="margin-top:16px">Token fingerprints — one kit per brand, identical on
    every skeleton it is bound to:
    {" · ".join(f"<code>{source}</code> {fp}" for source, fp in kits_fingerprint.items())}.</p>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>Before and after, rendered in headless Chrome</h2>
    <p class="sub">Left: the skeleton with its own neutral theme. Then the same untouched markup
    carrying each brand's kit. The band list, the number of bands and every repeat count are
    identical in all three; only the token block and the copy slots differ. Screenshots are
    full-page captures of the local <code>file://</code> pages — no CDN, no webfonts, so what you
    see is what CI renders.</p>
    {"".join(shots)}
  </div>
</section>

<section>
  <div class="wrap">
    <h2>The kits themselves</h2>
    <p class="sub">Colour tokens straight out of each kit's <code>kit.json</code>, with provenance:
    <em>measured</em> means the source page declared it, <em>derived</em> means the kit builder had
    to compute it (a sibling surface, a raised elevation, or the contrast repair above).</p>
    {"".join(swatch_groups)}
  </div>
</section>
{guardrail_html}
<section>
  <div class="wrap">
    <h2>Reproduce all of it</h2>
    <p class="sub">Standard library only. The three example brand sources are fictional pages
    authored for this repository, so the whole thing runs offline and license-clean.</p>
<pre><span class="c"># the gate: 3 sources x 4 skeletons, thresholds enforced</span>
make eval          <span class="c"># writes docs/eval.json, fails on regression</span>

<span class="c"># the gallery you are reading (needs a headless Chrome)</span>
make gallery       <span class="c"># restyles pages, screenshots them, rebuilds this file</span>

<span class="c"># one brand, by hand</span>
make kit SOURCE=slate-assurance SKELETON=02-saas-marketing
open out/restyled/slate-assurance--02-saas-marketing.html

<span class="c"># what is in the registry</span>
make api</pre>
  </div>
</section>

<footer>
  <div class="wrap">
    <p><b>brandkit-lab</b> — authored by <b>Shuo Zhao</b>. Zero third-party runtime dependencies;
    the only optional network call in the whole repository is the documented
    <code>--drafter openai:&lt;model&gt;</code> seam, which is inert unless you ask for it.</p>
    <p>Every number on this page is written by a script in this repository from artefacts produced
    by the pipeline. Nothing is typed by hand.</p>
  </div>
</footer>

</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", default=str(REPO_ROOT / "docs" / "eval.json"))
    ap.add_argument("--img", default=str(REPO_ROOT / "docs" / "img"))
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "index.html"))
    ap.add_argument("--verify", action="store_true",
                    help="check that the committed gallery and its images agree; write nothing")
    args = ap.parse_args(argv)

    report = load_report(Path(args.eval))
    img_dir = Path(args.img)
    out = Path(args.out)

    if args.verify:
        names = check_images(img_dir, GALLERY_SKELETONS, GALLERY_KITS)
        if not out.is_file():
            raise SystemExit(f"{out} is missing; run scripts/build_gallery.py")
        html = out.read_text(encoding="utf-8")
        referenced = set(re.findall(r'src="img/([^"]+)"', html))
        missing = sorted(name for name in names if name not in referenced)
        dangling = sorted(name for name in referenced if not (img_dir / name).is_file())
        if missing or dangling:
            for name in missing:
                print(f"verify: {name} exists but is not shown in the gallery", file=sys.stderr)
            for name in dangling:
                print(f"verify: the gallery references img/{name}, which does not exist",
                      file=sys.stderr)
            return 1
        expected = build(report, img_dir)
        if expected != html:
            print("verify: docs/index.html does not match a fresh render of docs/eval.json",
                  file=sys.stderr)
            return 1
        print(f"verify: {len(referenced)} screenshots referenced and present; "
              f"index.html matches a fresh render of eval.json")
        return 0

    names = check_images(img_dir, GALLERY_SKELETONS, GALLERY_KITS)
    html = build(report, img_dir)
    out.write_text(html, encoding="utf-8")
    print(f"gallery: {len(names)} screenshots referenced, "
          f"{report['summary']['kits']} kits in the table")
    print(f"gallery: wrote {out} ({len(html.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
