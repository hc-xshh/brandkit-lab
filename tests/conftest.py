"""Shared fixtures.

Everything the suite needs is rebuilt from the repository's own files, so a
failure here means the pipeline is broken, not that a checked-in golden file
went stale. Nothing in the suite touches the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brandkit import drafter, measure, skeletons  # noqa: E402
from brandkit.assemble_kit import assemble_kit  # noqa: E402

SOURCES = ("northwind-outfitters", "pulse-analytics", "slate-assurance")
SKELETONS = (
    "01-host-landing",
    "02-saas-marketing",
    "03-product-security",
    "04-insurance-longform",
)

#: The deliberately awkward source: greyscale plus one accent that cannot carry text.
AWKWARD_SOURCE = "slate-assurance"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def metrics_all() -> dict[str, dict]:
    """Measured facts for every example source, measured fresh from the HTML."""
    return {
        source: measure.measure_source(REPO_ROOT / "sources" / f"{source}.html")
        for source in SOURCES
    }


@pytest.fixture(scope="session")
def skeleton_all() -> dict[str, skeletons.Skeleton]:
    return skeletons.load_all()


@pytest.fixture(scope="session")
def paired(metrics_all: dict[str, dict]):
    """Every (source, skeleton) pair with its draft and its assembled kit."""

    def build(drafter_name: str = drafter.DEFAULT_MODEL):
        out = {}
        for source_id, metrics in metrics_all.items():
            for skeleton_id in SKELETONS:
                skeleton = skeletons.load(skeleton_id)
                draft = drafter.draft(skeleton, metrics, model=drafter_name)
                kit = assemble_kit(draft, metrics)
                out[(source_id, skeleton_id)] = (draft, kit, skeleton)
        return out

    return build
