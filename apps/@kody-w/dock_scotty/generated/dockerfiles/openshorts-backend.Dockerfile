FROM brainicism/bgutil-ytdlp-pot-provider@sha256:79b7d390e024f3308a0b8fe2041be7e4e4d6a8c30ad6052a89bc51d210c385f1 AS bgutil
FROM denoland/deno@sha256:6e4bc7aed62e400bb3f1bbea561da91e7abc02e1dbc5c3db38af78c3624f2760 AS deno
FROM python@sha256:174bec68e0451bffabbb08c7d5d21c6b253f772d81d52b9558af97bb3159b761

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
COPY system-packages/ /opt/system-packages/
COPY system-packages.sha256 /opt/system-packages.sha256
RUN cd /opt/system-packages && sha256sum -c /opt/system-packages.sha256 \
    && dpkg --unpack /opt/system-packages/*.deb \
    && dpkg --configure --pending \
    && test -z "$(dpkg --audit)" \
    && rm -rf /opt/system-packages /var/lib/apt/lists/*

COPY wheelhouse/ /opt/wheelhouse/
COPY requirements.lock /opt/requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-index --no-deps --require-hashes \
       --find-links /opt/wheelhouse -r /opt/requirements.lock \
    && /opt/venv/bin/pip check \
    && rm -rf /opt/wheelhouse

COPY --from=bgutil /usr/local/bin/node /usr/local/bin/node
COPY --from=bgutil /app /opt/bgutil-provider/server
COPY --from=deno /deno /usr/local/bin/deno
ENV PATH="/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    BGUTIL_SCRIPT_PATH=/opt/bgutil-provider/server/build/generate_once.js \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    YOLO_CONFIG_DIR=/tmp/Ultralytics \
    YOLO_MODEL_PATH=/opt/models/yolov8n.pt \
    WHISPER_MODEL=/opt/models/faster-whisper-small \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE=int8 \
    TRANSNETV2_DEVICE=cpu \
    BILLING_ENABLED=false \
    MAX_CONCURRENT_JOBS=1 \
    CLIP_WORKERS=1 \
    ASR_GPU_CONCURRENCY=1 \
    FFMPEG_ENCODER=x264 \
    AWS_EC2_METADATA_DISABLED=true
COPY models/ /opt/models/
COPY models.sha256 /opt/models.sha256
RUN cd /opt/models && sha256sum -c /opt/models.sha256 \
    && find /opt/models -type f -exec chmod 0644 '{}' ';'
WORKDIR /app
COPY source/ /app/
RUN mkdir -p /usr/local/share/fonts/openshorts \
    && cp fonts/*.ttf /usr/local/share/fonts/openshorts/ \
    && cp fonts/openshorts-fontmap.conf /etc/fonts/conf.d/60-openshorts.conf \
    && fc-cache -f \
    && groupadd -g 1000 appuser \
    && useradd -u 1000 -g 1000 -d /app -s /usr/sbin/nologin appuser \
    && mkdir -p /app/output /app/uploads /app/.cache /tmp/Ultralytics \
    && chown -R 1000:1000 /app /tmp/Ultralytics
LABEL org.opencontainers.image.source="https://github.com/mutonby/openshorts" \
      org.opencontainers.image.revision="0db0a3a04ba06b3dc74a670f38e335910c294249" \
      io.rapp.scotty.qualification="openshorts-offline-20260921"
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health/ready || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "15"]
