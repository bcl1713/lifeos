FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN addgroup --system lifeos && adduser --system --ingroup lifeos lifeos

COPY pyproject.toml README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY docker-entrypoint.sh /usr/local/bin/lifeos-entrypoint

RUN pip install --no-cache-dir . && chmod 755 /usr/local/bin/lifeos-entrypoint && mkdir -p /data && chown -R lifeos:lifeos /app /data

USER root
ENTRYPOINT ["/usr/local/bin/lifeos-entrypoint"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["uvicorn", "lifeos.main:app", "--host", "0.0.0.0", "--port", "8000"]
