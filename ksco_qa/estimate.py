"""Model-call and token estimates based on P0 inputs and documented assumptions."""

from __future__ import annotations

import math
from typing import Any

from ksco_qa.config import Config
from ksco_qa.stages.g1a import generate_candidates, make_bundles

DESIGN_TOKEN_ASSUMPTIONS = {
    "G0": {"input": 7000, "output_reasoning": 2300},
    "G1B": {"input": 14000, "output_reasoning": 8400},
    "G2": {"input": 8500, "output_reasoning": 3800},
}
G0_ESCALATION_RATE = 0.15


def estimate_run(row_cards: list[dict[str, Any]], cfg: Config) -> dict[str, Any]:
    """Estimate calls and costs without inferring or producing any QA decisions."""
    inspected = [card for card in row_cards if card.get("inspected")]
    g0_records = [
        {
            "source_row": int(card["source_row"]),
            "action": "KEEP",
            "output": {"task_card": None},
        }
        for card in inspected
    ]
    candidate_search = generate_candidates(row_cards, g0_records, cfg)
    bundles = make_bundles(
        [tuple(candidate["rows"]) for candidate in candidate_search["pairs"]],
        cfg.G1_PAIRS_PER_CALL,
    )

    g0_calls = len(inspected)
    g0_escalation_calls = math.ceil(g0_calls * G0_ESCALATION_RATE)
    g1b_calls = len(bundles)
    g2_upper_bound_calls = len(inspected)
    calls = {
        "G0_initial": g0_calls,
        "G0_escalation_estimate": g0_escalation_calls,
        "G1B_candidate_bundles_lower_bound": g1b_calls,
        "G2_upper_bound": g2_upper_bound_calls,
    }
    total_calls = sum(calls.values())
    token_estimates = {
        stage: {
            "calls": calls_count,
            "input": calls_count * DESIGN_TOKEN_ASSUMPTIONS[stage]["input"],
            "output_reasoning": calls_count * DESIGN_TOKEN_ASSUMPTIONS[stage]["output_reasoning"],
        }
        for stage, calls_count in (
            ("G0", g0_calls + g0_escalation_calls),
            ("G1B", g1b_calls),
            ("G2", g2_upper_bound_calls),
        )
    }
    total_tokens = {
        key: sum(item[key] for item in token_estimates.values())
        for key in ("input", "output_reasoning")
    }
    cost = None
    if None not in (cfg.PRICE_INPUT, cfg.PRICE_CACHED_INPUT, cfg.PRICE_OUTPUT):
        # The estimate deliberately assumes no prompt-cache discount.
        cost = (
            total_tokens["input"] * cfg.PRICE_INPUT
            + total_tokens["output_reasoning"] * cfg.PRICE_OUTPUT
        ) / 1_000_000
    return {
        "rows": len(row_cards),
        "inspected_rows": len(inspected),
        "calls": calls,
        "total_calls_estimate": total_calls,
        "candidate_pairs": candidate_search["candidate_count"],
        "candidate_bundles": len(bundles),
        "tokens": {"by_stage": token_estimates, "total": total_tokens},
        "cost_usd_estimate": cost,
        "assumptions": [
            "G0 escalation is estimated at the design baseline of 15%.",
            "G1B uses original Task text and fixed code signals only; G0-generated task cards may add candidates.",
            "G2 calls are an upper bound: G0 non-KEEP and confirmed G1 duplicates reduce actual calls.",
            "Per-call token figures are design estimates, not tokenizer measurements or API usage.",
            "Estimated input cost assumes no prompt-cache discount.",
        ],
    }
