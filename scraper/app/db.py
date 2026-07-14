import logging
import sys
import time

import psycopg2

logger = logging.getLogger("cs2-scraper.db")

MAX_RETRIES = 10
RETRY_DELAY_SECONDS = 3


def connect_with_retry(host: str, port: str, dbname: str, user: str, password: str):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
        except psycopg2.OperationalError as exc:
            last_error = exc
            logger.warning("DB not ready (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            time.sleep(RETRY_DELAY_SECONDS)
    logger.error("Giving up connecting to DB after %d attempts: %s", MAX_RETRIES, last_error)
    sys.exit(1)


def ensure_market_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data (
            id SERIAL PRIMARY KEY,
            item_name TEXT NOT NULL,
            lowest_price NUMERIC(10, 2) NOT NULL,
            volume INTEGER NOT NULL,
            scraped_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS market_data_item_name_scraped_at_idx "
        "ON market_data (item_name, scraped_at);"
    )
    cur.close()


def insert_market_row(conn, row: dict) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO market_data (item_name, lowest_price, volume, scraped_at)
        VALUES (%(item_name)s, %(lowest_price)s, %(volume)s, now());
        """,
        row,
    )
    cur.close()
