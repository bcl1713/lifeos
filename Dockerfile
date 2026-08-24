FROM python:3.12-slim AS runtime

ARG LIFEOS_BUILD_VERSION=local-dev
ARG LIFEOS_BUILD_REVISION=unknown
ARG LIFEOS_PACKAGE_VERSION=0.0.0+local

LABEL org.opencontainers.image.version=$LIFEOS_BUILD_VERSION \
    org.opencontainers.image.revision=$LIFEOS_BUILD_REVISION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN addgroup --system lifeos && adduser --system --ingroup lifeos lifeos

COPY pyproject.toml README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/lifeos-entrypoint

RUN python scripts/embed_build_metadata.py \
        --package-version "$LIFEOS_PACKAGE_VERSION" \
        --build-version "$LIFEOS_BUILD_VERSION" \
        --build-revision "$LIFEOS_BUILD_REVISION" \
    && pip install --no-cache-dir . \
    && chmod 755 /usr/local/bin/lifeos-entrypoint \
    && mkdir -p /data \
    && chown -R lifeos:lifeos /app /data

USER root
ENTRYPOINT ["/usr/local/bin/lifeos-entrypoint"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["uvicorn", "lifeos.main:app", "--host", "0.0.0.0", "--port", "8000"]
