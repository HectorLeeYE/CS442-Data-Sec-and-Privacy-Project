# One image: FastAPI serves the API and the built dashboard on :8000.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m spacy download en_core_web_lg
COPY backend/ .
COPY --from=web /web/dist /app/frontend/dist
# The database and the key authority (ABE master key, signing key, audit anchor) live on
# separate volumes: stealing /data alone decrypts nothing.
ENV DB_PATH=/data/demo.sqlite3 KEYS_DIR=/keys
VOLUME /data /keys
EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
