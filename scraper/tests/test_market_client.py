from unittest.mock import MagicMock, patch

import pytest
import requests

from app.market_client import MarketAPIError, SteamMarketClient


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("app.market_client.time.sleep", lambda *_args, **_kwargs: None)


def _make_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400 and status_code != 429:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_retries_on_429_then_succeeds():
    client = SteamMarketClient()
    rate_limited = _make_response(status_code=429)
    success = _make_response(status_code=200, json_data={"success": True, "lowest_price": "$1.00", "volume": "5"})

    with patch.object(client.session, "get", side_effect=[rate_limited, success]) as mock_get:
        data = client.get_price_overview("AK-47 | Redline (Field-Tested)")

    assert data["success"] is True
    assert mock_get.call_count == 2


def test_raises_marketapierror_after_exhausting_retries_on_timeout():
    client = SteamMarketClient()

    with patch.object(client.session, "get", side_effect=requests.Timeout("timed out")):
        with pytest.raises(MarketAPIError):
            client.get_price_overview("AWP | Asiimov (Field-Tested)")


def test_raises_marketapierror_when_success_is_false():
    client = SteamMarketClient()
    failure = _make_response(status_code=200, json_data={"success": False})

    with patch.object(client.session, "get", return_value=failure):
        with pytest.raises(MarketAPIError):
            client.get_price_overview("Nonexistent Item")


def test_does_not_crash_process_on_repeated_429(capsys):
    client = SteamMarketClient()
    always_limited = _make_response(status_code=429)

    with patch.object(client.session, "get", return_value=always_limited):
        with pytest.raises(MarketAPIError):
            client.get_price_overview("AK-47 | Redline (Field-Tested)")
    # Reaching this line proves the MarketAPIError was a normal exception,
    # not a process crash (SystemExit/os._exit) — the caller in main.py
    # catches MarketAPIError per-item and continues the loop.
