# Build stage produces a static bundle; the runtime stage is nginx serving
# it, not Node -- there's nothing server-side about this dashboard once it's
# built (Phase 13's design note: "the dashboard is a consumer of the API,
# not the product"), so shipping a Node runtime into production would just
# be dead weight.
FROM node:22-slim AS builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# VITE_API_BASE_URL is baked into the built JS at this step (Vite inlines
# import.meta.env.* at build time) -- it must be supplied as a build arg,
# not a container runtime env var, unlike the API/worker's env-based config.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html
EXPOSE 80
