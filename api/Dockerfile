FROM python:3.11-slim

WORKDIR /app

# Upgrade core tools and patch the vulnerable transitive dependencies flagged by Trivy
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip setuptools "wheel>=0.46.2" "jaraco.context>=6.1.0"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]