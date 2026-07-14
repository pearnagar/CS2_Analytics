import logging
import os
import sys
import time

from app import db
from app.market_client import MarketAPIError, SteamMarketClient
from app.market_transform import build_market_row

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cs2-scraper")

REQUEST_PACING_SECONDS = 8.0


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        logger.error("Required environment variable %s is not set", name)
        sys.exit(1)
    return value


def main():
    market_items = [item.strip() for item in require_env("MARKET_ITEMS").split(",") if item.strip()]

    db_host = os.environ.get("DB_HOST", "cs2-db-service")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "cs2_stats")
    db_user = os.environ.get("DB_USER", "admin")
    db_password = require_env("DB_PASSWORD")

    conn = db.connect_with_retry(db_host, db_port, db_name, db_user, db_password)
    conn.autocommit = True
    db.ensure_market_schema(conn)

    client = SteamMarketClient(currency=1)
    updated = 0
    for index, item_name in enumerate(market_items):
        if index > 0:
            time.sleep(REQUEST_PACING_SECONDS)
        try:
            overview = client.get_price_overview(item_name)
            row = build_market_row(item_name, overview)
            db.insert_market_row(conn, row)
            updated += 1
            logger.info("Recorded price for %s: $%.2f (volume %d)", item_name, row["lowest_price"], row["volume"])
        except MarketAPIError as exc:
            logger.error("Failed to fetch/record price for '%s': %s", item_name, exc)

    conn.close()
    logger.info("Done. Recorded %d/%d items.", updated, len(market_items))
    if updated == 0 and market_items:
        sys.exit(1)


if __name__ == "__main__":
    main()
