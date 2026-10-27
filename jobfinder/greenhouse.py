"""Client for the public Greenhouse Job Board API."""
import html
import re
import time

import httpx

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def strip_html(s):
    s = html.unescape(s or "")           # content arrives entity-escaped
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def normalize(raw, token):
    return {
        "id": raw["id"],
        "company": token,
        "title": raw.get("title", ""),
        "location": (raw.get("location") or {}).get("name", ""),
        "url": raw.get("absolute_url", ""),
        "updated": raw.get("updated_at", ""),
        "pay": raw.get("pay_input_ranges") or [],
        "text": strip_html(raw.get("content", "")),
    }


def fetch_board(token, client=None, retries=3, delay=1.0):
    """Return normalized jobs for a board; [] if the board does not exist."""
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        for attempt in range(retries):
            try:
                r = client.get(API.format(token=token), params={"content": "true", "pay_transparency": "true"})
            except httpx.TransportError:
                time.sleep(delay * (attempt + 1))
                continue
            if r.status_code == 404:
                return []
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(delay * (attempt + 1))
                continue
            r.raise_for_status()
            return [normalize(j, token) for j in r.json().get("jobs", [])]
        return []
    finally:
        if own:
            client.close()
