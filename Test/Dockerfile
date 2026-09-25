FROM python:3.10-slim-bookworm
WORKDIR /app
RUN apt-get update&&apt-get install -y --no-install-recommends ca-certificates libgl1 libegl1 libgles2 libglib2.0-0 libgomp1&&rm -rf /var/lib/apt/lists/*
COPY backend_python/requirements.txt /app/requirements.txt
# The container has no GPU, so take the CPU build of torch instead of the
# default CUDA one, which would add several GB of unused NVIDIA libraries.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "torch>=2.2,<3"&&pip install --no-cache-dir -r /app/requirements.txt
COPY backend_python/main.py backend_python/local_worker.py backend_python/prepare_local_models.py /app/
COPY backend_python/models /app/models
COPY backend_python/duui /app/duui
RUN useradd -m app&&mkdir -p /data/models /app/.matplotlib-cache /app/local_models&&chown -R app:app /app /data/models
USER app
ENV META_AVATAR_HOST=0.0.0.0
ENV META_AVATAR_PORT=9714
ENV META_AVATAR_OUTPUT_DIR=/data/models
# Model weights are not baked into the image. Run prepare_local_models.py on
# the host once and mount backend_python/local_models here (see docker-compose.yml).
ENV META_AVATAR_LOCAL_MODELS=/app/local_models
ENV META_AVATAR_LOCAL_3D_DEVICE=cpu
ENV META_AVATAR_LOCAL_IMAGE_DEVICE=cpu
ENV META_AVATAR_OLLAMA_IMAGE_API_URL=http://host.docker.internal:11434/api/generate
ENV META_AVATAR_OLLAMA_TEXT_API_URL=http://host.docker.internal:11434/api/generate
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV MPLCONFIGDIR=/app/.matplotlib-cache
EXPOSE 9714
VOLUME ["/data/models"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python","-c","from urllib.request import urlopen;urlopen('http://127.0.0.1:9714/api/health',timeout=3)"]
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","9714","--workers","1"]
