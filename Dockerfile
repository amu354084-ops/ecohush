FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  ERP_HOST=0.0.0.0 \
  ERP_SERVER_PORT=1833

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
  pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
COPY config ./config
COPY alembic.ini pyproject.toml requirements.txt ./

EXPOSE 1833

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:1833/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "1833"]
