FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    FLASK_APP=hyprprem

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hyprprem ./hyprprem
COPY run.py LICENSE CHANGELOG.md ./

RUN useradd --create-home --uid 1000 hyprprem \
    && mkdir -p /data \
    && chown -R hyprprem:hyprprem /data /app
USER hyprprem

VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# One worker plus threads, on purpose: the background worker thread must start
# once, and SQLite is happiest with a single writing process.
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--timeout", "90", \
     "--access-logfile", "-", "--bind", "0.0.0.0:8000", "hyprprem:create_app()"]
