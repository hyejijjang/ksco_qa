from __future__ import annotations

from pathlib import Path

from ksco_qa.config import Config
from ksco_qa.estimate import estimate_run
from ksco_qa.p0 import run_p0


def test_estimate_reports_call_bounds_without_decisions(sample_task: Path, tmp_path: Path) -> None:
    p0 = run_p0(sample_task, Config(), tmp_path, tmp_path / "00_mapping_audit.csv")
    report = estimate_run(p0.row_cards, Config())

    assert report["rows"] == len(p0.row_cards)
    assert report["inspected_rows"] == sum(bool(card["inspected"]) for card in p0.row_cards)
    assert report["calls"]["G0_initial"] == report["inspected_rows"]
    assert report["calls"]["G0_escalation_estimate"] >= 0
    assert report["calls"]["G1B_candidate_bundles_lower_bound"] == report["candidate_bundles"]
    assert report["calls"]["G2_upper_bound"] == report["inspected_rows"]
    assert report["cost_usd_estimate"] is None
    assert report["assumptions"]
    assert all("action" not in card for card in p0.row_cards)


def test_estimate_computes_cost_when_rates_are_configured(sample_task: Path, tmp_path: Path) -> None:
    cfg = Config(PRICE_INPUT=1, PRICE_CACHED_INPUT=0.5, PRICE_OUTPUT=2)
    p0 = run_p0(sample_task, cfg, tmp_path, tmp_path / "00_mapping_audit.csv")

    report = estimate_run(p0.row_cards, cfg)

    assert isinstance(report["cost_usd_estimate"], float)
    assert report["cost_usd_estimate"] > 0
