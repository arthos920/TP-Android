"""Schémas Pydantic — contrat de sortie JSON de Future Winner Score.

Les clés sont en anglais snake_case (intégration stable) ; le contenu humain
(thèses, bull/bear, alertes) est en français, conformément au prompt.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["BUY", "HOLD", "SELL_OR_AVOID"]
SourceType = Literal[
    "filing", "ir", "transcript", "news", "market_data", "analyst", "insider"
]


class SourceRef(BaseModel):
    source_type: SourceType
    provider: str
    url_or_id: str
    published_or_filed_at: str
    priority_level: int = Field(ge=1, le=3)


class ComponentScores(BaseModel):
    growth_score: float
    profitability_score: float
    cash_flow_score: float
    balance_sheet_score: float
    tam_moat_score: float
    valuation_score: float
    momentum_revisions_score: float


class RawMetricsOut(BaseModel):
    revenue_growth_yoy_latest_q: Optional[float] = None
    revenue_cagr_3y: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    gross_margin_yoy_bps: Optional[float] = None
    operating_margin: Optional[float] = None
    operating_margin_yoy_bps: Optional[float] = None
    fcf_margin: Optional[float] = None
    fcf_growth_yoy: Optional[float] = None
    cash_conversion: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    interest_coverage: Optional[float] = None
    share_count_growth_yoy: Optional[float] = None
    ev_sales_ntm: Optional[float] = None
    pe_forward: Optional[float] = None
    relative_strength_6m: Optional[float] = None
    relative_strength_12m: Optional[float] = None
    analyst_eps_revision_90d_pct: Optional[float] = None
    analyst_revenue_revision_90d_pct: Optional[float] = None
    insider_net_buy_value_180d_usd: Optional[float] = None


class QualitativeSignals(BaseModel):
    tam_thesis_fr: str
    moat_thesis_fr: str
    management_execution_fr: str
    earnings_call_signal_fr: str


class StockReport(BaseModel):
    run_id: str
    run_timestamp_utc: str
    ticker: str
    company_name: str
    isin: Optional[str] = None
    cik: Optional[str] = None
    exchange: str
    country: str
    sector: str
    industry: str
    currency: str
    primary_sources_ok: bool
    data_freshness_days: float
    base_score: float
    risk_penalty: float
    final_score: float
    confidence: float
    verdict: Verdict
    component_scores: ComponentScores
    raw_metrics: RawMetricsOut
    qualitative_signals: QualitativeSignals
    bull_case_fr: list[str]
    bear_case_fr: list[str]
    thesis_summary_fr: str
    why_now_fr: str
    why_not_now_fr: str
    risk_flags: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)


class ScanScope(BaseModel):
    universe_size: int
    eligible_count: int
    scored_count: int
    excluded_count: int


class Top20Entry(BaseModel):
    rank: int
    ticker: str
    company_name: str
    final_score: float
    confidence: float
    verdict: Verdict
    why_now_fr: str
    main_alert_fr: str


class DailyTop20(BaseModel):
    run_id: str
    run_timestamp_utc: str
    scan_scope: ScanScope
    top20: list[Top20Entry]
    market_context_fr: str
    method_version: str
    prompt_hash: str
