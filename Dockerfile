# NEWDRU Ops: one container that serves the React app and the API on port 8001.
# Built and run by Cloudflare Containers (see wrangler.jsonc). No secrets are baked in:
# they are injected at runtime from Cloudflare secrets.

# ---- 1. Build the frontend ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile --ignore-engines --network-timeout 600000
COPY frontend/ ./
# Same-origin API: the browser calls /api on mynewdru.in itself.
ENV REACT_APP_BACKEND_URL="" GENERATE_SOURCEMAP=false CI=false
RUN yarn build

# ---- 2. Runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_ENV=production FRONTEND_BUILD_DIR=/app/frontend/build PORT=8001
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY USER_GUIDE.md /app/USER_GUIDE.md
COPY --from=web /web/build /app/frontend/build
# Run as an unprivileged user
RUN useradd --system --uid 10001 newdru && chown -R newdru /app
USER newdru
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/health')" || exit 1
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--no-server-header"]
