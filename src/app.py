import os
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
    password=server_cfg.get("ftp_password", "RadioMaster2026!")
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

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
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

    base_url = get_base_url(request)
    html = template_file.read_text(encoding="utf-8")
    html = html.replace("{{STATION_ID}}", station_id)
    html = html.replace("{{STATION_NAME}}", relay.name)
    html = html.replace("{{STATION_CATEGORY}}", relay.config.get("category", "Quran"))
    html = html.replace("{{STATION_DESC}}", relay.config.get("description", "بث حي مستمر على مدار 24 ساعة"))
    html = html.replace("{{STATION_ICON}}", relay.config.get("icon", "📖"))
    html = html.replace("{{PAGE_URL}}", f"{base_url}/listen/{station_id}")
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
    return RedirectResponse(url="/?admin=true", status_code=302)

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
            "password": server_cfg.get("ftp_password", "RadioMaster2026!"),
            "url_lan": f"ftp://{server_cfg.get('ftp_user', 'radio')}:{server_cfg.get('ftp_password', 'RadioMaster2026!')}@{lan_ip}:{server_cfg.get('ftp_port', 2121)}",
            "url_tailscale": f"ftp://{server_cfg.get('ftp_user', 'radio')}:{server_cfg.get('ftp_password', 'RadioMaster2026!')}@{tailscale_ip}:{server_cfg.get('ftp_port', 2121)}",
            "url_duckdns": f"ftp://{server_cfg.get('ftp_user', 'radio')}:{server_cfg.get('ftp_password', 'RadioMaster2026!')}@{duckdns_domain}:{server_cfg.get('ftp_port', 2121)}"
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
        "total_stations": len(engine.relays)
    }
