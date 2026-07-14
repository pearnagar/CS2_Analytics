from app.market_transform import build_market_row, parse_price, parse_volume


def test_parse_price_strips_currency_symbol():
    assert parse_price("$12.34") == 12.34


def test_parse_price_handles_thousands_separator():
    assert parse_price("$1,234.56") == 1234.56


def test_parse_price_handles_empty_string():
    assert parse_price("") == 0.0


def test_parse_price_handles_malformed_string():
    assert parse_price("not a price") == 0.0


def test_parse_volume_strips_commas():
    assert parse_volume("1,234") == 1234


def test_parse_volume_handles_empty_string():
    assert parse_volume("") == 0


def test_build_market_row():
    overview = {"success": True, "lowest_price": "$12.34", "volume": "1,234", "median_price": "$12.50"}

    row = build_market_row("AK-47 | Redline (Field-Tested)", overview)

    assert row["item_name"] == "AK-47 | Redline (Field-Tested)"
    assert row["lowest_price"] == 12.34
    assert row["volume"] == 1234


def test_build_market_row_missing_fields_default_to_zero():
    row = build_market_row("Unknown Item", {})

    assert row["lowest_price"] == 0.0
    assert row["volume"] == 0
