FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    JOBAPPLY_DATA_DIR=/app/data \
    SCRAPER_HEADLESS=true \
    CHROMIUM_NO_SANDBOX=true \
    PORT=8000

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY data/*.example.json ./default-data/

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/api/health', timeout=3)"

CMD ["sh", "-c", "mkdir -p \"$JOBAPPLY_DATA_DIR\"; for name in candidat profil recherches; do test -f \"$JOBAPPLY_DATA_DIR/$name.json\" || cp \"/app/default-data/$name.example.json\" \"$JOBAPPLY_DATA_DIR/$name.json\"; done; exec uvicorn main:app --app-dir backend --host 0.0.0.0 --port \"${PORT:-8000}\""]
