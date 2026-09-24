import os
import json
import time
import socket
import logging
import hashlib
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, PlainTextResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import ConfigManager
from .audio_manager import AudioManager
from .engine import RadioEngine
from .ftp_server import EmbeddedFTPServer
from .quotes_manager import QuotesManager

# Version metadata — bumped by hand on release edits; commit baked at Docker build time.
APP_VERSION = os.getenv("APP_VERSION", "2.6.0")
GIT_SHA = os.getenv("GIT_SHA", "local")
APP_UPDATED = os.getenv("APP_UPDATED", "2026-09-24")

# Canonical public base URL — the ONE domain search engines / AI engines treat as authoritative.
# All canonical links, sitemap entries, og:url and JSON-LD identifiers point here so the
# xecod.com vs serastores.com (/radio prefix) duplicates consolidate into a single entity.
CANONICAL_BASE = os.getenv("CANONICAL_BASE", "https://radio.xecod.com")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("radio.app")

config_manager = ConfigManager()
audio_manager = AudioManager()
engine = RadioEngine(config_manager, audio_manager)
quotes_manager = QuotesManager(os.getenv("QUOTES_DB_PATH", "/app/data/quotes.db"))

# Server credentials & ports
server_cfg = config_manager.get_server_config()
ftp_server = EmbeddedFTPServer(
    audio_dir=os.getenv("AUDIO_DIR", "/app/audio"),
    port=server_cfg.get("ftp_port", 2121),
    pasv_ports=server_cfg.get("ftp_pasv_ports", [2122, 2123, 2124, 2125]),
    user=server_cfg.get("ftp_user", "radio"),
    password=server_cfg.get("ftp_password", "")
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing OmniRadio Multi-Station Studio...")
    ftp_server.start()
    await engine.start()
    quotes_task = asyncio.create_task(quotes_manager.start_daily_sync_worker())
    yield
    # Shutdown
    logger.info("Shutting down OmniRadio Studio...")
    quotes_task.cancel()
    await engine.stop()
    ftp_server.stop()

app = FastAPI(
    title="OmniRadio Multi-Station Studio",
    description="High-performance radio station relay with multi-source auto-failover, web upload, FTP storage, and Windows Media Player support.",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_base_url(request: Request) -> str:
    """Derives proper base URL supporting direct IP, LAN, Tailscale, or platform proxy prefix."""
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", f"127.0.0.1:{server_cfg.get('port', 9000)}"))
    forwarded_prefix = request.headers.get("x-forwarded-prefix", "")
    
    # Check if we are running behind the platform proxy path like /radio
    path_prefix = ""
    if "/radio/" in request.url.path or request.url.path.startswith("/radio"):
        path_prefix = "/radio"
    elif forwarded_prefix:
        path_prefix = forwarded_prefix.rstrip("/")
        
    return f"{forwarded_proto}://{forwarded_host}{path_prefix}".rstrip("/")

@app.api_route("/", methods=["GET", "HEAD"])
async def root_default_redirect(request: Request):
    """Default entry point: opens the primary Quran Cairo player."""
    return RedirectResponse(url="/listen/quran-cairo", status_code=302)


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Allow crawlers (classic + AI), block only private/admin/stream endpoints."""
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /admin\n"
        "Disallow: /dashboard\n"
        "Disallow: /live\n"
        "Disallow: /station/\n"
        "Disallow: /playlist.m3u\n"
        "Disallow: /live.m3u\n"
        "\n"
        f"Sitemap: {CANONICAL_BASE}/sitemap.xml\n"
    )


@app.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap_xml():
    """XML sitemap over canonical listen pages (one entry per station)."""
    urls = [f"{CANONICAL_BASE}/listen/{s['id']}" for s in engine.get_all_stations_status()]
    # Root redirect goes to quran-cairo; list the canonical listen URL first.
    urls = [f"{CANONICAL_BASE}/listen/quran-cairo"] + [u for u in urls if not u.endswith("/listen/quran-cairo")]
    entries = "\n".join(
        f"  <url><loc>{u}</loc><changefreq>always</changefreq><priority>0.9</priority></url>"
        for u in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# Serve /static (og share cards, any future assets) from the volume-mounted directory.
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent.parent / "static"),
    name="static",
)

@app.api_route("/dashboard", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serves the single-page web dashboard."""
    static_file = Path("/app/static/dashboard.html")
    if not static_file.exists():
        # Fallback for development / local
        static_file = Path(__file__).parent.parent / "static" / "dashboard.html"
    
    if static_file.exists():
        content = static_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse("<h1>OmniRadio Multi-Station Studio</h1><p>Dashboard file missing.</p>")

STATION_THEMES = {
    "quran-cairo": {
        "bg1": "#064e3b",
        "bg2": "#022c22",
        "accent": "#f59e0b",
        "glow": "rgba(245, 158, 11, 0.28)"
    },
    "abdulbasit": {
        "bg1": "#450a0a",
        "bg2": "#1c0404",
        "accent": "#fbbf24",
        "glow": "rgba(251, 191, 36, 0.28)"
    },
    "alminshawi": {
        "bg1": "#0f2b38",
        "bg2": "#081c24",
        "accent": "#2dd4bf",
        "glow": "rgba(45, 212, 191, 0.28)"
    },
    "alhussary": {
        "bg1": "#1e1b4b",
        "bg2": "#09071c",
        "accent": "#f59e0b",
        "glow": "rgba(245, 158, 11, 0.28)"
    },
    "alafasi": {
        "bg1": "#0e374e",
        "bg2": "#061b27",
        "accent": "#38bdf8",
        "glow": "rgba(56, 189, 248, 0.28)"
    },
    "local-library": {
        "bg1": "#291804",
        "bg2": "#120a01",
        "accent": "#f59e0b",
        "glow": "rgba(245, 158, 11, 0.28)"
    }
}

@app.api_route("/listen/{station_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_station_player(station_id: str, request: Request):
    """Serves a dedicated, beautiful themed web player for a specific station."""
    relay = engine.get_relay(station_id)
    if not relay:
        raise HTTPException(status_code=404, detail="Station not found")
    
    template_file = Path("/app/static/station_player.html")
    if not template_file.exists():
        template_file = Path(__file__).parent.parent / "static" / "station_player.html"
    
    if not template_file.exists():
        raise HTTPException(status_code=500, detail="Player template missing")

    theme = STATION_THEMES.get(station_id, {
        "bg1": "#064e3b",
        "bg2": "#022c22",
        "accent": "#f59e0b",
        "glow": "rgba(245, 158, 11, 0.25)"
    })

    html = template_file.read_text(encoding="utf-8")
    html = html.replace("{{STATION_ID}}", station_id)
    html = html.replace("{{STATION_NAME}}", relay.name)
    html = html.replace("{{STATION_CATEGORY}}", relay.config.get("category", "Quran"))
    html = html.replace("{{STATION_DESC}}", relay.config.get("description", "بث حي مستمر على مدار 24 ساعة"))
    html = html.replace("{{STATION_ICON}}", relay.config.get("icon", "📖"))

    # SEO/GEO: one canonical identity regardless of which domain/proxy served this page.
    canonical_url = f"{CANONICAL_BASE}/listen/{station_id}"
    stream_url = f"{CANONICAL_BASE}/station/{station_id}"
    og_image = f"{CANONICAL_BASE}/static/og/{station_id}.png"
    html = html.replace("{{CANONICAL_URL}}", canonical_url)
    html = html.replace("{{OG_IMAGE}}", og_image)

    # Stacked schema.org JSON-LD: RadioStation (entity) + RadioBroadcastService (live stream)
    # + Organization (operator) + WebSite. This is the primary GEO signal — it tells classic
    # and generative engines this is a named, citable radio station, not just an HTML page.
    station_name = relay.name
    station_desc = relay.config.get("description", "بث حي مستمر على مدار 24 ساعة")
    station_cat = relay.config.get("category", "Quran")
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "RadioStation",
                "@id": f"{canonical_url}#station",
                "name": station_name,
                "url": canonical_url,
                "description": station_desc,
                "image": og_image,
                "genre": station_cat,
                "inLanguage": "ar",
                "logo": f"{CANONICAL_BASE}/static/og/{station_id}.png",
                "sameAs": [stream_url],
                "parentOrganization": {"@id": f"{CANONICAL_BASE}#organization"},
            },
            {
                "@type": "RadioBroadcastService",
                "@id": f"{canonical_url}#service",
                "name": f"{station_name} — البث المباشر",
                "broadcastDisplayName": station_name,
                "url": stream_url,
                "description": station_desc,
                "genre": station_cat,
                "inLanguage": "ar",
                "serviceType": "Live audio stream",
                "provider": {"@id": f"{canonical_url}#station"},
                "broadcaster": {"@id": f"{CANONICAL_BASE}#organization"},
                "areaServed": {"@type": "Country", "name": "Worldwide"},
                "availableChannel": {"@type": "RadioChannel", "broadcastServiceTier": "Free"},
            },
            {
                "@type": "Organization",
                "@id": f"{CANONICAL_BASE}#organization",
                "name": "OmniRadio",
                "url": f"{CANONICAL_BASE}",
                "logo": {"@type": "ImageObject", "url": f"{CANONICAL_BASE}/static/og/{station_id}.png"},
                "sameAs": ["https://github.com/xecod-dev/omniradio", "https://radio.serastores.com"],
            },
            {
                "@type": "WebSite",
                "@id": f"{CANONICAL_BASE}#website",
                "name": "OmniRadio — إذاعة القرآن الكريم",
                "url": f"{CANONICAL_BASE}",
                "inLanguage": "ar",
                "publisher": {"@id": f"{CANONICAL_BASE}#organization"},
            },
        ],
    }
    html = html.replace("{{JSONLD_SCHEMA}}", json.dumps(jsonld, ensure_ascii=False))

    # Allowed stations for the channel switcher dropdown (id/name/icon/category only — no secrets)
    stations_meta = [
        {"id": s["id"], "name": s["name"], "icon": s["icon"], "category": s["category"]}
        for s in engine.get_all_stations_status()
        if s["id"] == station_id or engine.get_relay(s["id"]) is not None
    ]
    stations_meta.sort(key=lambda x: x["name"])
    html = html.replace("{{STATIONS_JSON}}", json.dumps(stations_meta, ensure_ascii=False))
    html = html.replace("{{THEME_BG1}}", theme["bg1"])
    html = html.replace("{{THEME_BG2}}", theme["bg2"])
    html = html.replace("{{THEME_ACCENT}}", theme["accent"])
    html = html.replace("{{THEME_GLOW}}", theme["glow"])

    return HTMLResponse(content=html)

@app.get("/quran")
async def shortcut_quran():
    return RedirectResponse(url="/listen/quran-cairo", status_code=302)

@app.get("/abdulbasit")
async def shortcut_abdulbasit():
    return RedirectResponse(url="/listen/abdulbasit", status_code=302)

@app.get("/minshawi")
async def shortcut_minshawi():
    return RedirectResponse(url="/listen/alminshawi", status_code=302)

@app.get("/hussary")
async def shortcut_hussary():
    return RedirectResponse(url="/listen/alhussary", status_code=302)

@app.get("/afasi")
async def shortcut_afasi():
    return RedirectResponse(url="/listen/alafasi", status_code=302)

@app.get("/library")
async def shortcut_library():
    return RedirectResponse(url="/listen/local-library", status_code=302)

@app.get("/healthz")
async def healthz():
    return {"status": "healthy", "service": "omniradio", "stations_count": len(engine.relays)}

@app.api_route("/playlist.m3u", methods=["GET", "HEAD"])
async def generate_master_playlist(request: Request):
    """Generates master M3U playlist file containing ALL stations for Windows Media Player, VLC, and Winamp."""
    base_url = get_base_url(request)
    lines = ["#EXTM3U", "# OmniRadio Master Multi-Station Playlist", ""]
    
    stations = engine.get_all_stations_status()
    for s in stations:
        name = f"{s.get('icon', '📻')} {s.get('name', s['id'])}"
        stream_url = f"{base_url}/station/{s['id']}"
        lines.append(f"#EXTINF:-1,{name}")
        lines.append(stream_url)
        lines.append("")

    content = "\n".join(lines)
    if request.method == "HEAD":
        return Response(status_code=200, media_type="audio/x-mpegurl")
    return Response(
        content=content,
        media_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": 'attachment; filename="radio_stations.m3u"',
            "Cache-Control": "no-cache"
        }
    )

@app.api_route("/live.m3u", methods=["GET", "HEAD"])
async def generate_live_playlist(request: Request):
    """Generates an M3U file for the default live stream."""
    base_url = get_base_url(request)
    lines = [
        "#EXTM3U",
        "#EXTINF:-1, OmniRadio Live Broadcast",
        f"{base_url}/live"
    ]
    if request.method == "HEAD":
        return Response(status_code=200, media_type="audio/x-mpegurl")
    return Response(
        content="\n".join(lines),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": 'attachment; filename="live.m3u"'}
    )

@app.api_route("/station/{station_id}.m3u", methods=["GET", "HEAD"])
async def generate_single_station_playlist(station_id: str, request: Request):
    """Generates an M3U file for a specific station."""
    relay = engine.get_relay(station_id)
    if not relay:
        raise HTTPException(status_code=404, detail="Station not found")
    
    base_url = get_base_url(request)
    lines = [
        "#EXTM3U",
        f"#EXTINF:-1, {relay.config.get('icon', '📻')} {relay.name}",
        f"{base_url}/station/{station_id}"
    ]
    if request.method == "HEAD":
        return Response(status_code=200, media_type="audio/x-mpegurl")
    return Response(
        content="\n".join(lines),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{station_id}.m3u"'}
    )

async def _stream_generator(relay):
    """Subscribes to station relay and yields audio MP3 chunks."""
    queue = relay.subscribe()
    try:
        while True:
            chunk = await queue.get()
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        pass
    finally:
        relay.unsubscribe(queue)

def safe_ascii_header(val: str, default: str = "OmniRadio Station") -> str:
    """Ensures HTTP header values conform to latin-1 / ASCII standard."""
    if not val:
        return default
    try:
        val.encode("latin-1")
        return val
    except Exception:
        # Strip or sanitize non-latin-1 characters
        sanitized = "".join(c for c in val if ord(c) < 128).strip()
        return sanitized if sanitized else default

@app.api_route("/live", methods=["GET", "HEAD"])
async def stream_live(request: Request):
    """Streams the primary/first station."""
    relays = list(engine.relays.values())
    if not relays:
        raise HTTPException(status_code=503, detail="No stations configured")
    relay = relays[0]
    icy_name = safe_ascii_header(relay.config.get("name_en", relay.name), relay.station_id)
    icy_genre = safe_ascii_header(relay.config.get("category", "Radio"), "Radio")
    
    headers = {
        "Content-Type": "audio/mpeg",
        "icy-name": icy_name,
        "icy-genre": icy_genre,
        "icy-br": "128",
        "Accept-Ranges": "none",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive"
    }

    if request.method == "HEAD":
        return Response(status_code=200, media_type="audio/mpeg", headers=headers)

    quotes_manager.increment_listener("live")
    return StreamingResponse(
        _stream_generator(relay),
        media_type="audio/mpeg",
        headers=headers
    )

@app.api_route("/station/{station_id}", methods=["GET", "HEAD"])
async def stream_station(station_id: str, request: Request):
    """Streams a specific station by ID with full ICY metadata support for WMP/VLC."""
    relay = engine.get_relay(station_id)
    if not relay:
        raise HTTPException(status_code=404, detail="Station not found")

    icy_name = safe_ascii_header(relay.config.get("name_en", relay.name), relay.station_id)
    icy_genre = safe_ascii_header(relay.config.get("category", "Radio"), "Radio")
    
    headers = {
        "Content-Type": "audio/mpeg",
        "icy-name": icy_name,
        "icy-genre": icy_genre,
        "icy-br": str(relay.config.get("bitrate", 128)),
        "Accept-Ranges": "none",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive"
    }

    if request.method == "HEAD":
        return Response(status_code=200, media_type="audio/mpeg", headers=headers)

    quotes_manager.increment_listener(station_id)
    return StreamingResponse(
        _stream_generator(relay),
        media_type="audio/mpeg",
        headers=headers
    )

# ==================== Admin Authentication ====================

def get_expected_admin_token() -> str:
    secret = config_manager.get_admin_password()
    return hashlib.sha256(f"radio_admin_{secret}".encode()).hexdigest()

def is_admin(request: Request) -> bool:
    expected = get_expected_admin_token()
    token = request.headers.get("X-Admin-Token") or request.cookies.get("radio_admin_token")
    return token == expected

def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin password authentication required")

class AdminLoginPayload(BaseModel):
    password: str

@app.post("/api/admin/login")
async def api_admin_login(payload: AdminLoginPayload, response: Response):
    """Authenticates admin and sets HTTP-only session cookie."""
    if payload.password == config_manager.get_admin_password():
        token = get_expected_admin_token()
        response.set_cookie(
            key="radio_admin_token",
            value=token,
            httponly=True,
            max_age=86400 * 30,
            samesite="lax"
        )
        return {"status": "authenticated", "token": token}
    raise HTTPException(status_code=403, detail="Invalid admin password")

@app.get("/api/admin/verify")
async def api_admin_verify(request: Request):
    return {"authenticated": is_admin(request)}

@app.post("/api/admin/logout")
async def api_admin_logout(response: Response):
    response.delete_cookie("radio_admin_token")
    return {"status": "logged_out"}

@app.get("/admin")
async def serve_admin_portal():
    """Admin shortcut: opens studio dashboard with admin prompt."""
    return RedirectResponse(url="/dashboard?admin=true", status_code=302)

# ==================== API Endpoints ====================

@app.get("/api/stations")
async def api_get_stations():
    stations = engine.get_all_stations_status()
    for s in stations:
        s["all_time_listeners"] = quotes_manager.get_all_time_listeners(s["id"])
    return stations

@app.get("/api/quotes/random")
async def api_get_random_quote():
    quote = quotes_manager.get_random_quote()
    if not quote:
        return {"id": 0, "content": "من صَلُحَتْ صلاته صلح سائر عمله وفاز فوزا عظيما", "total_quotes": 0}
    return quote

# ── Azkar Counter (per-day shared) ──
import datetime
AZKAR_DATA_PATH = Path("/app/data/azkar.json")

def _today_key() -> str:
    return datetime.date.today().isoformat()

def _load_azkar() -> dict:
    if AZKAR_DATA_PATH.exists():
        try:
            return json.loads(AZKAR_DATA_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}

def _save_azkar(data: dict):
    AZKAR_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    AZKAR_DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

@app.get("/api/azkar")
async def api_azkar_get():
    """Return today's total azkar count."""
    data = _load_azkar()
    return {"date": _today_key(), "count": data.get("count", 0)}

@app.post("/api/azkar")
async def api_azkar_post():
    """Increment today's total azkar count by 1 (shared across all visitors)."""
    data = _load_azkar()
    today = _today_key()
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] = data.get("count", 0) + 1
    _save_azkar(data)
    return {"date": today, "count": data["count"]}

# ── Prayer Times ──
import datetime
PRAYER_TIMES_CACHE = {"key": None, "data": None, "expires": 0}
PRAYER_NAMES_AR = {"Fajr": "الفجر", "Sunrise": "الشروق", "Dhuhr": "الظهر",
                   "Asr": "العصر", "Maghrib": "المغرب", "Isha": "العشاء"}
ALADHAN_TIMEOUT = 10.0

def _aladhan_get(url: str) -> Optional[dict]:
    """GET a JSON payload from the Aladhan prayer API."""
    import urllib.request as _urllib_request
    try:
        req = _urllib_request.Request(url, headers={"User-Agent": "OmniRadio-Relay/2.0"})
        with _urllib_request.urlopen(req, timeout=ALADHAN_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload if payload.get("code") == 200 else None
    except Exception as exc:
        logger.warning("Aladhan API request failed (%s): %s", url, exc)
        return None

def _aladhan_timings(lat: float, lng: float, api_date: str, tz: str) -> Optional[dict]:
    """Return a normalized prayer-times payload for coordinates.

    method=5 = Egyptian General Authority of Survey (correct for Egypt;
    method=2 ISNA is a North American method and shifts Isha ~12 min early).
    """
    payload = _aladhan_get(
        f"https://api.aladhan.com/v1/timings/{api_date}"
        f"?latitude={lat}&longitude={lng}&method=5&timezonestring={tz}"
    )
    if not payload or "data" not in payload:
        return None

    data = payload["data"]
    raw = data.get("timings", {})
    hijri = data.get("date", {}).get("hijri", {})
    meta = data.get("meta", {})
    return {
        "date": data.get("date", {}).get("readable", ""),
        "hijri": f"{hijri.get('day', '')} {hijri.get('month', {}).get('ar', '')} {hijri.get('year', '')} هـ",
        "timings": {
            PRAYER_NAMES_AR[key]: raw.get(key, "").split(" ")[0]
            for key in PRAYER_NAMES_AR if raw.get(key)
        },
        "timezone": meta.get("timezone", ""),
        "latitude": round(lat, 4),
        "longitude": round(lng, 4),
    }

@app.get("/api/prayer-times")
async def api_prayer_times(
    request: Request,
    lat: float = Query(0, ge=-90, le=90),
    lng: float = Query(0, ge=-180, le=180),
    city: str = Query("", max_length=100),
    country: str = Query("", max_length=100),
    tz: str = Query("Africa/Cairo", max_length=64),
):
    """Return today's prayer times for a browser-reported location or a city."""
    from datetime import date as _date
    today = _date.today()
    api_date = today.strftime("%d-%m-%Y")
    cache_key = f"{round(lat, 3)}:{round(lng, 3)}:{city.lower()}:{country.lower()}:{api_date}"

    if PRAYER_TIMES_CACHE.get("key") == cache_key and PRAYER_TIMES_CACHE["expires"] > time.time():
        result = dict(PRAYER_TIMES_CACHE["data"])
        result["cached"] = True
        return result

    if lat == 0 and lng == 0 and city:
        result = _aladhan_get(
            f"https://api.aladhan.com/v1/timingsByCity/{api_date}"
            f"?city={city}&country={country or 'Egypt'}&method=5"
        )
        if result and "data" in result:
            data = result["data"]
            raw = data.get("timings", {})
            hijri = data.get("date", {}).get("hijri", {})
            meta = data.get("meta", {})
            # Aladhan's city lookup sometimes returns a bogus fallback
            # (8.8888888 / 7.7777777). Hide it when it is not plausible,
            # e.g. the exact fallback pair or anything far from reality.
            lat_out, lng_out = None, None
            try:
                m_lat = float(meta.get("latitude", 0))
                m_lng = float(meta.get("longitude", 0))
                plausible = (
                    -90 <= m_lat <= 90 and -180 <= m_lng <= 180
                    and not (abs(m_lat - 8.8888888) < 0.01 and abs(m_lng - 7.7777777) < 0.01)
                )
                if plausible:
                    lat_out, lng_out = round(m_lat, 4), round(m_lng, 4)
            except (TypeError, ValueError):
                pass
            result = {
                "date": data.get("date", {}).get("readable", ""),
                "hijri": f"{hijri.get('day', '')} {hijri.get('month', {}).get('ar', '')} {hijri.get('year', '')} هـ",
                "timings": {
                    PRAYER_NAMES_AR[key]: raw.get(key, "").split(" ")[0]
                    for key in PRAYER_NAMES_AR if raw.get(key)
                },
                "timezone": meta.get("timezone", ""),
                "latitude": lat_out,
                "longitude": lng_out,
            }
        else:
            return {"error": "تعذر جلب أوقات الصلاة لهذه المدينة"}
    elif lat != 0 or lng != 0:
        result = _aladhan_timings(lat, lng, api_date, tz)
        if not result:
            return {"error": "تعذر جلب أوقات الصلاة لهذا الموقع"}
    else:
        return {"error": "لم يتم تحديد موقع", "needs_location": True}

    PRAYER_TIMES_CACHE.update({"key": cache_key, "data": result, "expires": time.time() + 3600})
    return result

@app.post("/api/quotes/sync")
async def api_sync_quotes(request: Request):
    require_admin(request)
    count = await quotes_manager.sync_from_turso()
    return {"status": "synced", "count": count}

class StationCreate(BaseModel):
    id: str
    name: str
    name_en: Optional[str] = ""
    category: Optional[str] = "General"
    description: Optional[str] = ""
    icon: Optional[str] = "📻"
    sources: List[str]
    bitrate: Optional[int] = 128

@app.post("/api/stations")
async def api_create_station(payload: StationCreate, request: Request):
    require_admin(request)
    try:
        new_station = config_manager.add_station(payload.dict())
        await engine.reload_station(payload.id)
        return {"status": "created", "station": new_station}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/stations/{station_id}")
async def api_update_station(station_id: str, payload: Dict[str, Any], request: Request):
    require_admin(request)
    updated = config_manager.update_station(station_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Station not found")
    await engine.reload_station(station_id)
    return {"status": "updated", "station": updated}

@app.delete("/api/stations/{station_id}")
async def api_delete_station(station_id: str, request: Request):
    require_admin(request)
    success = config_manager.delete_station(station_id)
    if not success:
        raise HTTPException(status_code=404, detail="Station not found")
    await engine.reload_station(station_id)
    return {"status": "deleted", "station_id": station_id}

@app.post("/api/stations/{station_id}/switch-source")
async def api_switch_station_source(station_id: str, request: Request, target_idx: int = Query(..., ge=0)):
    require_admin(request)
    relay = engine.get_relay(station_id)
    if not relay:
        raise HTTPException(status_code=404, detail="Station not found")
    
    success = await relay.switch_source(target_idx)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid source index")
    
    return {
        "status": "switched",
        "station_id": station_id,
        "active_source_idx": relay.active_source_idx,
        "active_source": relay.active_source
    }

@app.post("/api/upload")
async def api_upload_file(
    request: Request,
    file: UploadFile = File(...),
    folder: str = Form("uploads")
):
    """Handles single MP3 upload or ZIP file archive with automatic unzipping."""
    require_admin(request)
    try:
        content = await file.read()
        res = audio_manager.save_uploaded_file(file.filename, content, target_subfolder=folder)
        return {"status": "success", "result": res}
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")

@app.get("/api/files")
async def api_list_files(folder: str = ""):
    return audio_manager.list_files(folder)

@app.delete("/api/files")
async def api_delete_file(request: Request, path: str = Query(...)):
    require_admin(request)
    success = audio_manager.delete_file(path)
    if not success:
        raise HTTPException(status_code=404, detail="File not found or protected")
    return {"status": "deleted", "path": path}

@app.get("/status-json.xsl")
async def icecast_status_json(request: Request):
    """Icecast-compatible /status-json.xsl stats page for radio directories.

    Internet-Radio.com, Streema, myTuner, Radio Garden etc. only list
    Shoutcast/Icecast stations and read this standard JSON endpoint to
    discover mounts, listeners, bitrate and stream URLs. We are a custom
    HTTP MP3 relay, so we expose the same shape they expect — one source
    block per station (the /station/<id> mount).
    """
    base_url = get_base_url(request)
    sources = []
    total_listeners = 0
    server_start_ts = time.time()
    for relay in engine.relays.values():
        info = relay.get_status_info()
        total_listeners += int(info.get("listeners", 0))
        bitrate_kbps = int(relay.config.get("bitrate", 128))
        server_start_ts = min(server_start_ts, relay.source_start_time)
        sources.append({
            "admin": "radio@serastores.com",
            "audio_info": f"bitrate={bitrate_kbps};channels=2;samplerate=44100",
            "bitrate": bitrate_kbps,
            "genre": relay.config.get("category", "Radio"),
            "listener_peak": int(info.get("listeners", 0)),
            "listeners": int(info.get("listeners", 0)),
            "listenurl": f"{base_url}/station/{relay.station_id}",
            "mount": f"/station/{relay.station_id}",
            "server_name": relay.config.get("name_en", relay.name),
            "server_type": "audio/mpeg",
            "stream_start": datetime.datetime.fromtimestamp(
                relay.source_start_time, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "status": info.get("status", "starting"),
        })
    return JSONResponse({
        "icestats": {
            "admin": "radio@serastores.com",
            "host": base_url,
            "location": "Cairo, Egypt",
            "server_id": "OmniRadio (Icecast-compatible)",
            "server_start": datetime.datetime.fromtimestamp(
                server_start_ts, tz=datetime.timezone.utc,
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "listeners": total_listeners,
            "source": sources,
        }
    })

# Also expose the classic Icecast status page for human browsing
@app.get("/status.xsl", response_class=HTMLResponse)
async def icecast_status_xsl(request: Request):
    """Human-readable Icecast-style status page (same data as status-json.xsl)."""
    base_url = get_base_url(request)
    rows = []
    total_listeners = 0
    for relay in engine.relays.values():
        info = relay.get_status_info()
        listeners = int(info.get("listeners", 0))
        total_listeners += listeners
        bitrate_kbps = int(relay.config.get("bitrate", 128))
        name = relay.config.get("name_en", relay.name)
        rows.append(f"""<tr>
            <td><a href="{base_url}/station/{relay.station_id}">/station/{relay.station_id}</a></td>
            <td>{name}</td>
            <td>{bitrate_kbps} kbps</td>
            <td>{listeners}</td>
            <td>{info.get('status', 'starting')}</td>
        </tr>""")
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>OmniRadio — Stream Status (Icecast-compatible)</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; background: #0b1220; color: #e2e8f0; }}
h1 {{ color: #f59e0b; }}
table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
th, td {{ border: 1px solid #334155; padding: 0.5rem 0.75rem; text-align: left; }}
th {{ background: #1e293b; }}
a {{ color: #38bdf8; }}
.meta {{ color: #94a3b8; font-size: 0.9em; }}
</style></head><body>
<h1>OmniRadio — Stream Status</h1>
<p class="meta">Server: {base_url} · Total listeners: {total_listeners} ·
Stations: {len(engine.relays)} · Machine-readable: <a href="{base_url}/status-json.xsl">/status-json.xsl</a></p>
<table>
<tr><th>Mount</th><th>Station</th><th>Bitrate</th><th>Listeners</th><th>Status</th></tr>
{''.join(rows)}
</table>
</body></html>"""
    return HTMLResponse(content=html)

@app.get("/api/status")
async def api_get_status(request: Request):
    """Returns server telemetry, IP addresses for LAN, Tailscale, DuckDNS, and FTP connection info."""
    base_url = get_base_url(request)
    admin_auth = is_admin(request)
    
    lan_ip = "172.30.0.90"
    tailscale_ip = "100.64.1.90"
    duckdns_domain = "islamradio.duckdns.org"
    public_ip = "41.196.65.182"
    
    # FTP details are sensitive credentials: only exposed to authenticated admins
    ftp_info = None
    if admin_auth:
        ftp_info = {
            "host": lan_ip,
            "tailscale_host": tailscale_ip,
            "duckdns_host": duckdns_domain,
            "port": server_cfg.get("ftp_port", 2121),
            "user": server_cfg.get("ftp_user", "radio"),
            "password": server_cfg.get("ftp_password", ""),
            "url_lan": f"ftp://{server_cfg.get('ftp_user', 'radio')}:{server_cfg.get('ftp_password', '')}@{lan_ip}:{server_cfg.get('ftp_port', 2121)}",
            "url_tailscale": f"ftp://{server_cfg.get('ftp_user', 'radio')}:{server_cfg.get('ftp_password', '')}@{tailscale_ip}:{server_cfg.get('ftp_port', 2121)}",
            "url_duckdns": f"ftp://{server_cfg.get('ftp_user', 'radio')}:{server_cfg.get('ftp_password', '')}@{duckdns_domain}:{server_cfg.get('ftp_port', 2121)}"
        }

    return {
        "server_name": server_cfg.get("name", "OmniRadio Studio"),
        "base_url": base_url,
        "is_admin": admin_auth,
        "lan_ip": lan_ip,
        "tailscale_ip": tailscale_ip,
        "duckdns_domain": duckdns_domain,
        "public_ip": public_ip,
        "port": server_cfg.get("port", 9000),
        "ftp": ftp_info,
        "endpoints": {
            "master_playlist_m3u": f"{base_url}/playlist.m3u",
            "live_stream": f"{base_url}/live",
            "live_m3u": f"{base_url}/live.m3u",
            "duckdns_master_m3u": f"http://{duckdns_domain}:9000/playlist.m3u",
            "duckdns_live": f"http://{duckdns_domain}:9000/live"
        },
        "total_listeners": sum(r.listeners_count for r in engine.relays.values()),
        "current_listeners": sum(r.listeners_count for r in engine.relays.values()),
        "all_time_listeners": quotes_manager.get_all_time_listeners(),
        "total_stations": len(engine.relays),
        "version": APP_VERSION,
        "commit": GIT_SHA,
        "updated": APP_UPDATED
    }

@app.get("/api/version")
async def api_get_version(request: Request):
    """Public version metadata so users/clients can detect when a new edit is released."""
    base_url = get_base_url(request)
    return {
        "version": APP_VERSION,
        "commit": GIT_SHA,
        "updated": APP_UPDATED,
        "station_count": len(engine.relays),
        "stage": "live" if GIT_SHA != "local" else "dev",
        "download_url": f"{base_url}/playlist.m3u",
        "endpoints": {
            "master_playlist_m3u": f"{base_url}/playlist.m3u",
            "live_stream": f"{base_url}/live",
            "api": f"{base_url}/api/status"
        }
    }
