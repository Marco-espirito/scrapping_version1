FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    JOBAPPLY_DATA_DIR=/app/data \
    SCRAPER_HEADLESS=true

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY data/*.example.json ./data/
RUN cp data/profil.example.json data/profil.json \
    && cp data/recherches.example.json data/recherches.json \
    && cp data/candidat.example.json data/candidat.json

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]

