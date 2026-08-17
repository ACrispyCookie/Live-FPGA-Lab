# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS frontend-build
WORKDIR /app

COPY src/frontend/package*.json src/frontend/
RUN npm install --prefix src/frontend

COPY src/frontend src/frontend
COPY src/web_api/static/debug.html src/web_api/static/debug.html
RUN npm run build --prefix src/frontend


FROM python:3.13-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    WEB_API_HOST=0.0.0.0 \
    WEB_API_PORT=9121 \
    WEB_API_DEMO_DIR=/app/demos \
    WEB_API_AGENT_SOCKET=/run/fpga-agent/fpga-agent.sock

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src src
COPY demos demos
COPY --from=frontend-build /app/src/web_api/static src/web_api/static

RUN pip install --no-cache-dir .

EXPOSE 9121 9130
CMD ["python", "-m", "web_api.main"]
