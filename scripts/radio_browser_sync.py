#!/usr/bin/env python3
"""Radio-Browser directory sync for OmniRadio stations.

Registers every station in config/stations.json as an individual entry in the
radio-browser.info public directory (the API used by the earlier /json/add flow).

Idempotent: stations whose name or stream URL already exist in the directory are
skipped, so re-running is safe and only NEW stations get pushed.

Usage:
    python3 radio_browser_sync.py [--config PATH] [--base https://radio.xecod.com]
Cron-friendly: exit 0 on success, 1 if any station failed.

Directory API truth: the add endpoint is POST /json/add with
application/x-www-form-urlencoded (NOT /json/stations, NOT /json/stations/add).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://de1.api.radio-browser.info"
USER_AGENT = "OmniRadio/2.2.0 (admin@xecod.com)"

DEFAULT_TAGS = ["quran", "islam", "islamic", "arabic", "religious"]
TAG_BY_ID = {
    "quran-cairo": ["egypt", "cairo", "egyptian"],
    "abdulbasit": ["abdulbasit", "reciter", "mojawwad"],
    "alminshawi": ["minshawi", "reciter"],
    "alhussary": ["hussary", "hussari", "reciter"],
    "alafasi": ["afasy", "afasi", "reciter"],
    "local-library": ["islamic", "library", "uploads"],
}


def api_get(path: str) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post(payload: dict) -> dict:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/json/add",
        data=data,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def already_registered(name: str, url: str) -> bool:
    """True if the directory already has an entry with this name or stream URL."""
    try:
        rows = api_get(f"/json/stations/search?name={urllib.parse.quote(name)}&limit=100&hidebroken=false")
        for s in rows:
            if s.get("name", "").strip().lower() == name.strip().lower():
                return True
            for key in ("url", "url_resolved"):
                if s.get(key, "").strip().rstrip("/") == url.strip().rstrip("/"):
                    return True
    except Exception as exc:  # network hiccup -> assume not registered (will retry)
        print(f"  ! search check failed ({exc}); will attempt add anyway")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/home/saas/radio/config/stations.json")
    parser.add_argument("--base", default="https://radio.xecod.com")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        cfg_path = Path("/app/config/stations.json")
    if not cfg_path.exists():
        print(f"ERROR: config not found (tried {args.config} and /app/config/stations.json)")
        return 1

    with cfg_path.open(encoding="utf-8") as f:
        stations = json.load(f).get("stations", [])

    if not stations:
        print("ERROR: no stations in config")
        return 1

    added, skipped, failed = [], [], []
    for s in stations:
        sid = s.get("id", "")
        name_en = s.get("name_en", "").strip()
        name_ar = s.get("name", "").strip()
        display = f"OmniRadio - {name_en or sid} ({name_ar})" if name_en else f"OmniRadio - {name_ar or sid}"
        url = f"{args.base.rstrip('/')}/station/{sid}"
        homepage = f"{args.base.rstrip('/')}/listen/{sid}"
        tags = ",".join(dict.fromkeys(DEFAULT_TAGS + TAG_BY_ID.get(sid, [])))

        print(f"[{sid}] {display}")
        if already_registered(display, url):
            print("  = already listed, skipped")
            skipped.append(sid)
            continue

        payload = {
            "name": display,
            "url": url,
            "homepage": homepage,
            "tags": tags,
            "country": "Egypt",
            "countrycode": "EG",
            "language": "ar",
            "state": "Cairo",
        }
        try:
            res = api_post(payload)
            if res.get("ok"):
                print(f"  + added: {res.get('uuid')}")
                added.append(sid)
            else:
                print(f"  ! add rejected: {res}")
                failed.append(sid)
        except Exception as exc:
            print(f"  ! add failed: {exc}")
            failed.append(sid)
        time.sleep(1.0)  # be polite to the directory

    print(f"\nSUMMARY: added={added or 'none'} skipped={skipped or 'none'} failed={failed or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())