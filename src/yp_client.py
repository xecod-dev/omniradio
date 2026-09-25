"""Icecast-compatible Yellow Pages (YP) directory client.

Internet-Radio.com (and other Icecast directories) only list Icecast/
Shoutcast servers. Real Icecast servers register by pushing "YP touches"
to a directory URL (e.g. http://icecast-yp.internet-radio.com) using the
Icecast YP protocol v2:

    add     action=add&sn=..&type=..&genre=..&b=..&listenurl=..
            -> response headers: SID: <session-id>  TouchFreq: <seconds>
    touch   action=touch&sid=<sid>                  (keep listing alive)
    remove  action=remove&sid=<sid>                 (on shutdown)

We are a custom HTTP MP3 relay (no icecast.xml to add <directory> to),
so this module implements the SAME wire protocol directly. For every
station relay we register a mount listing (listeners/title refreshed on
each touch), and we honor the directory's TouchFreq between touches.

Configuration (env):
    YP_URL      directory endpoint, e.g. http://icecast-yp.internet-radio.com
                (empty string = client disabled)
    YP_ENABLED  "1" (default) or "0" to force-disable even when YP_URL set
    YP_INTERVAL initial touch interval in seconds (override; default 60)
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set

import requests

logger = logging.getLogger("radio.yp")

# Header names the YP directory replies with (protocol v2).
HDR_YP_RESPONSE = "YPResponse"  # "0" failure, "1" success
HDR_YP_MESSAGE = "YPMessage"
HDR_SID = "SID"
HDR_TOUCH_FREQ = "TouchFreq"


class YPClient:
    """Registers each station relay with an Icecast-compatible YP directory."""

    def __init__(
        self,
        base_url: str,
        yp_url: str,
        engine: Any,
        enabled: bool = True,
        interval: int = 60,
        user_agent: str = "Icecast 2.4.1",
    ):
        self.base_url = base_url.rstrip("/")
        self.yp_url = yp_url.strip()
        self.engine = engine
        self.enabled = enabled and bool(self.yp_url)
        self.touch_interval = max(15, interval)
        self.user_agent = user_agent

        # station_id -> SID issued by the directory for that listing
        self._sids: Dict[str, str] = {}
        self._last_touch: Dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if not self.enabled:
            logger.info("YP client disabled (YP_URL not set or YP_ENABLED=0)")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"YP client started for {self.yp_url}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self.enabled and self._sids:
            for station_id, sid in list(self._sids.items()):
                await self._post({"action": "remove", "sid": sid})
                logger.info(f"[YP] {station_id}: removed listing {sid}")
            self._sids.clear()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    async def _run_loop(self) -> None:
        while True:
            try:
                await self._sync_all()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let the loop die
                logger.warning(f"[YP] sync error (will retry): {exc}")
            await asyncio.sleep(self.touch_interval)

    async def _sync_all(self) -> None:
        relays = dict(self.engine.relays)

        # Remove listings for relays that no longer exist.
        for station_id in list(self._sids.keys()):
            if station_id not in relays:
                await self._post({"action": "remove", "sid": self._sids[station_id]})
                logger.info(f"[YP] {station_id}: removed stale listing")
                del self._sids[station_id]
                self._last_touch.pop(station_id, None)

        for station_id, relay in relays.items():
            info = relay.get_status_info() if hasattr(relay, "get_status_info") else {}
            sid = self._sids.get(station_id)

            if sid is None:
                await self._add(station_id, info)
            else:
                await self._touch(station_id, sid, info)

    # ------------------------------------------------------------------
    # Protocol verbs
    # ------------------------------------------------------------------
    async def _add(self, station_id: str, info: Dict[str, Any]) -> None:
        name = info.get("name_en") or info.get("name") or station_id
        category = info.get("category", "Radio")
        bitrate = int(info.get("bitrate", 128))

        params = {
            "action": "add",
            "sn": name,
            "type": "audio/mpeg",
            "genre": category,
            "b": str(bitrate),
            "listenurl": f"{self.base_url}/station/{station_id}",
            "url": self.base_url,
        }
        desc = (info.get("description") or "").strip()
        if desc:
            params["desc"] = desc[:500]

        headers = await self._post(params)
        response_ok = headers.get(HDR_YP_RESPONSE, "").strip() == "1"
        sid = (headers.get(HDR_SID) or "").strip()

        freq = (headers.get(HDR_TOUCH_FREQ) or "").strip()
        if freq.isdigit():
            self.touch_interval = max(15, int(freq))

        if response_ok and sid:
            self._sids[station_id] = sid
            self._last_touch[station_id] = time.time()
            logger.info(
                f"[YP] {station_id}: registered as '{sid}' "
                f"(TouchFreq={self.touch_interval}s)"
            )
        else:
            message = headers.get(HDR_YP_MESSAGE, "no response")
            logger.warning(f"[YP] {station_id}: add rejected ({message})")

    async def _touch(self, station_id: str, sid: str, info: Dict[str, Any]) -> None:
        params = {
            "action": "touch",
            "sid": sid,
        }
        listeners = info.get("listeners")
        title = info.get("current_title")
        if listeners is not None:
            params["listeners"] = str(listeners)
        if title:
            params["st"] = title

        headers = await self._post(params)
        if headers.get(HDR_YP_RESPONSE, "").strip() == "1":
            self._last_touch[station_id] = time.time()
        else:
            # Listing is gone or SID invalid — re-register next cycle.
            message = headers.get(HDR_YP_MESSAGE, "no response")
            logger.warning(
                f"[YP] {station_id}: touch failed ({message}) — will re-add"
            )
            self._sids.pop(station_id, None)
            self._last_touch.pop(station_id, None)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    async def _post(self, params: Dict[str, str]) -> Dict[str, str]:
        """POST form-encoded to the YP endpoint; returns response headers.

        Uses a worker thread so requests' blocking IO never stalls the
        asyncio event loop (same pattern as engine._build_ffmpeg_cmd_async).
        """

        def do_post() -> Dict[str, str]:
            try:
                resp = requests.post(
                    self.yp_url,
                    data=params,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "*/*",
                    },
                    timeout=15,
                )
                return dict(resp.headers)
            except requests.RequestException as exc:
                logger.warning(f"[YP] HTTP error: {exc}")
                return {}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, do_post)