"""Tests du classement Top 20 et du rendu des alertes."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import (  # noqa: E402
    ComponentScores,
    QualitativeSignals,
    RawMetricsOut,
    StockReport,
)
from app.ranking import build_top20, render_telegram_alert  # noqa: E402


def _report(ticker: str, score: float, conf: float, verdict: str) -> StockReport:
    return StockReport(
        run_id="run-1",
        run_timestamp_utc="2026-06-03T01:30:00Z",
        ticker=ticker,
        company_name=f"{ticker} Inc",
        exchange="NASDAQ",
        country="US",
        sector="Tech",
        industry="Software",
        currency="USD",
        primary_sources_ok=True,
        data_freshness_days=5,
        base_score=score,
        risk_penalty=0,
        final_score=score,
        confidence=conf,
        verdict=verdict,
        component_scores=ComponentScores(
            growth_score=0, profitability_score=0, cash_flow_score=0,
            balance_sheet_score=0, tam_moat_score=0, valuation_score=0,
            momentum_revisions_score=0,
        ),
        raw_metrics=RawMetricsOut(analyst_eps_revision_90d_pct=3.0),
        qualitative_signals=QualitativeSignals(
            tam_thesis_fr="x", moat_thesis_fr="x",
            management_execution_fr="x", earnings_call_signal_fr="x",
        ),
        bull_case_fr=["Catalyseur A", "Catalyseur B"],
        bear_case_fr=["Risque A", "Risque B"],
        thesis_summary_fr="Résumé",
        why_now_fr="Momentum + révisions",
        why_not_now_fr="Valorisation",
        alerts=["Entrée watchlist"],
    )


def test_top20_sorted_and_excludes_avoid():
    reports = [
        _report("AAA", 85, 80, "BUY"),
        _report("BBB", 90, 75, "BUY"),
        _report("CCC", 50, 40, "SELL_OR_AVOID"),  # exclu
        _report("DDD", 70, 60, "HOLD"),
    ]
    top = build_top20(
        reports, "run-1", "2026-06-03T01:30:00Z",
        universe_size=500, eligible_count=400,
        method_version="fws-1.0.0", prompt_hash="abc",
    )
    tickers = [e.ticker for e in top.top20]
    assert tickers == ["BBB", "AAA", "DDD"]  # trié par score desc, AVOID exclu
    assert top.top20[0].rank == 1
    assert top.scan_scope.scored_count == 4


def test_tie_breaker_uses_confidence():
    reports = [
        _report("LOW", 80, 70, "BUY"),
        _report("HIGH", 80, 90, "BUY"),
    ]
    top = build_top20(
        reports, "r", "t", universe_size=10, eligible_count=10,
        method_version="v", prompt_hash="h",
    )
    assert [e.ticker for e in top.top20] == ["HIGH", "LOW"]


def test_telegram_alert_contains_ticker_and_score():
    r = _report("MRVL", 80, 78, "BUY")
    msg = render_telegram_alert(r)
    assert "MRVL" in msg
    assert "80/100" in msg
    assert "Verdict BUY" in msg
