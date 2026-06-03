"""Modèle de données PostgreSQL (SQLAlchemy) — blueprint de persistance.

Reprend les 12 tables minimales du prompt. Les payloads bruts sont stockés en
``JSONB`` pour conserver la traçabilité source. Ce module définit le schéma ;
le câblage du pipeline d'ingestion est laissé en V2.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    company_name: Mapped[str] = mapped_column(String(256))
    cik: Mapped[str | None] = mapped_column(String(16), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Price(Base):
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Financial(Base):
    __tablename__ = "financials"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    period_end: Mapped[datetime] = mapped_column(Date, index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    cfo: Mapped[float | None] = mapped_column(Float, nullable=True)
    capex: Mapped[float | None] = mapped_column(Float, nullable=True)
    fcf: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_out: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Filing(Base):
    __tablename__ = "filings"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    form_type: Mapped[str] = mapped_column(String(16))
    accession_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    filing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    items: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    call_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prepared_remarks_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    qa_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    nlp_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class News(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AnalystRevision(Base):
    __tablename__ = "analyst_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    as_of_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    firm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rating_old: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rating_new: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pt_old: Mapped[float | None] = mapped_column(Float, nullable=True)
    pt_new: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_fy1_old: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_fy1_new: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_fy1_old: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_fy1_new: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class InsiderTrade(Base):
    __tablename__ = "insider_trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trade_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    insider_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    insider_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transaction_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ownership_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    filing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ScoreRun(Base):
    __tablename__ = "score_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    universe_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eligible_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class StockScore(Base):
    __tablename__ = "stock_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("score_runs.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    base_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    component_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metrics_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rationale_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("score_runs.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("score_runs.id"), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
