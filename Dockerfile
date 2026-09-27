FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY --from=frontend /build/dist ./frontend/dist
RUN useradd --uid 10001 --create-home readyline && mkdir -p /app/data && chown -R readyline:readyline /app/data
USER readyline
ENV READYLINE_DB=/app/data/readyline.sqlite3
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
