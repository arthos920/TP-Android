"""Stockage en mémoire pour le MVP runnable.

En production, remplacer par la couche PostgreSQL (voir ``db.py``). Cette
implémentation permet de faire tourner l'API et les tests sans base.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Optional

from .models import DailyTop20, StockReport


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: list[DailyTop20] = []
        # ticker -> liste de rapports (historique)
        self._reports: dict[str, list[StockReport]] = defaultdict(list)
        self._alerts: list[dict] = []

    def save_run(self, run: DailyTop20, reports: list[StockReport]) -> None:
        with self._lock:
            self._runs.append(run)
            for r in reports:
                self._reports[r.ticker.upper()].append(r)

    def latest_run(self) -> Optional[DailyTop20]:
        return self._runs[-1] if self._runs else None

    def latest_report(self, ticker: str) -> Optional[StockReport]:
        hist = self._reports.get(ticker.upper())
        return hist[-1] if hist else None

    def report_history(self, ticker: str) -> list[StockReport]:
        return list(self._reports.get(ticker.upper(), []))

    def record_alert(self, alert: dict) -> None:
        with self._lock:
            self._alerts.append(alert)

    def recent_alerts(self, limit: int = 50) -> list[dict]:
        return self._alerts[-limit:]


store = InMemoryStore()
