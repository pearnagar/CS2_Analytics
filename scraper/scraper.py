import os
import sys
import time

import psycopg2

DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "cs2_stats")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "password123")

MAX_RETRIES = 10
RETRY_DELAY_SECONDS = 3

MOCK_PLAYERS = [
    ("s1mple", 42, 1180, 720),
    ("ZywOo", 40, 1150, 700),
    ("donk", 38, 1090, 680),
    ("NiKo", 45, 1200, 810),
    ("m0NESY", 36, 1020, 650),
]


def connect_with_retry():
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
            )
        except psycopg2.OperationalError as exc:
            last_error = exc
            print(f"[scraper] DB not ready (attempt {attempt}/{MAX_RETRIES}): {exc}")
            time.sleep(RETRY_DELAY_SECONDS)
    print(f"[scraper] Giving up after {MAX_RETRIES} attempts: {last_error}")
    sys.exit(1)


def main():
    conn = connect_with_retry()
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS player_stats (
            id SERIAL PRIMARY KEY,
            player_name TEXT NOT NULL,
            matches_played INTEGER NOT NULL,
            kills INTEGER NOT NULL,
            deaths INTEGER NOT NULL,
            kd_ratio NUMERIC(5, 2) NOT NULL
        );
        """
    )

    cur.execute("SELECT COUNT(*) FROM player_stats;")
    (count,) = cur.fetchone()
    if count == 0:
        for player_name, matches_played, kills, deaths in MOCK_PLAYERS:
            kd_ratio = round(kills / deaths, 2) if deaths else 0.0
            cur.execute(
                """
                INSERT INTO player_stats
                    (player_name, matches_played, kills, deaths, kd_ratio)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (player_name, matches_played, kills, deaths, kd_ratio),
            )
        print(f"[scraper] Inserted {len(MOCK_PLAYERS)} mock player rows.")
    else:
        print(f"[scraper] player_stats already has {count} rows, skipping seed.")

    cur.close()
    conn.close()
    print("[scraper] Done.")


if __name__ == "__main__":
    main()
