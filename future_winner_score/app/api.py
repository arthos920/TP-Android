"""API FastAPI de consultation Future Winner Score.

Endpoints (lecture seule + déclencheurs) conformes au prompt :
    GET  /health
    GET  /runs/latest
    GET  /runs/latest/top20
    GET  /stocks/{ticker}/latest
    GET  /stocks/{ticker}/history
    GET  /alerts/recent
    POST /rescore/{ticker}        (stub : renvoie 501 tant que non câblé au pipeline)
    POST /backfill/sec            (stub)
    POST /backfill/transcripts    (stub)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from .ranking import render_discord_alert, render_telegram_alert
from .scoring import METHOD_VERSION
from .store import store

app = FastAPI(title="Future Winner Score API", version=METHOD_VERSION)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "method_version": METHOD_VERSION,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "has_run": store.latest_run() is not None,
    }


@app.get("/runs/latest")
def runs_latest() -> dict:
    run = store.latest_run()
    if run is None:
        raise HTTPException(404, "Aucun run disponible")
    return run.model_dump()


@app.get("/runs/latest/top20")
def runs_latest_top20() -> dict:
    run = store.latest_run()
    if run is None:
        raise HTTPException(404, "Aucun run disponible")
    return {"run_id": run.run_id, "top20": [e.model_dump() for e in run.top20]}


@app.get("/stocks/{ticker}/latest")
def stock_latest(ticker: str) -> dict:
    report = store.latest_report(ticker)
    if report is None:
        raise HTTPException(404, f"Aucun rapport pour {ticker}")
    return report.model_dump()


@app.get("/stocks/{ticker}/history")
def stock_history(ticker: str) -> dict:
    hist = store.report_history(ticker)
    if not hist:
        raise HTTPException(404, f"Aucun historique pour {ticker}")
    return {"ticker": ticker.upper(), "reports": [r.model_dump() for r in hist]}


@app.get("/alerts/recent")
def alerts_recent(limit: int = 50) -> dict:
    return {"alerts": store.recent_alerts(limit)}


@app.get("/stocks/{ticker}/alert")
def stock_alert(ticker: str) -> dict:
    report = store.latest_report(ticker)
    if report is None:
        raise HTTPException(404, f"Aucun rapport pour {ticker}")
    return {
        "telegram": render_telegram_alert(report),
        "discord": render_discord_alert(report),
    }


# --- Déclencheurs (stubs MVP : à câbler sur Celery/pipeline) ---------------- #
@app.post("/rescore/{ticker}")
def rescore(ticker: str):
    raise HTTPException(501, "Pipeline de rescore non câblé dans le MVP")


@app.post("/backfill/sec")
def backfill_sec():
    raise HTTPException(501, "Backfill SEC non câblé dans le MVP")


@app.post("/backfill/transcripts")
def backfill_transcripts():
    raise HTTPException(501, "Backfill transcripts non câblé dans le MVP")
