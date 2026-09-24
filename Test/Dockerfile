FROM python:3.10-slim-bookworm
WORKDIR /app
RUN apt-get update&&apt-get install -y --no-install-recommends ca-certificates libgl1 libegl1 libgles2 libglib2.0-0 libgomp1&&rm -rf /var/lib/apt/lists/*
COPY backend_python/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend_python/main.py /app/main.py
COPY backend_python/local_worker.py /app/local_worker.py
COPY backend_python/prepare_local_models.py /app/prepare_local_models.py
COPY backend_python/models /app/models
COPY backend_python/duui /app/duui
RUN useradd -m app&&mkdir -p /data/models /app/.matplotlib-cache /app/local_models&&chown -R app:app /app /data/models
USER app
ENV META_AVATAR_HOST=0.0.0.0
ENV META_AVATAR_PORT=9714
ENV META_AVATAR_OUTPUT_DIR=/data/models
ENV META_AVATAR_3D_MODE=local
ENV META_AVATAR_TRIPOSR_PATH=/app/local_models/TripoSR
ENV META_AVATAR_LOCAL_IMAGE_MODEL=/app/local_models/stable-diffusion-v1-5
ENV META_AVATAR_LOCAL_3D_DEVICE=cpu
ENV META_AVATAR_LOCAL_IMAGE_DEVICE=cpu
ENV META_AVATAR_MC_RESOLUTION=128
ENV META_AVATAR_LOCAL_IMAGE_SIZE=512x768
ENV META_AVATAR_LOCAL_PHOTO_STRENGTH=0.42
ENV META_AVATAR_OLLAMA_IMAGE_API_URL=http://host.docker.internal:11434/api/generate
ENV META_AVATAR_OLLAMA_IMAGE_MODEL=x/flux2-klein:4b
ENV META_AVATAR_OLLAMA_IMAGE_STEPS=4
ENV META_AVATAR_OLLAMA_TEXT_API_URL=http://host.docker.internal:11434/api/generate
ENV META_AVATAR_OLLAMA_TEXT_MODEL=qwen3.5:0.8b
ENV HF_HOME=/app/local_models/.cache
ENV U2NET_HOME=/app/local_models/u2net
ENV MPLCONFIGDIR=/app/.matplotlib-cache
EXPOSE 9714
VOLUME ["/data/models","/app/local_models"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python","-c","from urllib.request import urlopen;urlopen('http://127.0.0.1:9714/api/health',timeout=3)"]
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","9714","--workers","1"]
