"""Listener location statistics.

Tracks where listeners connect from using Cloudflare's free geo headers
(CF-IPCountry) available on every request routed through the tunnel — no
external geoip API calls needed. Data is aggregated in-memory per country
and per station, and persisted to disk so counts survive restarts.

 design notes:
- Only "connects" are counted (each GET /station/<id> or /listen/<id>).
- Cold data older than DAYS_TO_KEEP is pruned on save.
- Defaults to region code 'XX' (Cloudflare uses this for unknown/NA).
"""
import json
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict

logger = logging.getLogger("radio.stats")

PERSIST_PATH = Path("/app/data/listener_stats.json")
# Keep no more than this many days of per-day history.
DAYS_TO_KEEP = 90
# Flush interval for the background saver thread. Disk I/O must NEVER run on
# the event-loop thread: a sync write on every connect wedged the loop in
# jbd2_log_wait_commit (ext4 journal) under crawler load and froze the app.
SAVE_INTERVAL_SECONDS = 60

# Crawler/scanner UA fragments — these are station-directory bots, not humans.
# Recording them inflated per-country counts massively (ID-048) and caused
# bursts of connects → burst of disk writes → loop stalls.
IGNORE_UA_FRAGMENTS = (
    "bot", "spider", "crawler", "crawl", "curl/", "wget", "python-requests",
    "python-urllib", "httpx", "aiohttp", "go-http-client", "java/",
    "okhttp", "scrapy", "masscan", "zgrab", "nmap", "headless",
)


class ListenerStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._dirty = False
        # {"countries": {country_code: count}, "stations": {station_id: {cc: count}},
        #  "daily": {"YYYY-MM-DD": {cc: count}}, "last_country": {station_id: cc}}
        self._data = {
            "countries": defaultdict(int),
            "stations": defaultdict(lambda: defaultdict(int)),
            "daily": defaultdict(lambda: defaultdict(int)),
            "last_country": {},
        }
        self._load()
        # Dedicated daemon thread: the ONLY place stats hit the disk.
        self._saver = threading.Thread(
            target=self._saver_loop, name="listener-stats-saver", daemon=True
        )
        self._saver.start()

    # ---------- persistence ----------
    def _load(self):
        try:
            if PERSIST_PATH.exists():
                raw = json.loads(PERSIST_PATH.read_text(encoding="utf-8"))
                self._data["countries"] = defaultdict(int, raw.get("countries", {}))
                self._data["stations"] = defaultdict(
                    lambda: defaultdict(int),
                    {sid: defaultdict(int, ccs) for sid, ccs in raw.get("stations", {}).items()},
                )
                self._data["daily"] = defaultdict(
                    lambda: defaultdict(int),
                    {day: defaultdict(int, ccs) for day, ccs in raw.get("daily", {}).items()},
                )
                self._data["last_country"] = raw.get("last_country", {})
        except Exception as e:
            # Stats are best-effort; never break streaming because of them.
            logger.warning(f"listener_stats load failed: {e}")

    def _saver_loop(self):
        """Background thread — flushes at most once per SAVE_INTERVAL_SECONDS.

        Even if the disk stalls (jbd2 commit wedges, ID-031 family), this
        thread blocks alone; the HTTP event loop keeps streaming.
        """
        while True:
            time.sleep(SAVE_INTERVAL_SECONDS)
            if self._dirty:
                self.save()

    def save(self):
        """Write the current snapshot to disk. May block — only call from the
        saver thread (or admin endpoints), never from a request handler."""
        try:
            with self._lock:
                cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - DAYS_TO_KEEP * 86400))
                daily = {
                    day: ccs for day, ccs in self._data["daily"].items() if day >= cutoff
                }
                payload = {
                    "countries": dict(self._data["countries"]),
                    "stations": {sid: dict(ccs) for sid, ccs in self._data["stations"].items()},
                    "daily": {day: dict(ccs) for day, ccs in sorted(daily.items())},
                    "last_country": dict(self._data["last_country"]),
                }
            PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = PERSIST_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(PERSIST_PATH)
        except Exception as e:
            logger.warning(f"listener_stats save failed: {e}")

    # ---------- recording ----------
    def record_connect(self, station_id: str, request):
        """Record one listener-connect for a station. Pure in-memory — NEVER
        touches the disk (disk I/O from here deadlocked the event loop)."""
        try:
            ua = (request.headers.get("user-agent") or "").lower()
            if any(frag in ua for frag in IGNORE_UA_FRAGMENTS):
                return  # crawler/scanner — not a human listener (ID-048)
            cc = (
                request.headers.get("cf-ipcountry")
                or request.headers.get("CF-IPCountry")
                or "XX"
            ).upper()[:2] or "XX"
            with self._lock:
                self._data["countries"][cc] += 1
                self._data["stations"][station_id][cc] += 1
                day = time.strftime("%Y-%m-%d", time.gmtime())
                self._data["daily"][day][cc] += 1
                self._data["last_country"][station_id] = cc
                self._dirty = True  # saver thread flushes within 60s
        except Exception:
            pass

    # ---------- reporting ----------
    def summary(self) -> Dict:
        with self._lock:
            countries = dict(self._data["countries"])
            stations = {sid: dict(ccs) for sid, ccs in self._data["stations"].items()}
            daily = {day: dict(ccs) for day, ccs in sorted(self._data["daily"].items(), reverse=True)[:30]}
            last = dict(self._data["last_country"])
        total = sum(countries.values())
        ranked = sorted(
            [{"country": cc, "count": n} for cc, n in countries.items()],
            key=lambda x: x["count"], reverse=True,
        )
        flag = {
            # minimal common flag map; fallback 🌍
            "EG": "🇪🇬", "SA": "🇸🇦", "AE": "🇦🇪", "QA": "🇶🇦", "KW": "🇰🇼",
            "BH": "🇧🇭", "OM": "🇴🇲", "JO": "🇯🇴", "PS": "🇵🇸", "LB": "🇱🇧",
            "IQ": "🇮🇶", "SY": "🇸🇾", "MA": "🇲🇦", "DZ": "🇩🇿", "TN": "🇹🇳",
            "LY": "🇱🇾", "SD": "🇸🇩", "YE": "🇾🇪", "TR": "🇹🇷", "US": "🇺🇸",
            "GB": "🇬🇧", "FR": "🇫🇷", "DE": "🇩🇪", "NL": "🇳🇱", "CA": "🇨🇦",
            "AU": "🇦🇺", "ID": "🇮🇩", "MY": "🇲🇾", "PK": "🇵🇰", "IN": "🇮🇳",
            "BD": "🇧🇩", "SE": "🇸🇪", "NO": "🇳🇴", "XX": "🌐",
        }
        return {
            "total_connects": total,
            "distinct_countries": len(countries),
            "countries": [
                {**r, "flag": flag.get(r["country"], "🌍")} for r in ranked
            ],
            "per_station": stations,
            "daily": daily,
            "last_country_per_station": last,
        }

    def clear(self):
        with self._lock:
            self._data = {
                "countries": defaultdict(int),
                "stations": defaultdict(lambda: defaultdict(int)),
                "daily": defaultdict(lambda: defaultdict(int)),
                "last_country": {},
            }
        self.save()


listener_stats = ListenerStats()
