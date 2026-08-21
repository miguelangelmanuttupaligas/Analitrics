# Build LibreChat from the controlled source fork so Analitrics UI changes live in
# React instead of post-build HTML/script injection.
FROM node:24.16.0-alpine

RUN apk upgrade --no-cache \
  && apk add --no-cache jemalloc python3 py3-pip

COPY --from=ghcr.io/astral-sh/uv:0.9.5-python3.12-alpine /usr/local/bin/uv /usr/local/bin/uvx /bin/

ENV LD_PRELOAD=/usr/lib/libjemalloc.so.2

ARG NODE_MAX_OLD_SPACE_SIZE=6144
ARG NPM_CI_TIMEOUT_SECONDS=1500
ARG NPM_CI_ATTEMPTS=2

RUN mkdir -p /app && chown node:node /app
WORKDIR /app

USER node

COPY --chown=node:node fork/package.json fork/package-lock.json ./
COPY --chown=node:node fork/api/package.json ./api/package.json
COPY --chown=node:node fork/client/package.json ./client/package.json
COPY --chown=node:node fork/packages/data-provider/package.json ./packages/data-provider/package.json
COPY --chown=node:node fork/packages/data-schemas/package.json ./packages/data-schemas/package.json
COPY --chown=node:node fork/packages/api/package.json ./packages/api/package.json

RUN \
  touch .env ; \
  mkdir -p /app/client/public/images /app/logs /app/uploads /app/skill /app/data ; \
  chmod 1777 /app/data ; \
  npm config set fetch-retry-maxtimeout 600000 ; \
  npm config set fetch-retries 5 ; \
  npm config set fetch-retry-mintimeout 15000 ; \
  attempt=1 ; \
  until timeout "$NPM_CI_TIMEOUT_SECONDS" npm ci --no-audit ; do \
    status=$? ; \
    if [ "$attempt" -ge "$NPM_CI_ATTEMPTS" ]; then \
      exit "$status" ; \
    fi ; \
    echo "npm ci --no-audit failed with exit code $status; retrying attempt $((attempt + 1))/$NPM_CI_ATTEMPTS" ; \
    attempt=$((attempt + 1)) ; \
    npm cache clean --force || true ; \
    sleep 10 ; \
  done

COPY --chown=node:node fork/ .

RUN \
  NODE_OPTIONS="--max-old-space-size=${NODE_MAX_OLD_SPACE_SIZE}" npm run frontend ; \
  npm prune --production ; \
  npm cache clean --force

USER root

COPY custom/fork /tmp/analitrics-fork

RUN node /tmp/analitrics-fork/patches/files-invalidation.js
RUN node --check /tmp/analitrics-fork/api/routes/analitrics.js \
  && node /tmp/analitrics-fork/patches/install-analitrics-route.js
RUN node /tmp/analitrics-fork/patches/conversation-cleanup.js
RUN node /tmp/analitrics-fork/patches/direct-agent-controller.js

EXPOSE 3080
ENV HOST=0.0.0.0
CMD ["npm", "run", "backend"]
