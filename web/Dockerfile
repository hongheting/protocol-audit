# =============================================================================
# Jassy 主写 — 此文件以 Jassy King 版本为准；下方为对齐说明（勿另起冲突版）。
# 对齐约定：PORT 默认 8080；绑定 0.0.0.0；子域 protocol.jassyhong.top；
# Basic auth 由 app.py 读 PROTOCOL_AUDIT_DEMO_PASSWORD（ACA secret 注入）。
# 建议（未改 CMD，避免抢写）：HEALTHCHECK / gunicorn 绑定读 $PORT；
# LLM 审查较久时可把 --timeout 提到 300；可选 entrypoint 仿 refcheck 写 /run/secrets。
# =============================================================================
# ProtocolAudit Beta — Flask UI
# Build from protocol-audit root:
#   docker build --platform linux/amd64 -f web/Dockerfile -t protocol-audit-beta:0.1.3.3 .
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PROTOCOL_AUDIT_VERSION=0.1.3.3 \
    PORT=8080

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /app/requirements.txt gunicorn>=22.0

COPY protocol_audit /app/protocol_audit
COPY web /app/web
COPY audit-request.v0.2.schema.json audit-report.v0.2.schema.json parse-preview.v0.2.schema.json design-extract.v0.2.schema.json /app/

RUN mkdir -p /app/web/jobs /tmp/protocol-audit-jobs \
 && find /app -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true \
 && rm -rf /app/web/jobs/* \
 && useradd -m -u 10001 appuser \
 && chown -R appuser:appuser /app /tmp/protocol-audit-jobs

USER appuser
WORKDIR /app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT','8080'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=3)"

# Bind 0.0.0.0 for Container Apps; jobs dir under web/ as app expects
CMD ["gunicorn", "-b", "0.0.0.0:8080", "-w", "2", "-k", "gthread", "--threads", "4", "--timeout", "300", "--keep-alive", "5", "web.app:app"]
