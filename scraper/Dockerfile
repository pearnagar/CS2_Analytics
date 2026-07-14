FROM python:3.11-slim

WORKDIR /app

# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip setuptools "wheel>=0.46.2" "jaraco.context>=6.1.0"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "app.main"]
