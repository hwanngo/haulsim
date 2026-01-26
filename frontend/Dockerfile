# syntax=docker/dockerfile:1
# Frontend: build the Vite/React/TS app, then serve the static bundle via nginx
# (which also reverse-proxies /api to the backend, including SSE).

# --- build stage ---
FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# --- serve stage ---
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# Run nginx as the non-root, pre-existing "nginx" user (C3). The stock image
# runs the master as root; instead we drop the top-level "user nginx;" directive
# (nginx warns if a non-root master tries to honour it), point the pid file at a
# writable location, and chown the dirs nginx needs to write (cache, run, the
# served html). Port 80 is fine for a non-root process inside the container.
RUN sed -i '/^user[[:space:]]/d' /etc/nginx/nginx.conf \
    && sed -i 's#^pid[[:space:]].*#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && mkdir -p /tmp /var/cache/nginx \
    && chown -R nginx:nginx /var/cache/nginx /usr/share/nginx/html /etc/nginx/conf.d \
    && touch /tmp/nginx.pid && chown nginx:nginx /tmp/nginx.pid

USER nginx
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
