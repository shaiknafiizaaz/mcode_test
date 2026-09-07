FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV TENET_DB_PATH=/app/data/app.db
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
