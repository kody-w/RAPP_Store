FROM node@sha256:929b04d7c782f04f615cf785488fed452b6569f87c73ff666ad553a7554f0006 AS compile
WORKDIR /home/node/work
ENV NPM_CONFIG_USERCONFIG=/opt/qualification/npmrc NPM_CONFIG_GLOBALCONFIG=/dev/null \
    NODE_OPTIONS=--max-old-space-size=1536 UV_THREADPOOL_SIZE=4 \
    VITE_API_URL="" VITE_OPENPANEL_API_URL="" VITE_OPENPANEL_CLIENT_ID=""
COPY qualification/npmrc /opt/qualification/npmrc
COPY qualification/offline-npm-lock.mjs qualification/frontend-build.sh frontend-artifacts.json ./
COPY tarballs/ ./tarballs/
COPY source/dashboard/ ./dashboard/
RUN sh /home/node/work/frontend-build.sh
FROM nginx@sha256:7396be67b6f53012a5cf955fa9040619294c25ccacf11e22af5de1b572fc756e
LABEL org.opencontainers.image.source="https://github.com/mutonby/openshorts" \
      org.opencontainers.image.revision="0db0a3a04ba06b3dc74a670f38e335910c294249" \
      rapp.dock.component="openshorts-frontend"
COPY --from=compile /home/node/work/dashboard/dist/ /usr/share/nginx/html/
COPY qualification/private-nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
