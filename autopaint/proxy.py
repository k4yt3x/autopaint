import requests
from loguru import logger

MULLVAD_RELAYS_URL = "https://api.mullvad.net/public/relays/wireguard/v2"


def fetch_proxies(countries: list[str]) -> list[str]:
    """Fetch SOCKS5 proxy addresses from Mullvad for the given country codes."""
    resp = requests.get(MULLVAD_RELAYS_URL, timeout=30)
    resp.raise_for_status()

    prefixes = tuple(f"{code}-" for code in countries)
    proxies: list[str] = []

    for relay in resp.json()["wireguard"]["relays"]:
        if relay["location"].startswith(prefixes) and relay["active"]:
            host = relay["hostname"].replace("wg-", "wg-socks5-")
            proxies.append(f"socks5://{host}.relays.mullvad.net:1080")

    logger.info(
        "Fetched {} Mullvad proxies for countries={}",
        len(proxies),
        ",".join(countries),
    )
    return proxies
