FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Install dependencies, then forcefully nuke the build tools and their METADATA
# to ensure Trivy doesn't trip on orphaned .dist-info directories.
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /usr/local/lib/python3.11/site-packages/pip \
    && rm -rf /usr/local/lib/python3.11/site-packages/pip-* \
    && rm -rf /usr/local/lib/python3.11/site-packages/setuptools \
    && rm -rf /usr/local/lib/python3.11/site-packages/setuptools-* \
    && rm -rf /usr/local/lib/python3.11/site-packages/wheel \
    && rm -rf /usr/local/lib/python3.11/site-packages/wheel-*

COPY main.py .

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]