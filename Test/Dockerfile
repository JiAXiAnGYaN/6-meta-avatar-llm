FROM python:3.10-slim-bookworm
WORKDIR /app
RUN apt-get update&&apt-get install -y --no-install-recommends ca-certificates libgl1 libegl1 libgles2 libglib2.0-0 libgomp1&&rm -rf /var/lib/apt/lists/*
COPY backend_python/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend_python/main.py /app/main.py
COPY backend_python/models /app/models
COPY backend_python/duui /app/duui
RUN useradd -m app&&mkdir -p /data/models /app/.matplotlib-cache&&chown -R app:app /app /data/models
USER app
ENV META_AVATAR_HOST=0.0.0.0
ENV META_AVATAR_PORT=9714
ENV META_AVATAR_OUTPUT_DIR=/data/models
ENV MPLCONFIGDIR=/app/.matplotlib-cache
EXPOSE 9714
VOLUME ["/data/models"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python","-c","from urllib.request import urlopen;urlopen('http://127.0.0.1:9714/api/health',timeout=3)"]
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","9714","--workers","1"]
