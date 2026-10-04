"""The LLM step is a seam, and a seam has to be inert by default.

These tests assert the *offline* behaviour of the hook: it refuses to run without
a key, it validates what a model returns, and it never lets a model near a token.
No test in this repository performs a network call.
"""

from __future__ import annotations

import pytest

from brandkit import drafter, skeletons


def test_no_api_key_means_no_call(monkeypatch, metrics_all):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    skeleton = skeletons.load("01-host-landing")
    with pytest.raises(drafter.DraftError) as excinfo:
        drafter.draft_via_llm(skeleton, metrics_all["northwind-outfitters"], "some-model")
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_the_dispatcher_only_touches_the_llm_path_when_asked(monkeypatch, metrics_all):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    metrics = metrics_all["northwind-outfitters"]
    # the default path is the rule-based one and needs nothing
    draft = drafter.draft_for("01-host-landing", metrics)
    assert draft["model"] == "rules-v1"
    # asking for an endpoint without a key fails fast instead of guessing
    with pytest.raises(drafter.DraftError):
        drafter.draft_for("01-host-landing", metrics, "openai:gpt-4o-mini")


def test_a_model_may_not_return_design_facts(skeleton_all):
    skeleton = skeleton_all["01-host-landing"]
    for forbidden in ("tokens", "css", "theme", "palette", "colors"):
        with pytest.raises(drafter.DraftError):
            drafter.validate_llm_copy({forbidden: {"paper": "#fff"}, "copy": {}}, skeleton)


def test_a_model_may_not_invent_slots(skeleton_all):
    skeleton = skeleton_all["01-host-landing"]
    with pytest.raises(drafter.DraftError) as excinfo:
        drafter.validate_llm_copy({"copy": {"hero-center.h9": "Nope"}}, skeleton)
    assert "invented" in str(excinfo.value)


def test_valid_model_output_is_accepted(skeleton_all):
    skeleton = skeleton_all["01-host-landing"]
    cleaned = drafter.validate_llm_copy(
        {"copy": {"hero-center.h1": "A headline", "hero-center.lead": "  "}},
        skeleton,
    )
    assert cleaned == {"hero-center.h1": "A headline"}, "empty values are dropped, not written"


def test_the_prompt_forbids_design_changes(metrics_all):
    skeleton = skeletons.load("01-host-landing")
    prompt = drafter.build_llm_prompt(skeleton, metrics_all["pulse-analytics"])
    assert "slot key" in prompt
    assert "hero-center.h1" in prompt
    assert "never return colours" in drafter.SYSTEM_PROMPT.lower()
    assert "{" in drafter.SYSTEM_PROMPT and "copy" in drafter.SYSTEM_PROMPT


def test_the_slot_plan_matches_the_layout_exactly(skeleton_all):
    for skeleton_id, skeleton in skeleton_all.items():
        planned = {slot["key"] for slot in drafter.slot_plan(skeleton)}
        assert planned == set(skeleton.slot_text()), skeleton_id
        assert [slot["key"] for slot in drafter.slot_plan(skeleton)] == \
            [slot["key"] for slot in drafter.slot_plan(skeleton)], "plan order must be stable"


def test_rule_drafters_are_the_only_offline_models():
    assert drafter.DEFAULT_MODEL in drafter.RULE_MODELS
    with pytest.raises(drafter.DraftError):
        drafter.draft(skeletons.load("01-host-landing"), {"copy_pool": {"h1": ["x"]}},
                      model="gpt-4o-mini")
