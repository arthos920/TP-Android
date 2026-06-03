# Future Winner Score — image API (MVP)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY prompts/ ./prompts/
COPY demo.py .

EXPOSE 8000

# API de consultation (lecture seule + déclencheurs stub)
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
