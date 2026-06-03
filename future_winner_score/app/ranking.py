"""Classement Top 20 et rendu des alertes Telegram / Discord."""

from __future__ import annotations

from .models import DailyTop20, ScanScope, StockReport, Top20Entry


def _tie_breaker_key(r: StockReport):
    """Tri principal: final_score desc, puis confidence desc, puis révisions,
    puis liquidité implicite via fraîcheur des données (plus récent = mieux)."""
    rev = r.raw_metrics.analyst_eps_revision_90d_pct or 0.0
    return (
        -r.final_score,
        -r.confidence,
        -rev,
        r.data_freshness_days,
    )


def build_top20(
    reports: list[StockReport],
    run_id: str,
    run_timestamp_utc: str,
    universe_size: int,
    eligible_count: int,
    method_version: str,
    prompt_hash: str,
    market_context_fr: str = "",
    limit: int = 20,
) -> DailyTop20:
    """Construit l'objet daily_top20.

    Conforme au prompt : si moins de `limit` titres sont réellement
    convaincants (verdict != SELL_OR_AVOID), on en retourne moins.
    """
    convincing = [r for r in reports if r.verdict != "SELL_OR_AVOID"]
    ordered = sorted(convincing, key=_tie_breaker_key)[:limit]

    top20 = [
        Top20Entry(
            rank=i + 1,
            ticker=r.ticker,
            company_name=r.company_name,
            final_score=r.final_score,
            confidence=r.confidence,
            verdict=r.verdict,
            why_now_fr=r.why_now_fr,
            main_alert_fr=(r.alerts[0] if r.alerts else r.thesis_summary_fr),
        )
        for i, r in enumerate(ordered)
    ]

    return DailyTop20(
        run_id=run_id,
        run_timestamp_utc=run_timestamp_utc,
        scan_scope=ScanScope(
            universe_size=universe_size,
            eligible_count=eligible_count,
            scored_count=len(reports),
            excluded_count=max(0, eligible_count - len(reports)),
        ),
        top20=top20,
        market_context_fr=market_context_fr,
        method_version=method_version,
        prompt_hash=prompt_hash,
    )


def render_telegram_alert(r: StockReport) -> str:
    providers = [s.provider for s in r.source_refs][:3]
    bull = (r.bull_case_fr + ["", ""])[:2]
    bear = (r.bear_case_fr + ["", ""])[:2]
    return (
        f"🚨 Future Winner Score | {r.ticker} | Score {r.final_score:.0f}/100 | "
        f"Verdict {r.verdict}\n"
        f"Pourquoi maintenant : {r.why_now_fr}\n"
        f"Catalyseurs : {bull[0]} | {bull[1]}\n"
        f"Risques : {bear[0]} | {bear[1]}\n"
        f"Confiance : {r.confidence:.0f}/100\n"
        f"Sources clés : {', '.join(providers)}"
    )


def render_discord_alert(r: StockReport) -> str:
    bull = (r.bull_case_fr + ["", ""])[:2]
    bear = (r.bear_case_fr + ["", ""])[:2]
    return (
        f"**Future Winner Score** — **{r.ticker}** — **{r.final_score:.0f}/100** — "
        f"**{r.verdict}**\n"
        f"**Pourquoi maintenant :** {r.why_now_fr}\n"
        f"**Bull case :** {bull[0]} ; {bull[1]}\n"
        f"**Bear case :** {bear[0]} ; {bear[1]}\n"
        f"**Confiance :** {r.confidence:.0f}/100"
    )
