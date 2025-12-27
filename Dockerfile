# Stage 1: Build the frontend
FROM node:20-alpine AS frontend-build

WORKDIR /usr/src/app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Build the backend
FROM python:3.11-slim AS backend-build

WORKDIR /usr/src/app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/ /usr/src/app/backend/
COPY --from=frontend-build /usr/src/app/frontend/dist /usr/src/app/backend/app/static

# Stage 3: Final runtime image
FROM python:3.11-slim

WORKDIR /usr/src/app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-build /opt/venv /opt/venv
COPY --from=backend-build /usr/src/app/backend /usr/src/app/backend

ENV PATH="/opt/venv/bin:$PATH"

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /usr/src/app
USER appuser

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
