# syntax=docker/dockerfile:1.7

# Pin the exact Node image identified in the field logs; npm is pinned below.
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS builder

WORKDIR /source/frontend
COPY frontend/package.json frontend/package-lock.json ./
COPY deploy/bootstrap/npm-install.mjs /opt/p2pkanban/npm-install.mjs
ENV P2PKANBAN_NPM_CACHE=/root/.npm
RUN --mount=type=cache,target=/root/.npm,sharing=locked node /opt/p2pkanban/npm-install.mjs install --global npm@11.9.0 \
    && node /opt/p2pkanban/npm-install.mjs ci
COPY frontend ./

ARG VITE_API_BASE_URL=/api/v1
ARG VITE_SOURCE_REVISION=unknown
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_SOURCE_REVISION=${VITE_SOURCE_REVISION}
ENV VITE_ENABLE_PROJECT_ROADMAP_SEED=true
RUN npm run build

FROM nginx:1.27-alpine

COPY deploy/bootstrap/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /source/frontend/dist /usr/share/nginx/html

EXPOSE 8080
