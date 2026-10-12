# ---------- фронтенд ----------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- бэкенд ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True DEKANAT_WARMUP=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements/ requirements/
RUN pip install -r requirements/backend.txt
COPY core/ core/
COPY config/ config/
COPY data/rules.md data/rules.md
COPY backend/ backend/
COPY scripts/ scripts/
COPY --from=frontend /app/frontend/dist frontend/dist
# предзагрузка весов OCR в образ (офлайн-запуск)
RUN python scripts/download_models.py || true
WORKDIR /app/backend
RUN python manage.py migrate
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate && python -m waitress --listen=0.0.0.0:8000 --threads=4 dekanat.wsgi:application"]
