import re


def parse_price(price_str: str) -> float:
    if not price_str:
        return 0.0
    cleaned = re.sub(r"[^0-9.,]", "", price_str)
    cleaned = cleaned.replace(",", ".")
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_volume(volume_str: str) -> int:
    if not volume_str:
        return 0
    cleaned = re.sub(r"[^0-9]", "", volume_str)
    return int(cleaned) if cleaned else 0


def build_market_row(item_name: str, overview: dict) -> dict:
    return {
        "item_name": item_name,
        "lowest_price": parse_price(overview.get("lowest_price", "")),
        "volume": parse_volume(overview.get("volume", "")),
    }
