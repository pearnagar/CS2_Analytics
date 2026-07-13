import os
import time

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "cs2_stats")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "password123")

CONNECT_MAX_RETRIES = 10
CONNECT_RETRY_DELAY_SECONDS = 3
QUERY_TIMEOUT_MS = 5000

app = FastAPI(title="CS2 Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
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
            print(f"[api] DB not ready (attempt {attempt}/{CONNECT_MAX_RETRIES}): {exc}")
            time.sleep(CONNECT_RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Could not connect to DB after {CONNECT_MAX_RETRIES} attempts: {last_error}")


@app.on_event("startup")
def startup_check():
    conn = get_connection()
    conn.close()


@app.get("/api/stats")
def get_stats():
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, player_name, matches_played, kills, deaths, kd_ratio "
            "FROM player_stats ORDER BY id;"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except psycopg2.Error as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}")
