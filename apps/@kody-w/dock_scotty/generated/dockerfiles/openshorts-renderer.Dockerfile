FROM node@sha256:fc3faf127a182135fd956e68d570b1932a758f8008866d8dd6e131cf89de9605 AS compile
WORKDIR /build
ENV NPM_CONFIG_USERCONFIG=/opt/qualification/npmrc NPM_CONFIG_GLOBALCONFIG=/dev/null \
    NODE_OPTIONS=--max-old-space-size=1536 UV_THREADPOOL_SIZE=4
COPY qualification/npmrc /opt/qualification/npmrc
COPY qualification/offline-npm-lock.mjs ./
COPY tarballs/ ./tarballs/
COPY source/render-service/ ./render-service/
COPY source/remotion/ ./remotion/
RUN for project in render-service remotion; do \
      cd /build/$project && \
      node /build/offline-npm-lock.mjs package-lock.json artifact-manifest.json /build/tarballs && \
      npm ci --offline --ignore-scripts || exit 1; \
    done && cd /build/render-service && npm run build
FROM node@sha256:fc3faf127a182135fd956e68d570b1932a758f8008866d8dd6e131cf89de9605
ENV DEBIAN_FRONTEND=noninteractive
COPY system-packages/ /opt/system-packages/
COPY system-packages.sha256 /opt/system-packages.sha256
RUN cd /opt/system-packages && sha256sum -c /opt/system-packages.sha256 \
    && printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod 0755 /usr/sbin/policy-rc.d \
    && apt-get --no-install-recommends -y install /opt/system-packages/*.deb \
    && test -z "$(dpkg --audit)" \
    && rm -rf /opt/system-packages /var/lib/apt/lists/*
WORKDIR /app
COPY --from=compile /build/render-service/ /app/
COPY --from=compile /build/remotion/ /app/remotion/
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    REMOTION_BUNDLE_PATH=/app/remotion \
    OUTPUT_DIR=/output \
    PORT=3100 \
    NODE_OPTIONS="--max-old-space-size=1536"
RUN mkdir -p /output /home/node/.cache && chown -R 1000:1000 /app /output
LABEL org.opencontainers.image.source="https://github.com/mutonby/openshorts" \
      org.opencontainers.image.revision="0db0a3a04ba06b3dc74a670f38e335910c294249" \
      io.rapp.scotty.qualification="openshorts-offline-20260921"
USER 1000:1000
EXPOSE 3100
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3100/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "dist/server.js"]
