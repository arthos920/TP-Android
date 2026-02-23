# ============================================================
# appium-mcp-runner  —  image autonome offline
# ============================================================
# Build (en ligne) :  docker build -t appium-mcp-runner .
# Export (offline) :  docker save appium-mcp-runner | gzip > appium-mcp-runner.tar.gz
# Import (offline) :  docker load -i appium-mcp-runner.tar.gz
# ============================================================
#
# Architecture :
#   CONTAINER                         HOST (Windows)
#   ─────────────────────────────     ─────────────────────────
#   Python runner                     Appium Server :4723
#     └─ subprocess: node (stdio)       └─ ADB → devices USB
#          appium-mcp
#            └─ HTTP → host.docker.internal:4723
#
# Variables obligatoires au run :
#   DEVICE_1_ID          serial ADB du 1er device réel
#   DEVICE_2_ID          serial ADB du 2ème device réel (optionnel)
#   LLM_API_KEY          clé API ou "no-key" si LLM local
#   LLM_BASE_URL         URL du LLM (ex: http://host.docker.internal:11434/v1)
#   APPIUM_SERVER_URL    (défaut: http://host.docker.internal:4723)
# ============================================================

FROM node:20-slim AS base

# ── Dépendances système ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Répertoire de travail ────────────────────────────────────
WORKDIR /app

# ── appium-mcp : copier dist/ + node_modules (déjà buildés) ─
# On ne rebuilde pas (offline), on copie l'artefact déjà construit.
COPY appium-mcp/dist/       ./appium-mcp/dist/
COPY appium-mcp/package.json ./appium-mcp/package.json
COPY appium-mcp/node_modules/ ./appium-mcp/node_modules/

# ── Python : installer les dépendances ──────────────────────
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

# ── Scripts Python ───────────────────────────────────────────
COPY script_jira_appium_v2.py   ./
COPY script_test_settings.py    ./
COPY capabilities.json          ./

# ── Dossier screenshots (monté en volume au run) ────────────
RUN mkdir -p /app/screenshots

# ── Variables d'environnement par défaut ────────────────────
ENV APPIUM_MCP_DIR=/app/appium-mcp \
    SCREENSHOTS_DIR=/app/screenshots \
    APPIUM_SERVER_URL=http://host.docker.internal:4723 \
    DEVICE_1_ID=change-me \
    DEVICE_2_ID="" \
    LLM_API_KEY=no-key \
    LLM_BASE_URL=http://host.docker.internal:11434/v1 \
    LLM_MODEL=gpt-4o-mini \
    JIRA_MCP_URL=http://host.docker.internal:9000/mcp \
    TICKET_KEY=XXXX-0001 \
    APP_PACKAGE=com.android.settings \
    APP_ACTIVITY=.Settings \
    MAX_TURNS_PER_DRIVER=30 \
    TOOL_TIMEOUT_S=90 \
    NO_UI=1

# ── Point d'entrée ───────────────────────────────────────────
# Par défaut : test Settings déterministe (sans LLM requis)
# Pour le runner complet : docker run ... python3 script_jira_appium_v2.py
CMD ["python3", "script_test_settings.py"]
