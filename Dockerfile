# PostgreSQL client tools for in-app backups.
# The VPS cannot reach apt mirrors during the build, so pg_dump is taken from the
# official Debian-based postgres image (same major version as the database, glibc
# like python:slim). The Alpine build used before is linked against musl and cannot
# run here, which made "Создать и скачать копию" fail with HTTP 500.
FROM postgres:16-bookworm AS pgclient
RUN set -eu; \
  mkdir -p /opt/pgclient/bin /opt/pgclient/lib; \
  for tool in pg_dump pg_restore; do cp "/usr/lib/postgresql/16/bin/$tool" /opt/pgclient/bin/; done; \
  for tool in pg_dump pg_restore; do ldd "/usr/lib/postgresql/16/bin/$tool"; done \
    | awk '/=> \// {print $3}' | sort -u \
    | grep -vE '/(libc|libm|libdl|libpthread|librt|ld-linux[^/]*)\.so' \
    | xargs -r -I{} cp -L {} /opt/pgclient/lib/

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  ERP_HOST=0.0.0.0 \
  ERP_SERVER_PORT=1833

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
  pip install --no-cache-dir -r requirements.txt

COPY --from=pgclient /opt/pgclient /opt/pgclient
# Small wrappers keep the bundled libraries private to pg_dump/pg_restore.
# The build stops here if the tools cannot start, so a broken image is never deployed.
RUN set -eu; \
  for tool in pg_dump pg_restore; do \
    printf '#!/bin/sh\nLD_LIBRARY_PATH=/opt/pgclient/lib exec /opt/pgclient/bin/%s "$@"\n' "$tool" > "/usr/local/bin/$tool"; \
    chmod 755 "/usr/local/bin/$tool"; \
  done; \
  pg_dump --version; \
  pg_restore --version

COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
COPY config ./config
COPY alembic.ini pyproject.toml requirements.txt ./

EXPOSE 1833

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:1833/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "1833"]
