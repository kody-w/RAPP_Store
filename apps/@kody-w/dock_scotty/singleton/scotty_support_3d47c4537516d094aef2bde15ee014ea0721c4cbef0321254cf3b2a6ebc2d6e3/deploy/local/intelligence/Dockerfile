FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

LABEL rapp.dock.application="intelligence" \
      rapp.dock.copilot.version="1.0.88" \
      rapp.dock.copilot.archive.sha256="e263f5f9eb0db5dddf5775ac98c437e27743857ce0ba310f08f2338aebd1107d"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INTELLIGENCE_STATE=/state \
    TMPDIR=/state

RUN useradd --uid 10001 --create-home --home-dir /home/ai ai \
    && mkdir /app /state \
    && chown 10001:10001 /state \
    && chmod 0700 /state

COPY --chmod=0755 copilot /usr/local/bin/copilot
COPY --chmod=0444 server.py schema.py /app/

USER 10001:10001
WORKDIR /app
EXPOSE 8080
ENTRYPOINT ["python", "/app/server.py"]
