import logging
import os
import time
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cs2-api")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


DB_HOST = os.environ.get("DB_HOST", "cs2-db-service")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "cs2_stats")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = require_env("DB_PASSWORD")
API_KEY = require_env("API_KEY")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

CONNECT_MAX_RETRIES = 10
CONNECT_RETRY_DELAY_SECONDS = 3
QUERY_TIMEOUT_MS = 5000

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection()
    conn.close()
    yield


app = FastAPI(title="CS2 Analytics API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["X-API-Key"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


def get_connection():
    last_error = None
    for attempt in range(1, CONNECT_MAX_RETRIES + 1):
        try:
            return psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                options=f"-c statement_timeout={QUERY_TIMEOUT_MS}",
            )
        except psycopg2.OperationalError as exc:
            last_error = exc
            logger.warning("DB not ready (attempt %d/%d): %s", attempt, CONNECT_MAX_RETRIES, exc)
            time.sleep(CONNECT_RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Could not connect to DB after {CONNECT_MAX_RETRIES} attempts: {last_error}")


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


LATEST_PER_ITEM_QUERY = """
    SELECT DISTINCT ON (item_name) item_name, lowest_price, volume, scraped_at
    FROM market_data
    ORDER BY item_name, scraped_at DESC;
"""


class MarketDataCollector:
    def collect(self):
        price_gauge = GaugeMetricFamily(
            "cs2_market_lowest_price_usd", "Latest Steam Market lowest price (USD)", labels=["item_name"]
        )
        volume_gauge = GaugeMetricFamily(
            "cs2_market_volume", "Latest Steam Market sell listing volume", labels=["item_name"]
        )
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(LATEST_PER_ITEM_QUERY)
            for item_name, lowest_price, volume, _scraped_at in cur.fetchall():
                price_gauge.add_metric([item_name], float(lowest_price))
                volume_gauge.add_metric([item_name], float(volume))
            cur.close()
            conn.close()
        except psycopg2.Error:
            logger.exception("Failed to collect market_data metrics")
        yield price_gauge
        yield volume_gauge


REGISTRY.register(MarketDataCollector())


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.close()
        conn.close()
        return {"status": "ready"}
    except psycopg2.Error:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Not ready")


@app.get("/api/market", dependencies=[Depends(require_api_key)])
@limiter.limit("30/minute")
def get_market(request: Request):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(LATEST_PER_ITEM_QUERY)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except psycopg2.Error:
        logger.exception("Database error while fetching market data")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
