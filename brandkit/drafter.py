"""The copy-drafting seam.

Everything in this pipeline is deterministic *except* the step that writes the
words onto a layout, and this module is that seam. Two implementations live here:

``draft(...)``
    The default. Rule-based, offline, no network, no model, byte-stable: the
    same metrics plus the same skeleton always produce the same draft. This is
    what the tests, the eval harness and CI use.

``draft_via_llm(...)``
    An optional hook for any OpenAI-compatible ``/chat/completions`` endpoint,
    driven through :mod:`urllib` with ``temperature=0`` and the API key read from
    an environment variable. It is **inert unless explicitly requested** on the
    command line (``--drafter openai:<model>``). Importing this module never
    touches the network, and the repository is fully usable and verifiable
    without it.

Why the seam matters: a draft may carry **copy only**. The measured facts --the
palette, the type roles, the radius scale, the elevation -- come from
``metrics`` and are written exactly once, by :mod:`brandkit.assemble_kit`. That is
what makes two different models produce the same kit: they can disagree about
every sentence and still cannot disagree about a hex.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import skeletons as skeletons_mod
from .blocks import DEFAULT, Registry
from .util import dumps_stable, sha256_text

DEFAULT_MODEL = "rules-v1"

#: Deterministic "models" that stand in for two different LLM outputs. They pick
#: different sentences on purpose; see tests/test_two_models.py.
RULE_MODELS = ("rules-v1", "alt-v1")

#: Slot field -> pools to draw from, most preferred first. The order inside a
#: pool is the measured order (i.e. the source page's own order).
SLOT_POOLS: dict[str, tuple[str, ...]] = {
    "brand": ("__brand__",),
    "h1": ("h1", "lead", "h2"),
    "h2": ("h2", "h1", "lead"),
    "h3": ("h3", "h2"),
    "eyebrow": ("eyebrow", "meta"),
    "lead": ("lead", "body", "h2"),
    "body": ("body", "lead"),
    "quote": ("lead", "body"),
    "attribution": ("meta", "eyebrow"),
    "meta": ("meta", "eyebrow"),
    "cta": ("cta", "eyebrow", "meta"),
    "cta-secondary": ("cta", "link"),
    "footer": ("footer", "meta"),
    "nav-item": ("eyebrow", "meta"),
    "item-title": ("h3", "h2"),
    "item-body": ("body", "lead"),
    "item-label": ("eyebrow", "meta"),
    "item-value": ("meta", "eyebrow"),
    "item-name": ("h3", "eyebrow"),
    "item-price": ("meta",),
    "item-cta": ("cta", "link"),
    "item-meta": ("meta",),
    "item-q": ("h2", "h3"),
    "item-a": ("body", "lead"),
}

#: Slots that must never be filled from a pool because they are not prose.
DERIVED_SLOTS = ("brand",)

#: A rule-based drafter cannot invent navigation labels, so it leaves those to
#: the layout. Only *optional* slots may appear here: a required slot must still
#: be filled by the draft or the kit is refused. This is a documented limitation
#: of the offline default, not of the kit -- a real model is free to supply copy
#: for them (see ``draft_via_llm``), and so is a human with a JSON file.
CHROME_SLOTS = {
    ("nav-bar", "nav-item"),
    ("footer-legal", "nav-item"),
}


class DraftError(Exception):
    """The draft is not usable: bad shape, unknown slots, or tokens smuggled in."""


# --------------------------------------------------------------------------
# slot plan: which slots exist on which skeleton, in binding order
# --------------------------------------------------------------------------
def slot_plan(skeleton: skeletons_mod.Skeleton, registry: Registry | None = None) -> list[dict]:
    """The ordered list of slots a draft must decide about.

    Required slots come first within a band, then optional ones, then the
    repeated fields in index order -- the same order every time, so two drafts
    are directly comparable. Only slots the *page* actually has appear: a plan is
    a description of this layout, not of the block in the abstract, so copy is
    never drafted for a place that does not exist.
    """
    registry = registry or DEFAULT
    plan: list[dict] = []
    counts = skeleton.repeats
    present = set(skeleton.slot_text())
    for band in skeleton.bands:
        block_id = band["block"]
        if block_id not in registry:
            raise DraftError(f"skeleton {skeleton.id!r} uses unknown block {block_id!r}")
        block = registry.resolve(block_id)
        repeated = set(block.repeat.fields) if block.repeat else set()

        for field in block.all_fields:
            if field in repeated:
                continue
            key = f"{block_id}.{field}"
            if key not in present:
                continue
            plan.append({
                "key": key,
                "block": block_id,
                "field": field,
                "index": None,
                "required": field in block.required,
                "band": band["band"],
            })
        if block.repeat:
            count = counts.get(f"{block_id}.{block.repeat.name}", 0)
            for field in block.repeat.fields:
                for index in range(count):
                    key = f"{block_id}.{field}[{index}]"
                    if key not in present:
                        continue
                    plan.append({
                        "key": key,
                        "block": block_id,
                        "field": field,
                        "index": index,
                        "required": field in block.required,
                        "band": band["band"],
                    })
    return plan


def brand_name(metrics: dict) -> str:
    """The brand string a kit may use for a ``brand`` slot."""
    override = (metrics.get("source") or {}).get("brand")
    if override:
        return str(override)
    source_id = (metrics.get("source") or {}).get("id") or "brand"
    return " ".join(word.capitalize() for word in re.split(r"[-_]+", source_id) if word)


# --------------------------------------------------------------------------
# deterministic drafters
# --------------------------------------------------------------------------
class _Pool:
    """A per-pool cursor that cycles. Deterministic, no randomness."""

    def __init__(self, pools: dict[str, list[str]], reverse: bool = False) -> None:
        self.pools = {k: (list(reversed(v)) if reverse else list(v)) for k, v in pools.items()}
        self.cursor: dict[str, int] = {}

    def take(self, field: str, brand: str, used: set[str]) -> str | None:
        """Take the next string for ``field``.

        Preference order is the pool chain in :data:`SLOT_POOLS`. A string that
        has not been used yet anywhere wins; only when every pool in the chain is
        exhausted does the cursor wrap and start repeating, which is what keeps a
        small copy pool from producing a page of identical sentences.
        """
        chains = SLOT_POOLS.get(field, ())
        for pool_name in chains:
            if pool_name == "__brand__":
                return brand
            values = self.pools.get(pool_name) or []
            if not values:
                continue
            start = self.cursor.get(pool_name, 0)
            for offset in range(len(values)):
                candidate = values[(start + offset) % len(values)]
                if candidate not in used:
                    self.cursor[pool_name] = (start + offset + 1) % len(values)
                    used.add(candidate)
                    return candidate
        # Everything in the chain is used: cycle the first pool that has anything.
        for pool_name in chains:
            values = self.pools.get(pool_name) or []
            if values:
                start = self.cursor.get(pool_name, 0)
                candidate = values[start % len(values)]
                self.cursor[pool_name] = (start + 1) % len(values)
                return candidate
        return None


def draft(
    skeleton: skeletons_mod.Skeleton,
    metrics: dict,
    model: str = DEFAULT_MODEL,
    registry: Registry | None = None,
) -> dict:
    """Draft copy for ``skeleton`` from the measured ``metrics``.

    Returns a draft document: ``model``, the source it was drafted for, the
    ``copy`` mapping and a fingerprint. Empty slots are simply absent from
    ``copy`` -- a kit that fills fewer slots than the layout has is valid, and
    the layout keeps its own text in those slots.
    """
    if model not in RULE_MODELS:
        raise DraftError(
            f"unknown rule model {model!r}; expected one of {', '.join(RULE_MODELS)}"
        )
    pools = {k: list(v) for k, v in (metrics.get("copy_pool") or {}).items()}
    if not pools:
        raise DraftError("metrics carry no copy_pool; nothing to draft from")

    brand = brand_name(metrics)
    reverse = model == "alt-v1"
    pool = _Pool(pools, reverse=reverse)
    used: set[str] = set()
    copy: dict[str, str] = {}
    skipped: list[str] = []
    plan = slot_plan(skeleton, registry)
    chrome_keys = sorted(
        slot["key"] for slot in plan if (slot["block"], slot["field"]) in CHROME_SLOTS
    )

    for slot in plan:
        if (slot["block"], slot["field"]) in CHROME_SLOTS:
            skipped.append(slot["key"])
            continue
        text = pool.take(slot["field"], brand, used)
        if not text:
            skipped.append(slot["key"])
            continue
        if slot["field"] == "eyebrow" and model == "alt-v1":
            text = text.rstrip(".:")
        copy[slot["key"]] = text.strip()

    return {
        "schema": "brandkit/draft@1",
        "model": model,
        "source_id": (metrics.get("source") or {}).get("id", ""),
        "skeleton": skeleton.id,
        "copy": dict(sorted(copy.items())),
        "unfilled_slots": sorted(skipped),
        "chrome_slots_left_to_layout": chrome_keys,
        "copy_fingerprint": sha256_text(dumps_stable(copy)),
        "slot_count": len(plan),
    }


# --------------------------------------------------------------------------
# optional LLM hook (inert unless explicitly requested)
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are drafting marketing copy for a fixed web page layout.

Rules that are not negotiable:
* Answer with JSON only: {"copy": {"<slot key>": "<text>"}}.
* Keys must come from the slot list you are given. Never invent a key.
* Text only. Never return colours, fonts, radii, shadows, CSS or tokens: the
  design kit is measured from the brand source and you cannot influence it.
* Keep each string close to the length of the example it replaces.
* Write in English, in the voice of the brand summary you are given.
"""


def build_llm_prompt(skeleton: skeletons_mod.Skeleton, metrics: dict) -> str:
    plan = slot_plan(skeleton)
    existing = skeleton.slot_text()
    lines = [
        "BRAND SUMMARY",
        f"  id: {(metrics.get('source') or {}).get('id')}",
        f"  palette: {json.dumps(metrics.get('roles', {}), sort_keys=True)}",
        f"  type: {json.dumps(metrics.get('fonts', {}).get('roles', {}), sort_keys=True)}",
        "",
        "SLOTS TO FILL (slot key | required | text currently in the layout)",
    ]
    for slot in plan:
        lines.append(
            f"  {slot['key']} | {'required' if slot['required'] else 'optional'} | "
            f"{existing.get(slot['key'], '')[:160]}"
        )
    lines += [
        "",
        "SOURCE COPY SAMPLES (the brand's own sentences, to imitate in length and register)",
    ]
    for pool_name, values in sorted((metrics.get("copy_pool") or {}).items()):
        if values:
            lines.append(f"  [{pool_name}] " + " / ".join(values[:3]))
    return "\n".join(lines)


def validate_llm_copy(payload: dict, skeleton: skeletons_mod.Skeleton) -> dict[str, str]:
    """Reject anything a model is not allowed to say."""
    if not isinstance(payload, dict):
        raise DraftError("model response is not a JSON object")
    forbidden = {"tokens", "colors", "colours", "css", "theme", "palette"}
    present = forbidden & set(payload)
    if present:
        raise DraftError(
            f"model tried to influence the design: {sorted(present)}. Copy only."
        )
    raw = payload.get("copy")
    if not isinstance(raw, dict):
        raise DraftError("model response has no 'copy' object")
    allowed = {slot["key"] for slot in slot_plan(skeleton)}
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if key not in allowed:
            raise DraftError(f"model invented slot {key!r}")
        if not isinstance(value, str) or not value.strip():
            continue
        cleaned[key] = value.strip()
    return cleaned


def draft_via_llm(
    skeleton: skeletons_mod.Skeleton,
    metrics: dict,
    model: str,
    base_url: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
    timeout: int = 60,
) -> dict:
    """Draft copy through an OpenAI-compatible endpoint.

    Only ever called when the caller asks for ``--drafter openai:<model>``. The
    key is read from the environment and is never written to a draft, a kit or a
    log; the endpoint is never contacted at import time.
    """
    key = os.environ.get(api_key_env)
    if not key:
        raise DraftError(f"{api_key_env} is not set; refusing to call {model!r}")
    url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1")
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_llm_prompt(skeleton, metrics)},
        ],
    }
    request = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "brandkit-lab/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise DraftError(f"LLM request failed: {exc}") from exc

    content = payload["choices"][0]["message"]["content"]
    copy = validate_llm_copy(json.loads(content), skeleton)
    return {
        "schema": "brandkit/draft@1",
        "model": f"openai:{model}",
        "source_id": (metrics.get("source") or {}).get("id", ""),
        "skeleton": skeleton.id,
        "copy": dict(sorted(copy.items())),
        "unfilled_slots": sorted({s["key"] for s in slot_plan(skeleton)} - set(copy)),
        "copy_fingerprint": sha256_text(dumps_stable(copy)),
        "slot_count": len(slot_plan(skeleton)),
        "seam": {"endpoint": url, "temperature": 0, "api_key_env": api_key_env},
    }


def draft_for(
    skeleton_id: str,
    metrics: dict,
    drafter: str = DEFAULT_MODEL,
    registry: Registry | None = None,
) -> dict:
    """Dispatch on a ``--drafter`` value: ``rules-v1``, ``alt-v1`` or ``openai:<model>``."""
    skeleton = skeletons_mod.load(skeleton_id)
    if drafter.startswith("openai:"):
        return draft_via_llm(skeleton, metrics, drafter.split(":", 1)[1])
    return draft(skeleton, metrics, model=drafter, registry=registry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draft copy for a skeleton from measured facts.")
    ap.add_argument("--metrics", required=True, help="path to a metrics.json")
    ap.add_argument("--skeleton", required=True, help="skeleton id, e.g. 01-host-landing")
    ap.add_argument(
        "--drafter",
        default=DEFAULT_MODEL,
        help="rules-v1 | alt-v1 | openai:<model> (the last one needs OPENAI_API_KEY)",
    )
    ap.add_argument("--out", required=True, help="where to write the draft json")
    args = ap.parse_args(argv)

    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    try:
        draft_doc = draft_for(args.skeleton, metrics, args.drafter)
    except DraftError as exc:
        print(f"drafting failed: {exc}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps_stable(draft_doc), encoding="utf-8")
    filled = len(draft_doc["copy"])
    print(
        f"drafted {args.skeleton} with {draft_doc['model']}: {filled}/{draft_doc['slot_count']} "
        f"slots filled, {len(draft_doc['unfilled_slots'])} left to the layout "
        f"(fingerprint {draft_doc['copy_fingerprint'][:12]})"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
