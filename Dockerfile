FROM python:3.12-slim AS builder
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip wheel --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim AS runtime
WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

COPY . .

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; u=urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3); sys.exit(0 if u.status==200 else 1)"

CMD ["sh", "/app/entrypoint.sh"]