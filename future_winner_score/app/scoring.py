"""Future Winner Score — moteur de scoring déterministe.

Ce module est la source de vérité machine du barème décrit dans
``prompts/future_winner_score_prompt.md``. Toute modification du barème doit
être répercutée dans le prompt ET incrémenter ``METHOD_VERSION``.

Le score final est calculé ainsi :

    final_score = clamp(base_score + risk_penalty, 0, 100)

avec ``base_score`` = somme des 7 piliers (sur 100) et ``risk_penalty`` un
malus dans [-20, 0].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

METHOD_VERSION = "fws-1.0.0"

# Poids maximum de chaque pilier (somme = 100).
PILLAR_WEIGHTS = {
    "growth_score": 20,
    "profitability_score": 15,
    "cash_flow_score": 15,
    "balance_sheet_score": 10,
    "tam_moat_score": 15,
    "valuation_score": 10,
    "momentum_revisions_score": 15,
}

BUY_MIN_SCORE = 80
BUY_MIN_CONFIDENCE = 70
HOLD_MIN_SCORE = 60
MAX_DATA_FRESHNESS_DAYS = 140


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Entrées du modèle                                                           #
# --------------------------------------------------------------------------- #
@dataclass
class RawMetrics:
    """Métriques fondamentales / marché normalisées (None = indisponible)."""

    # Croissance
    revenue_growth_yoy_latest_q: Optional[float] = None
    revenue_cagr_3y: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    operating_income_growth_yoy: Optional[float] = None  # repli si EPS non pertinent

    # Profitabilité
    gross_margin: Optional[float] = None
    gross_margin_yoy_bps: Optional[float] = None
    operating_margin: Optional[float] = None
    operating_margin_yoy_bps: Optional[float] = None
    rule_of_40: Optional[float] = None  # growth% + fcf_margin%

    # Cash-flow
    fcf_margin: Optional[float] = None
    fcf_growth_yoy: Optional[float] = None
    cash_conversion: Optional[float] = None  # CFO/net_income ou FCF/EBITDA

    # Bilan
    net_debt_to_ebitda: Optional[float] = None
    interest_coverage: Optional[float] = None
    share_count_growth_yoy: Optional[float] = None

    # Valorisation
    valuation_discount_vs_peers_pct: Optional[float] = None  # >0 = décote
    peer_growth_advantage: Optional[bool] = None  # croissance >= pairs
    upside_vs_consensus_pct: Optional[float] = None

    # Momentum / révisions
    above_50dma: Optional[bool] = None
    above_200dma: Optional[bool] = None
    relative_strength_strong: Optional[bool] = None  # RS forte vs secteur/indice
    relative_strength_positive: Optional[bool] = None
    analyst_eps_revision_90d_pct: Optional[float] = None
    net_upgrades: Optional[bool] = None
    insider_net_buy_value_180d_usd: Optional[float] = None
    insider_significant_buys: Optional[bool] = None  # achats open-market C-level
    insider_massive_unexplained_sells: Optional[bool] = None


@dataclass
class QualitativeInputs:
    """Scores qualitatifs (0..max) issus des filings/IR/transcripts."""

    secular_tailwind_tam: float = 0.0  # /5
    moat_quality: float = 0.0          # /6
    execution_quality: float = 0.0     # /4


@dataclass
class RiskInputs:
    """Drapeaux de risque pour le malus et les hard fails."""

    primary_sources_ok: bool = True
    data_freshness_days: float = 0.0
    going_concern: bool = False
    restatement_material: bool = False
    severe_regulatory_or_accounting_flag: bool = False
    liquidity_ok: bool = True

    # Pénalités graduelles (intensité fournie par l'agent en amont)
    critical_debt_penalty: float = 0.0          # -10..-20
    regulatory_penalty: float = 0.0             # -8..-20
    data_mismatch_penalty: float = 0.0          # -5..-10
    concentration_penalty: float = 0.0          # -3..-10
    euphoric_valuation_penalty: float = 0.0     # -3..-8
    margin_or_guidance_cut_penalty: float = 0.0 # -3..-8
    dilution_penalty: float = 0.0               # -2..-8
    illiquidity_penalty: float = 0.0            # -5 mini


# --------------------------------------------------------------------------- #
# Barème par pilier                                                           #
# --------------------------------------------------------------------------- #
def _band(value: Optional[float], thresholds, default: float = 0.0) -> float:
    """Retourne le 1er score dont le seuil ``>=`` est satisfait.

    ``thresholds`` : liste de tuples (seuil_min, score) triée décroissante.
    """
    if value is None:
        return default
    for threshold, score in thresholds:
        if value >= threshold:
            return score
    return default


def score_growth(m: RawMetrics) -> float:
    # revenue_growth_yoy_latest_q /8
    s1 = _band(m.revenue_growth_yoy_latest_q,
               [(30, 8), (20, 7), (10, 5), (5, 3), (0, 1)], default=0)
    # revenue_cagr_3y /6
    s2 = _band(m.revenue_cagr_3y,
               [(25, 6), (15, 5), (8, 3), (3, 2), (0, 1)], default=0)
    # eps_growth (ou operating_income_growth) /6
    eps = m.eps_growth_yoy if m.eps_growth_yoy is not None else m.operating_income_growth_yoy
    s3 = _band(eps, [(25, 6), (10, 4), (0, 2)], default=0)
    return s1 + s2 + s3


def score_profitability(m: RawMetrics) -> float:
    # gross margin niveau /5 + ajustement trend
    s1 = _band(m.gross_margin, [(60, 5), (45, 4), (30, 3), (15, 2)], default=0)
    if m.gross_margin_yoy_bps is not None and m.gross_margin_yoy_bps < -200:
        s1 = max(0, s1 - 1)
    # operating margin /6 + trend
    s2 = _band(m.operating_margin, [(25, 6), (15, 5), (8, 3), (0, 1)], default=0)
    if m.operating_margin_yoy_bps is not None and m.operating_margin_yoy_bps < -200:
        s2 = max(0, s2 - 1)
    # rule of 40 /4
    s3 = _band(m.rule_of_40, [(40, 4), (30, 3), (20, 2), (10, 1)], default=0)
    return s1 + s2 + s3


def score_cash_flow(m: RawMetrics) -> float:
    s1 = _band(m.fcf_margin, [(20, 7), (10, 5), (5, 3), (0, 1)], default=0)
    s2 = _band(m.fcf_growth_yoy, [(20, 4), (10, 3), (0, 2)], default=0)
    s3 = _band(m.cash_conversion, [(1.0, 4), (0.8, 3), (0.6, 2), (0.4, 1)], default=0)
    return s1 + s2 + s3


def score_balance_sheet(m: RawMetrics) -> float:
    # net_debt_to_ebitda /5 — plus c'est bas, mieux c'est (net cash => très bas/négatif)
    nd = m.net_debt_to_ebitda
    if nd is None:
        s1 = 0.0
    elif nd < 1:
        s1 = 5.0
    elif nd <= 2:
        s1 = 4.0
    elif nd <= 3:
        s1 = 2.0
    elif nd <= 4:
        s1 = 1.0
    else:
        s1 = 0.0
    # interest coverage /2
    s2 = _band(m.interest_coverage, [(8, 2), (4, 1)], default=0)
    # dilution control /3 (share_count_growth_yoy, plus bas = mieux)
    sc = m.share_count_growth_yoy
    if sc is None:
        s3 = 0.0
    elif sc <= 0:
        s3 = 3.0
    elif sc <= 2:
        s3 = 2.0
    elif sc <= 5:
        s3 = 1.0
    else:
        s3 = 0.0
    return s1 + s2 + s3


def score_tam_moat(q: QualitativeInputs) -> float:
    return clamp(q.secular_tailwind_tam, 0, 5) + clamp(q.moat_quality, 0, 6) + clamp(
        q.execution_quality, 0, 4)


def score_valuation(m: RawMetrics) -> float:
    # relative_valuation /6
    disc = m.valuation_discount_vs_peers_pct
    if disc is None:
        s1 = 0.0
    elif disc >= 20:
        s1 = 6.0
    elif disc >= 0:
        s1 = 4.0 if m.peer_growth_advantage else 3.0
    elif disc >= -30:
        s1 = 3.0 if m.peer_growth_advantage else 1.0
    elif disc >= -50:
        s1 = 1.0
    else:
        s1 = 0.0
    # upside vs consensus /4
    up = m.upside_vs_consensus_pct
    if up is None:
        s2 = 0.0
    elif up >= 15:
        s2 = 4.0
    elif up >= 5:
        s2 = 2.0
    elif up >= 0:
        s2 = 1.0
    else:
        s2 = 0.0
    return s1 + s2


def score_momentum_revisions(m: RawMetrics) -> float:
    # price momentum /6
    if m.above_50dma and m.above_200dma and m.relative_strength_strong:
        s1 = 6.0
    elif m.above_200dma and m.relative_strength_positive:
        s1 = 4.0
    elif m.above_50dma or m.above_200dma:
        s1 = 2.0
    else:
        s1 = 0.0
    # analyst revisions /5
    rev = m.analyst_eps_revision_90d_pct
    if rev is None:
        s2 = 0.0
    elif rev > 5 and m.net_upgrades:
        s2 = 5.0
    elif rev > 0:
        s2 = 3.0
    elif rev == 0:
        s2 = 2.0
    else:
        s2 = 0.0
    # insider signal /4
    has_insider_data = (
        m.insider_massive_unexplained_sells is not None
        or m.insider_significant_buys is not None
        or m.insider_net_buy_value_180d_usd is not None
    )
    if m.insider_massive_unexplained_sells:
        s3 = 0.0
    elif m.insider_significant_buys:
        s3 = 4.0
    elif (m.insider_net_buy_value_180d_usd or 0) > 0:
        s3 = 2.0
    elif has_insider_data:
        s3 = 1.0  # données présentes mais neutres
    else:
        s3 = 0.0  # pas de données insider
    return s1 + s2 + s3


# --------------------------------------------------------------------------- #
# Malus de risque & hard fails                                                #
# --------------------------------------------------------------------------- #
def compute_risk_penalty(r: RiskInputs) -> float:
    raw = (
        r.critical_debt_penalty
        + r.regulatory_penalty
        + r.data_mismatch_penalty
        + r.concentration_penalty
        + r.euphoric_valuation_penalty
        + r.margin_or_guidance_cut_penalty
        + r.dilution_penalty
        + r.illiquidity_penalty
    )
    return clamp(raw, -20, 0)


def evaluate_hard_fails(r: RiskInputs, m: RawMetrics) -> list[str]:
    """Retourne la liste des hard fails déclenchés (BUY interdit si non vide)."""
    fails: list[str] = []
    if not r.primary_sources_ok:
        fails.append("primary_sources_ok=false")
    if r.data_freshness_days > MAX_DATA_FRESHNESS_DAYS:
        fails.append(f"data_freshness_days>{MAX_DATA_FRESHNESS_DAYS}")
    if r.going_concern:
        fails.append("going_concern=true")
    if r.restatement_material:
        fails.append("restatement_material=true")
    if r.severe_regulatory_or_accounting_flag:
        fails.append("severe_regulatory_or_accounting_flag=true")
    if (m.net_debt_to_ebitda is not None and m.net_debt_to_ebitda > 4
            and m.fcf_margin is not None and m.fcf_margin < 0):
        fails.append("net_debt>4x_and_fcf_negative")
    if m.share_count_growth_yoy is not None and m.share_count_growth_yoy > 5:
        fails.append("dilution>5pct_yoy")
    if not r.liquidity_ok:
        fails.append("liquidity_below_rules")
    return fails


# --------------------------------------------------------------------------- #
# Résultat & orchestration                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class ScoreResult:
    component_scores: dict = field(default_factory=dict)
    base_score: float = 0.0
    risk_penalty: float = 0.0
    final_score: float = 0.0
    confidence: float = 0.0
    verdict: str = "SELL_OR_AVOID"
    hard_fails: list = field(default_factory=list)
    method_version: str = METHOD_VERSION


def decide_verdict(final_score: float, confidence: float, hard_fails: list[str]) -> str:
    if final_score >= BUY_MIN_SCORE and confidence >= BUY_MIN_CONFIDENCE and not hard_fails:
        return "BUY"
    if final_score >= HOLD_MIN_SCORE:
        return "HOLD"
    # En dessous de 60 : SELL_OR_AVOID. Les hard fails sévères plafonnent aussi ici.
    return "SELL_OR_AVOID"


def compute_score(
    metrics: RawMetrics,
    qualitative: QualitativeInputs,
    risk: RiskInputs,
    confidence: float,
) -> ScoreResult:
    components = {
        "growth_score": round(score_growth(metrics), 2),
        "profitability_score": round(score_profitability(metrics), 2),
        "cash_flow_score": round(score_cash_flow(metrics), 2),
        "balance_sheet_score": round(score_balance_sheet(metrics), 2),
        "tam_moat_score": round(score_tam_moat(qualitative), 2),
        "valuation_score": round(score_valuation(metrics), 2),
        "momentum_revisions_score": round(score_momentum_revisions(metrics), 2),
    }
    base_score = round(sum(components.values()), 2)
    risk_penalty = compute_risk_penalty(risk)
    final_score = clamp(base_score + risk_penalty, 0, 100)
    hard_fails = evaluate_hard_fails(risk, metrics)

    verdict = decide_verdict(final_score, confidence, hard_fails)
    # Un hard fail plafonne à HOLD au mieux ; gravité réglementaire/dette => SELL.
    if hard_fails and verdict == "BUY":
        verdict = "HOLD"
    severe = (
        risk.going_concern
        or risk.restatement_material
        or risk.severe_regulatory_or_accounting_flag
    )
    if severe:
        verdict = "SELL_OR_AVOID"

    return ScoreResult(
        component_scores=components,
        base_score=base_score,
        risk_penalty=risk_penalty,
        final_score=round(final_score, 2),
        confidence=round(confidence, 2),
        verdict=verdict,
        hard_fails=hard_fails,
    )
