"""Tests du moteur de scoring Future Winner Score."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.scoring import (  # noqa: E402
    PILLAR_WEIGHTS,
    QualitativeInputs,
    RawMetrics,
    RiskInputs,
    compute_score,
    score_balance_sheet,
    score_growth,
)


def _mrvl_metrics() -> RawMetrics:
    """Scénario type MRVL (pédagogique, cf. prompt)."""
    return RawMetrics(
        revenue_growth_yoy_latest_q=24.0,
        revenue_cagr_3y=18.0,
        eps_growth_yoy=31.0,
        gross_margin=63.0,
        gross_margin_yoy_bps=120,
        operating_margin=19.0,
        operating_margin_yoy_bps=150,
        rule_of_40=42.0,
        fcf_margin=18.0,
        fcf_growth_yoy=22.0,
        cash_conversion=0.92,
        net_debt_to_ebitda=1.1,
        interest_coverage=9.8,
        share_count_growth_yoy=1.2,
        valuation_discount_vs_peers_pct=5.0,
        peer_growth_advantage=True,
        upside_vs_consensus_pct=16.0,
        above_50dma=True,
        above_200dma=True,
        relative_strength_strong=True,
        relative_strength_positive=True,
        analyst_eps_revision_90d_pct=6.5,
        net_upgrades=True,
        insider_net_buy_value_180d_usd=0.0,
    )


def test_component_bounds_respected():
    res = compute_score(
        _mrvl_metrics(),
        QualitativeInputs(secular_tailwind_tam=5, moat_quality=5, execution_quality=3),
        RiskInputs(primary_sources_ok=True, data_freshness_days=7),
        confidence=78,
    )
    for name, max_w in PILLAR_WEIGHTS.items():
        assert 0 <= res.component_scores[name] <= max_w, name
    assert abs(res.base_score - sum(res.component_scores.values())) < 1e-6


def test_mrvl_like_is_buy():
    res = compute_score(
        _mrvl_metrics(),
        QualitativeInputs(secular_tailwind_tam=5, moat_quality=5, execution_quality=3),
        RiskInputs(primary_sources_ok=True, data_freshness_days=7),
        confidence=78,
    )
    assert res.final_score >= 80
    assert res.verdict == "BUY"
    assert res.hard_fails == []


def test_growth_bands():
    # 24% YoY -> 7 ; 18% CAGR -> 5 ; 31% EPS -> 6  => 18
    m = RawMetrics(revenue_growth_yoy_latest_q=24, revenue_cagr_3y=18, eps_growth_yoy=31)
    assert score_growth(m) == 18
    # croissance négative => 0 partout
    m2 = RawMetrics(revenue_growth_yoy_latest_q=-5, revenue_cagr_3y=-2, eps_growth_yoy=-10)
    assert score_growth(m2) == 0


def test_growth_falls_back_to_operating_income():
    m = RawMetrics(eps_growth_yoy=None, operating_income_growth_yoy=12)
    # operating_income_growth 12 -> band [(25,6),(10,4)] -> 4
    assert score_growth(m) == 4


def test_balance_sheet_net_cash():
    m = RawMetrics(net_debt_to_ebitda=0.2, interest_coverage=10, share_count_growth_yoy=-1)
    assert score_balance_sheet(m) == 10  # 5 + 2 + 3


def test_missing_data_scores_zero_not_crash():
    res = compute_score(
        RawMetrics(), QualitativeInputs(), RiskInputs(primary_sources_ok=True),
        confidence=10,
    )
    assert res.base_score == 0
    assert res.verdict == "SELL_OR_AVOID"


def test_hard_fail_blocks_buy():
    metrics = _mrvl_metrics()
    # Données trop anciennes => hard fail, BUY interdit
    res = compute_score(
        metrics,
        QualitativeInputs(secular_tailwind_tam=5, moat_quality=6, execution_quality=4),
        RiskInputs(primary_sources_ok=True, data_freshness_days=200),
        confidence=90,
    )
    assert "data_freshness_days>140" in res.hard_fails
    assert res.verdict != "BUY"


def test_severe_flag_forces_sell():
    res = compute_score(
        _mrvl_metrics(),
        QualitativeInputs(secular_tailwind_tam=5, moat_quality=6, execution_quality=4),
        RiskInputs(primary_sources_ok=True, going_concern=True),
        confidence=90,
    )
    assert res.verdict == "SELL_OR_AVOID"


def test_risk_penalty_clamped():
    res = compute_score(
        _mrvl_metrics(),
        QualitativeInputs(secular_tailwind_tam=5, moat_quality=6, execution_quality=4),
        RiskInputs(
            primary_sources_ok=True,
            critical_debt_penalty=-20,
            regulatory_penalty=-20,
        ),
        confidence=90,
    )
    assert res.risk_penalty == -20  # clampé à -20


def test_dilution_hard_fail():
    m = _mrvl_metrics()
    m.share_count_growth_yoy = 8.0  # > 5%
    res = compute_score(
        m,
        QualitativeInputs(secular_tailwind_tam=5, moat_quality=6, execution_quality=4),
        RiskInputs(primary_sources_ok=True),
        confidence=90,
    )
    assert "dilution>5pct_yoy" in res.hard_fails
    assert res.verdict != "BUY"
