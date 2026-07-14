import logging
import time

import requests

logger = logging.getLogger("cs2-scraper.market_client")

MARKET_API_URL = "https://steamcommunity.com/market/priceoverview/"
CS2_APPID = 730

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 10

HEADERS = {"User-Agent": "cs2-scraper/1.0 (+https://github.com/; personal analytics CronJob)"}


class MarketAPIError(Exception):
    pass


class SteamMarketClient:
    def __init__(self, currency: int = 1, session: requests.Session = None):
        self.currency = currency
        self.session = session or requests.Session()

    def get_price_overview(self, market_hash_name: str, appid: int = CS2_APPID) -> dict:
        params = {
            "appid": appid,
            "currency": self.currency,
            "market_hash_name": market_hash_name,
        }
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.get(
                    MARKET_API_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS
                )
                if response.status_code == 429:
                    wait = RETRY_DELAY_SECONDS * attempt
                    logger.warning(
                        "Market API rate limited (attempt %d/%d), backing off %ds", attempt, MAX_RETRIES, wait
                    )
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                data = response.json()
                if not data.get("success"):
                    raise MarketAPIError(f"Market API returned success=false for '{market_hash_name}'")
                return data
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Market API request failed for '%s' (attempt %d/%d): %s",
                    market_hash_name, attempt, MAX_RETRIES, exc,
                )
                time.sleep(RETRY_DELAY_SECONDS)
        raise MarketAPIError(f"Market API request for '{market_hash_name}' failed after {MAX_RETRIES} attempts: {last_error}")
