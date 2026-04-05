import re

import requests
from loguru import logger

UA_LIST_URL = (
    "https://raw.githubusercontent.com/MichaelJorky/"
    "top-user-agents-latest/refs/heads/main/data/browsers/browsers_1.txt"
)

# Greased brand strings rotated by Chromium across major versions.
_GREASE_BRANDS = [
    "Not/A)Brand",
    "Not.A/Brand",
    "Not_A Brand",
    "Not-A.Brand",
    "Not A;Brand",
    "Not A(Brand",
]

# Headers specific to Firefox-based UAs.
_FIREFOX_HEADERS = {
    "Sec-GPC": "1",
    "Priority": "u=0",
    "TE": "trailers",
}

# Static headers shared by all Chrome-based UAs.
_CHROME_HEADERS = {
    "DNT": "1",
    "Priority": "u=1, i",
}


def fetch_user_agents() -> list[str]:
    """Fetch the latest user agent list from GitHub."""
    resp = requests.get(UA_LIST_URL, timeout=30)
    resp.raise_for_status()

    agents = [line.strip() for line in resp.text.splitlines() if line.strip()]
    logger.info("Fetched {} user agents", len(agents))

    return agents


def _parse_chrome_version(user_agent: str) -> int | None:
    """Return the major Chrome/Chromium version, or None if not Chrome-based."""
    match = re.search(r"Chrome/(\d+)", user_agent)
    if match is None:
        return None

    # Exclude Edge, Opera, etc. that also carry "Chrome/" in their UA.
    if re.search(r"Edg/|OPR/|Brave/|Vivaldi/", user_agent):
        return None

    return int(match.group(1))


def _parse_platform(user_agent: str) -> str:
    """Derive the sec-ch-ua-platform value from the UA string."""
    if "Windows" in user_agent:
        return '"Windows"'
    if "Macintosh" in user_agent or "Mac OS X" in user_agent:
        return '"macOS"'
    if "Android" in user_agent:
        return '"Android"'
    if "CrOS" in user_agent:
        return '"Chrome OS"'
    # Linux, X11, or anything else
    return '"Linux"'


def _is_mobile(user_agent: str) -> bool:
    """Return True if the UA looks like a mobile browser."""
    return "Mobile" in user_agent or "Android" in user_agent


def build_extra_headers(user_agent: str) -> dict[str, str]:
    """Return browser-specific headers based on the user agent string.

    Chrome-based UAs get sec-ch-ua, sec-ch-ua-mobile, sec-ch-ua-platform, DNT,
    and the Chrome-style Priority header.  The platform and mobile flag are
    derived from the UA string itself.

    Firefox (and other) UAs get Sec-GPC, TE: trailers, and the Firefox-style
    Priority header.
    """
    major = _parse_chrome_version(user_agent)

    if major is None:
        return {**_FIREFOX_HEADERS}

    grease = _GREASE_BRANDS[major % len(_GREASE_BRANDS)]
    grease_version = str(major % 100 // 4)
    mobile = "?1" if _is_mobile(user_agent) else "?0"
    platform = _parse_platform(user_agent)

    return {
        **_CHROME_HEADERS,
        "sec-ch-ua": f'"{grease}";v="{grease_version}", "Chromium";v="{major}"',
        "sec-ch-ua-mobile": mobile,
        "sec-ch-ua-platform": platform,
    }
