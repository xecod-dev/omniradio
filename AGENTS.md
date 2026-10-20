# AGENTS.md — Project Memory Pointer

> This file is the entry point for any AI agent working in this repo.
> Read this FIRST, then read the files it points to, before doing anything else.

## Memory files
- `.context/architecture.md` — system specs, stack, directory tree, schemas
- `.context/active_issues.md` — open bugs, tech debt, pending work
- `.context/history_log.md` — append-only decision/change log

## Quick facts
- Project: OmniRadio Multi-Station Studio (Islamic Quran radio relay)
- Stack: Python 3.14 on Alpine, FastAPI + Uvicorn, FFmpeg, SQLite, Docker
- Primary entry points: `src/app.py` (FastAPI), `src/engine.py` (relay engine)
- Runtime port: 9000 (HTTP), 2121 (FTP), 2122-2125 (FTP passive)
- Container: `radio-app` (single uvicorn process, 10 stations, 9-10 FFmpeg relays)

## Latest Session Summaries

## Session Summary — 2026-10-03
- Completed:
  1. Diagnosed severe memory exhaustion: uvicorn parent process at 3.95 GiB RSS (4 GiB limit), D-state disk sleep, 77 stuck healthcheck curl processes, container unhealthy — causing "loads loading".
  2. Restarted container → immediate relief (RSS dropped to ~70 MiB, TTFB < 5ms).
  3. Fixed Dockerfile HEALTHCHECK: added `--max-time 5 --connect-timeout 3` (ID-002 resolved).
  4. Replaced `requests` library in yp_client.py with stdlib `urllib.request` + removed from requirements.txt (ID-006 resolved).
  5. Dashboard poll interval: 3s → 10s + tab-hidden pause (ID-005 resolved).
  6. Added `MALLOC_TRIM_THRESHOLD_=131072` + `MALLOC_MMAP_THRESHOLD_=131072` to docker-compose.yml.
  7. Added `_memory_watchdog()` async task in app.py: GC + malloc_trim every 60s, SIGTERM at 2800 MiB.
  8. Fixed engine.py syntax error on line 537 (trailing `.` after `asyncio.sleep(5.0)`) (ID-007 resolved).
  9. Fixed idle-gating lifecycle bugs (ID-008): asyncio.wait coroutine tasks, stale subscriber pruning, resume_event clearing, listener-drop detection.
  10. Rebuilt and redeployed image — container healthy, all 11 stations running.
- In progress / incomplete: Root memory leak (ID-001) underlying cause not yet fully identified — watchdog is the mitigation. SQLite connection pooling (ID-004) not yet implemented.
- New issues logged: [ID-007] engine.py syntax error (resolved), [ID-008] idle-gating lifecycle bugs (resolved)
- Decisions made: Multiple — see history_log.md entries "Applied memory-exhaustion mitigations" and "Fixed idle-gating lifecycle bugs".
- Next recommended step: Monitor RSS over 24h. If it still leaks past 2.8 GiB, use `tracemalloc` to pinpoint. Implement SQLite WAL mode + connection pooling (ID-004).

## Session Summary — 2026-10-20 (524 root-caused & fixed; auto-heal watchdog; geo card minimized)
- Completed: (1) Cloudflare 524 (radio.xecod.com Host Error 2026-10-19) root-caused via /proc/1/task/1/wchan = jbd2_log_wait_commit: listener_stats `save()` ran synchronously on EVERY connect on the request thread; idle-gate pause branch was dead code after `continue` (15 ffmpegs 24/7); zombie-queue liveness + wake-on-subscribers>0 caused 5s thrash; mid-stream break catch-22 starved first listeners forever. Fixed all four (background saver thread, gate rewrite consumption-based, wake-on-event-only, fruitless-spawn cooldown, -threads 1, clean kill/reap) — rebuilds 1bce3f3c→ae8edae17. (2) Auto-heal watchdog deployed (PM2 `radio-watchdog`): polls /healthz 20s, docker kill+start after 2 fails, logs watchdog.log; deploy-grace 90s prevents kill during compose recreate. (3) Geo stats card minimized in dashboard (collapsed header + top-5 bars, commits n/a). (4) Repaired config/station_abouts.json stray brace (16 keys valid; do NOT git-restore this file — working copy is richer than HEAD).
- Verified: albanna listener-wake-after-idle = 200 + 278KB audio; 10min+ uptime; 14 ffmpegs serving 33 real consumer sockets @ ~246% CPU; watchdog "Skipping restart" fired correctly during deploy window; public xecod/serastores /healthz 200 fast; curl refresh card OK.
- In progress / incomplete: ID-052 checker-bots keep upstream semi-awake (bounded, not minimal); 24-48h RSS/CPU watch for ID-001 memory regression; commit the working tree (11 modified files + 3 untracked src/scripts) — NOT yet committed!
- New issues logged: ID-049 (resolved), ID-050 (resolved), ID-051 (fixed), ID-052 (open).
- Decisions made: stats disk I/O NEVER on request path; consumption-only liveness; wake only via resume_event; cooldown 30s after fruitless spawns; ffmpeg `-threads 1`; Popen start_new_session; watchdog skips containers younger than 90s.
- Next recommended step: git add/commit the radio tree (explicit paths — backups/ unreadable trap); monitor 24-48h; then ID-052 smoothing only if egress bill still spiked.
