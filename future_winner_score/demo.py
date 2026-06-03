"""Démo de bout en bout : scoring -> rapport JSON -> Top 20 -> alertes.

Usage : python demo.py
Aucune dépendance réseau ; données d'exemple en dur (pédagogique, pas une reco).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import (
    ComponentScores,
    QualitativeSignals,
    RawMetricsOut,
    SourceRef,
    StockReport,
)
from app.ranking import build_top20, render_discord_alert, render_telegram_alert
from app.scoring import (
    METHOD_VERSION,
    QualitativeInputs,
    RawMetrics,
    RiskInputs,
    compute_score,
)


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()

    metrics = RawMetrics(
        revenue_growth_yoy_latest_q=24.0, revenue_cagr_3y=18.0, eps_growth_yoy=31.0,
        gross_margin=63.0, gross_margin_yoy_bps=120, operating_margin=19.0,
        operating_margin_yoy_bps=150, rule_of_40=42.0, fcf_margin=18.0,
        fcf_growth_yoy=22.0, cash_conversion=0.92, net_debt_to_ebitda=1.1,
        interest_coverage=9.8, share_count_growth_yoy=1.2,
        valuation_discount_vs_peers_pct=5.0, peer_growth_advantage=True,
        upside_vs_consensus_pct=16.0, above_50dma=True, above_200dma=True,
        relative_strength_strong=True, relative_strength_positive=True,
        analyst_eps_revision_90d_pct=6.5, net_upgrades=True,
        insider_net_buy_value_180d_usd=0.0,
    )
    qual = QualitativeInputs(secular_tailwind_tam=5, moat_quality=5, execution_quality=3)
    risk = RiskInputs(primary_sources_ok=True, data_freshness_days=7,
                      euphoric_valuation_penalty=-6)

    res = compute_score(metrics, qual, risk, confidence=78)

    report = StockReport(
        run_id=now, run_timestamp_utc=now, ticker="MRVL",
        company_name="Marvell Technology", exchange="NASDAQ", country="US",
        sector="Semiconductors", industry="Data infrastructure semiconductors",
        currency="USD", primary_sources_ok=True, data_freshness_days=7,
        base_score=res.base_score, risk_penalty=res.risk_penalty,
        final_score=res.final_score, confidence=res.confidence, verdict=res.verdict,
        component_scores=ComponentScores(**res.component_scores),
        raw_metrics=RawMetricsOut(
            revenue_growth_yoy_latest_q=24.0, revenue_cagr_3y=18.0, eps_growth_yoy=31.0,
            gross_margin=63.0, operating_margin=19.0, fcf_margin=18.0,
            net_debt_to_ebitda=1.1, analyst_eps_revision_90d_pct=6.5,
        ),
        qualitative_signals=QualitativeSignals(
            tam_thesis_fr="Exposition forte aux dépenses IA et data center.",
            moat_thesis_fr="Design wins et coûts de changement élevés.",
            management_execution_fr="Exécution crédible, dépendante du ramp produit.",
            earnings_call_signal_fr="Q&A constructive, ton positif mesuré.",
        ),
        bull_case_fr=[
            "Accélération durable du data center et de l'IA",
            "Expansion de marge liée au mix produit",
            "Révisions d'estimations encore trop basses",
        ],
        bear_case_fr=[
            "Valorisation déjà tendue",
            "Concentration clients hyperscalers",
            "Décalage de ramp ou digestion des dépenses cloud",
        ],
        thesis_summary_fr="Croissance, marge et révisions positives soutenues par un "
        "narratif IA crédible ; sensible à la valorisation.",
        why_now_fr="Révisions 90 jours positives et momentum relatif fort.",
        why_not_now_fr="La valorisation laisse moins de marge d'erreur.",
        risk_flags=["valuation_premium", "customer_concentration"],
        alerts=["Score au-dessus de 80, entrée possible en watchlist BUY"],
        source_refs=[
            SourceRef(source_type="filing", provider="SEC",
                      url_or_id="latest_10Q", published_or_filed_at="latest",
                      priority_level=1),
            SourceRef(source_type="transcript", provider="IR_or_FMP",
                      url_or_id="latest_call", published_or_filed_at="latest",
                      priority_level=1),
        ],
    )

    top = build_top20(
        [report], run_id=now, run_timestamp_utc=now, universe_size=500,
        eligible_count=480, method_version=METHOD_VERSION, prompt_hash="demo",
        market_context_fr="Marché porté par le thème IA / data center.",
    )

    print("=== STOCK REPORT ===")
    print(report.model_dump_json(indent=2))
    print("\n=== DAILY TOP20 ===")
    print(top.model_dump_json(indent=2))
    print("\n=== ALERTE TELEGRAM ===")
    print(render_telegram_alert(report))
    print("\n=== ALERTE DISCORD ===")
    print(render_discord_alert(report))


if __name__ == "__main__":
    main()
