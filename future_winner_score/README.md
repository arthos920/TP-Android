# Future Winner Score

Moteur d'aide à la décision actions : scanne chaque nuit un univers d'actions
US et globales, calcule un **score 0–100**, produit une **watchlist Top 20** et
émet des verdicts **BUY / HOLD / SELL_OR_AVOID**, le tout traçable jusqu'aux
sources primaires.

> ⚠️ Outil d'aide à la décision, **pas un broker** et **pas un conseil
> d'investissement**. Aucun ordre n'est exécuté.

Ce dossier contient le **MVP** : moteur de scoring déterministe + contrat JSON
+ classement + alertes + API de consultation. Les connecteurs de données
(SEC, IR, FMP, Alpha Vantage, Polygon…) et l'orchestration Celery sont
spécifiés mais laissés en V2 (voir [Limites](#limites--zones-v2)).

## Contenu

| Fichier | Rôle |
|---|---|
| `prompts/future_winner_score_prompt.md` | Prompt agent Claude (source de vérité humaine) |
| `app/scoring.py` | **Moteur de scoring déterministe** (source de vérité machine du barème) |
| `app/models.py` | Schémas Pydantic — contrat de sortie JSON |
| `app/ranking.py` | Classement Top 20 + rendu alertes Telegram/Discord |
| `app/db.py` | Modèle PostgreSQL (12 tables, SQLAlchemy) |
| `app/store.py` | Stockage en mémoire (MVP runnable sans base) |
| `app/api.py` | API FastAPI de consultation |
| `demo.py` | Démo bout-en-bout (scoring → JSON → Top 20 → alertes) |
| `tests/` | Tests unitaires (scoring, hard fails, classement) |

## Démarrage rapide

```bash
cd future_winner_score
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python demo.py            # démo bout-en-bout
python -m pytest tests/   # tests
uvicorn app.api:app --reload   # API sur http://localhost:8000/docs
```

Ou via Docker : `docker compose up --build`.

## Modèle de scoring

`final_score = clamp(base_score + risk_penalty, 0, 100)`

`base_score` = somme de 7 piliers (sur 100) :

| Pilier | Poids | Mesures |
|---|---:|---|
| `growth_score` | 20 | croissance CA T, CAGR 3 ans, EPS/EBIT |
| `profitability_score` | 15 | marge brute, marge opé, Rule of 40 |
| `cash_flow_score` | 15 | marge FCF, croissance FCF, conversion cash |
| `balance_sheet_score` | 10 | net debt/EBITDA, couverture intérêts, dilution |
| `tam_moat_score` | 15 | TAM, moat, qualité d'exécution (qualitatif vérifié) |
| `valuation_score` | 10 | valorisation relative, upside vs consensus |
| `momentum_revisions_score` | 15 | momentum prix, révisions analystes, insiders |

`risk_penalty` ∈ [-20, 0] : dette critique, red flags réglementaires, mismatch
de données, concentration client, valorisation euphorique, coupe de marge/guidance,
dilution, illiquidité.

### Hard fails (BUY interdit même avec un bon score)

`primary_sources_ok=false`, `data_freshness_days > 140`, going concern,
restatement matériel, flag réglementaire/comptable sévère,
`net_debt/EBITDA > 4` **et** FCF négatif, dilution > 5 % YoY, illiquidité.

### Verdicts

- **BUY** : `final_score ≥ 80` **et** `confidence ≥ 70` **et** aucun hard fail
- **HOLD** : `60 ≤ final_score < 80`, ou confiance moyenne, ou risques modérés
- **SELL_OR_AVOID** : `final_score < 60`, ou hard fail sévère

## Hiérarchie des sources (stricte)

1. **Niveau 1 — référence** : SEC EDGAR (10-K/10-Q/8-K/20-F/40-F/6-K, XBRL,
   Forms 3/4/5), site IR officiel, earnings releases/decks/transcripts.
2. **Niveau 2 — premium licencié** : Reuters, Bloomberg, fils PR autorisés.
3. **Niveau 3 — normalisation/couverture** : FMP, Polygon/Massive, Alpha Vantage
   (Yahoo Finance en simple sanity-check).

Le niveau 1 prime toujours ; tout conflit est signalé, jamais deviné ; chaque
affirmation porte un `source_refs` avec `priority_level`.

## Architecture cible

`Python 3.11 + FastAPI` (API) · `PostgreSQL` (+`jsonb`) · `Redis` (cache/queues)
· `Celery + Beat` (un seul scheduler) · `Docker Compose` · `Claude API / Agent
SDK` pour la synthèse qualitative · notifications Telegram / Discord.

### Cadence nocturne (UTC)

| Heure | Job |
|---|---|
| 20:00 | refresh univers / symbol master |
| 21:00 | prix EOD régions clôturées |
| 22:30 | US close, news, révisions, insiders |
| 23:00–01:00 | ingestion IR after-close, 8-K, transcripts |
| 01:15 | scoring complet |
| 01:30 | Top 20 + JSON + alertes |
| 07:15 | backfill / réconciliation bulk SEC |

> SEC : respecter le fair-access (**≤ 10 req/s**, **User-Agent déclaré**). Les
> ZIP bulk sont republiés vers ~3:00 a.m. ET → run principal sur flux temps
> réel + IR + APIs, réconciliation bulk plus tard.

## Limites & zones V2

- **Connecteurs de données** (SEC/IR/FMP/AlphaVantage/Polygon) et NLP earnings
  call : **spécifiés, non implémentés** dans le MVP.
- **Orchestration Celery** et persistance PostgreSQL : schéma fourni, câblage V2.
- **Sous-modèles sectoriels** (banques, assureurs, REITs, biotech pré-revenue) :
  plafonner le verdict à HOLD tant que non implémentés.
- **Couverture globale** non homogène sans connecteurs de filings locaux hors SEC.
- **API Claude + JSON strict** : Structured Outputs ⇒ **pas de citations
  natives** → traçabilité via `source_refs`.
- La synthèse qualitative (`tam_moat`, thèses, bull/bear) est produite par
  l'agent ; le moteur ne fait que le **quantitatif déterministe** + l'agrégation.

## Checklist de déploiement (production)

- [ ] Secrets en variables d'env / vault (jamais committés)
- [ ] `SEC_USER_AGENT` déclaré + rate-limit ≤ 10 req/s
- [ ] Un **seul** Celery Beat scheduler
- [ ] Backups PostgreSQL + partition temporelle des grosses tables
- [ ] Logs structurés JSON, retries, dead-letter queue
- [ ] `method_version` + `prompt_hash` journalisés à chaque run
- [ ] Backtests (precision@20, hit_rate, excess return) avant d'élargir l'univers
- [ ] Garde-fous faux positifs : ≥ 2 familles de preuves pour un BUY fort
