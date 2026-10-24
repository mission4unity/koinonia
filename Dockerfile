FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 koinonia && mkdir /data && chown koinonia /data
WORKDIR /app
COPY run.py ./
COPY koinonia ./koinonia
ENV KOINONIA_OUTBOX=/data/outbox KOINONIA_UPLOADS=/data/uploads PYTHONUNBUFFERED=1
USER koinonia
VOLUME /data
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8080", "--db", "/data/koinonia.db"]
