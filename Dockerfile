# Stage 1: build the planner and the help center into backend/static
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps

COPY frontend/ ./
# Shows the Transactions section in the planner.
ARG VITE_TRANSACTIONS_ENABLED=false
RUN npx vite build


# Stage 2: the API server, which also serves the built planner
FROM python:3.14-slim

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /app/backend/static ./static

# /data holds the SQLite database and the secrets generated beside it.
RUN adduser --disabled-password --no-create-home --gecos '' appuser \
    && mkdir /data && chown appuser /data
USER appuser
VOLUME /data

ENV PORT=8000 \
    DATABASE_URL=sqlite:////data/coastmath.db

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]
