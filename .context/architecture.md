# Architecture

## Tech Stack
- Language(s): Python 3.14 (Alpine-based Docker image)
- Framework(s): FastAPI + Uvicorn (single worker, single process)
- Database: SQLite (`/app/data/quotes.db` — quotes + analytics counters)
- Audio engine: FFmpeg (one FFmpeg subprocess per station relay, reading from pipe)
- Infra / deployment: Docker Engine + Docker Compose v2
- FTP: pyftpdlib (embedded FTP server, port 2121)
- External APIs: aladhan.com (prayer times), archive.org & mp3quran.net (audio), Turso/SQLite (quotes)
- YP directory: YP client to internet-radio.com Icecast directory (optional, `YP_ENABLED=1`)

## Runtime Config
- HTTP port: 9000
- FTP port: 2121 (passive 2122–2125)
- Audio dir: `/app/audio` (volume-mounted from `/home/saas/radio/audio`)
- Config: `/app/config/stations.json` (volume-mounted)
- Secrets: `/app/config/secrets.json` (gitignored, volume-mounted, overlays stations.json creds)
- Data: `/app/data/` (SQLite db, volume-mounted)

## Directory Structure
```
radio/
├── config/
│   ├── stations.json          # Server + station config (11 stations)
│   ├── secrets.json           # Gitignored credentials (admin+ftp password)
│   └── station_abouts.json    # Per-station Arabic About content (optional)
├── src/
│   ├── app.py                 # FastAPI endpoints & streaming router
│   ├── engine.py              # Multi-source relay engine with auto-failover + idle-gating
│   ├── ftp_server.py          # Embedded pyftpdlib FTP server
│   ├── audio_manager.py       # ZIP extractor, file indexer, standby chime
│   ├── config.py              # Config manager (loads stations.json + secrets.json)
│   ├── quotes_manager.py      # SQLite quotes DB + Turso sync
│   └── yp_client.py           # Icecast-compatible YP directory registration
├── static/
│   ├── dashboard.html         # Studio management web UI (self-contained, ~1900 lines)
│   └── station_player.html    # Themed dedicated mobile station player
├── audio/                     # Volume-mounted audio storage
│   ├── quran/
│   ├── ambient/
│   ├── cache/                 # Pre-cached archive.org stations
│   └── uploads/
├── data/                      # Volume-mounted: quotes.db, azkar.json
├── Dockerfile
└── docker-compose.yml
```

## Key Modules
| Module | Responsibility | Notes |
|---|---|---|
| `src/app.py` | FastAPI app: HTTP routes, auth, streaming, prayer times | 1092 lines; / redirects to /listen/quran-cairo |
| `src/engine.py` | Station relay: FFmpeg management, failover, idle-gating | CHUNK_SIZE=4096, IDLE_GATE_SECONDS=60, RING_BUFFER_SIZE=16 |
| `src/config.py` | Config load/save (stations.json + secrets.json overlay) | Read at startup only |
| `src/quotes_manager.py` | Local SQLite quotes + Turso cloud sync (daily) | Opens connection per-call (no connection pool!) |
| `src/yp_client.py` | Icecast YP directory client (optional) | Uses `requests` library via run_in_executor |
| `static/dashboard.html` | Admin dashboard (vanilla JS, self-contained) | Polls /api/stations every 3s |

## Data Model / Schema Summary
### `quotes.db` (SQLite)
- `quotes(id INTEGER PK, content TEXT, synced_at TIMESTAMP)` — Islamic spiritual quotes
- `analytics(key TEXT PK, value INTEGER)` — counters: `all_time_listeners`, `station_{id}_all_time`, `last_quotes_sync`

### `azkar.json` — simple day-keyed JSON `{date, count}` for azkar counter

## 11 Configured Stations
1. `quran-cairo` — Radiojar live stream → Zeno FM → local
2. `abdulbasit` — Qurango → archive.org → local
3. `alminshawi` — Qurango → archive.org → local
4. `alhussary` — Qurango → archive.org → local
5. `alafasi` — Qurango → local
6. `albanna` — archive.org → mp3quran → local
7. `ammar-almulla` — archive.org → local cache → local
8. `bandar-balila` — archive.org → mp3quran → local
9. `ahmad-tamim` — archive.org → local cache → local
10. `local-library` — local audio dirs (no remote, always runs)
11. `AdelRayan` — archive.org → local

## Known Constraints & Conventions
- **Single Uvicorn worker** — no multi-process; all async; FFmpeg runs as subprocesses
- **SQLite** per-call connection (see ID-004); no WAL mode; not thread-safe by default
- **Idle-gating**: remote sources auto-pause after 60s with no listeners; local sources never gate
- **dashboard.html** polls `/api/stations` every 3 seconds — will accumulate load if many browser tabs open
- **Authentication**: cookie-based with SHA256 token; no expiry beyond 30-day max-age
- **CANONICAL_BASE** env var controls all public URLs (SEO, JSON-LD)
- **Memory limit**: 4 GiB (`mem_limit: 4g`) — MUST stay below this as single-process leak will crash
- All station bitrates are 64 kbps mono (`audio_channels: 1`)
