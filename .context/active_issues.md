# Active Issues

### [ID-001] Memory leak in uvicorn parent process (3.95 GiB RSS → 4 GiB limit → disk sleep → site down)
- Status: open
- Severity: blocking
- Location: `src/app.py`, `src/engine.py`, `src/yp_client.py`, Python 3.14/uvicorn internals
- Discovered: 2026-10-03, diagnosed live from container
- Description: The single uvicorn process has grown to 3.95 GiB RSS (99.9% of 4 GiB cgroup limit) in ~16 hours.
  RssAnon=3.94 GiB (pure heap/anonymous memory), VmData=4.84 GiB.
  Process enters disk sleep (D state) when kernel swaps aggressively; all HTTP requests hang,
  healthcheck curl processes pile up (75+ stuck processes), container marked unhealthy.
  The leak was noted in docker-compose.yml comment as "~48 MiB/min over 7h" from the 2026-10-02 incident.
  Likely suspect: audio chunk ring buffers accumulating in asyncio queues, or the `requests` library
  in yp_client.py holding session connection pool open with growing per-connection state,
  or Python 3.14 thread executor tasks not being cleaned up (77 curl healthcheck threads blocked).
- Suggested fix:
  1. **Immediate**: `docker compose restart radio-app` to restore service.
  2. **Short-term**: Switch YP client from `requests` to `urllib` (no session state), add
     `limits.max_connections` to uvicorn config, enable `--limit-concurrency`.
  3. **Medium-term**: Add `MALLOC_TRIM_THRESHOLD_=131072` env var to trim heap after GC.
     Consider memory profiling (`tracemalloc`) to pinpoint the exact allocator leak.
  4. **Long-term**: Switch to `--workers 2` (multiprocessing) so a single leak is bounded
     by per-worker restart, or add a cron/watchdog to restart when RSS > 2 GiB.

### [ID-002] Healthcheck curl processes accumulate (77 stuck curls observed) — RESOLVED
- Status: resolved (2026-10-03 — Dockerfile updated with --max-time 5 --connect-timeout 3)
- Severity: high
- Location: `Dockerfile` HEALTHCHECK directive
- Discovered: 2026-10-03
- Description: Docker HEALTHCHECK runs `curl -f http://localhost:9000/healthz` every 15s.
  When uvicorn is in disk sleep and can't respond, each curl hangs waiting for response
  (no `--max-time` flag). Old curls are never killed; they accumulate as zombie-like processes
  inside the container consuming PID table slots and RSS (~5 MB each × 77 = ~385 MB extra).
  At 77 curls × 15s interval that's ~19 minutes of stuck healthchecks.
- Suggested fix: Add `--max-time 5` and `--connect-timeout 3` to the HEALTHCHECK curl command:
  `CMD curl --max-time 5 --connect-timeout 3 -f http://localhost:9000/healthz || exit 1`
  Also `docker build` → `docker compose up -d` to apply.

### [ID-003] Stations not properly idle-gating when memory-pressured
- Status: open
- Severity: medium
- Location: `src/engine.py` `_run_relay_loop()`
- Discovered: 2026-10-03
- Description: 9 FFmpeg processes are running with no active listeners. The idle-gating code
  sets a 60s grace timer but the relay loop itself is blocked by the single uvicorn event loop
  being stuck in disk sleep. So the idle-gating timer never fires while memory is exhausted.
  This creates a feedback loop: FFmpeg processes consume memory, memory pressure blocks the
  event loop, event loop can't idle-gate, FFmpeg keeps running.
- Suggested fix: The idle-gate timer should fire independently of HTTP request handling.
  Consider moving idle-gating to a separate asyncio task that runs independently.
  Alternatively, reduce IDLE_GATE_SECONDS from 60 to 15.

### [ID-007] engine.py line 537: syntax error (trailing dot on asyncio.sleep) — FIXED in this session
- Status: resolved (see history_log.md)
- Severity: blocking (prevented fresh builds from starting)
- Location: `src/engine.py` line 537 — `asyncio.sleep(5.0).` — trailing period was invalid syntax
- Discovered: 2026-10-03 during docker build (cached image masked it previously)
- Suggested fix: Remove trailing `.` — applied.


### [ID-008] Station relay loop spin / "connecting" state after listener disconnect — RESOLVED
- Status: resolved (2026-10-03)
- Severity: high (was causing continuous log spam, CPU waste, and preventing proper idle-gating)
- Location: `src/engine.py` `_run_relay_loop()`, `_wait_for_listener_or_running_stop()`
- Discovered: 2026-10-03 during post-fix verification
- Description: Three bugs in the idle-gating lifecycle:
  1. `asyncio.wait()` in `_wait_for_listener_or_running_stop()` passed bare coroutines —
     in Python 3.14 these create dangling tasks that fire repeatedly after the wait returns
     (causing continuous log spam of "Idle-gating" messages every second).
  2. After waking from idle-gating, stale zombie subscriber queues (from abruptly dropped
     HTTP connections) were not pruned, causing `len(subscribers) > 0` to be true → the
     relay would immediately re-enter idle-gating → infinite loop.
  3. The `_resume_event` could remain "set" from the previous subscribe() call, causing
     `_wait_for_listener_or_running_stop()` to return immediately without actually waiting.
- Suggested fix (all applied):
  1. Switched `asyncio.wait()` to use `asyncio.ensure_future()` for both tasks, and explicitly
     cancel pending tasks after the wait completes (fixes "Task was destroyed but it is pending" warnings).
  2. Added stale subscriber pruning (30s qsize-unchanged = dead) at the **top of the relay loop**
     before the idle-gating check, plus cleanup in `_wait_for_listener_or_running_stop()`.
  3. Clear `_resume_event` before creating/waiting on it.
  4. Added "All listeners dropped" break check in the inner streaming loop — when the last
      real subscriber disconnects, break immediately instead of continuing to stream to zombies.

### [ID-004] QuotesManager opens SQLite connection per call (no connection pool)
- Status: open
- Discovered: 2026-10-03
- Description: `_get_connection()` calls `sqlite3.connect()` on every method invocation
  creating and destroying connections on every quote fetch, listener increment, etc.
  Under high load (dashboard polling every 3s, multiple browser tabs), this causes
  frequent SQLite lock contention. Also WAL mode is not enabled.
- Suggested fix: Create a single shared connection at init time (or a small pool).
  Add `conn.execute("PRAGMA journal_mode=WAL")` for concurrent read performance.

### [ID-005] Dashboard polls /api/stations every 3 seconds — RESOLVED
- Status: resolved (2026-10-03 — increased to 10s + visibility-paused)
- Severity: medium
- Location: `static/dashboard.html`
- Discovered: 2026-10-03
- Description: Was polling every 3s; changed to 10s with tab-hidden pause.

### [ID-006] YP client uses `requests` library — RESOLVED
- Status: resolved (2026-10-03 — replaced with urllib.request; requests removed from requirements.txt)
- Status: open
- Severity: medium
- Location: `src/yp_client.py`
- Discovered: 2026-10-03
- Description: `yp_client.py` imports `requests` and calls `requests.post()` directly
  without creating a `Session()`. This means urllib3 creates a new connection pool on
  every call. However, `requests` still holds internal state in module-level objects
  that grows over time. The `requests` library is also a heavyweight dependency for
  what is essentially a simple HTTP POST every 60s.
- Suggested fix: Replace `requests.post()` with `urllib.request.urlopen()` (already used
  elsewhere in the codebase). No external dependency, no connection pool state, no leak risk.

(no open issues yet — resolved issues moved to history_log.md)

### [ID-049] 524 outage: event-loop wedged by sync disk writes + idle-gate dead code — RESOLVED (2026-10-20)
- Status: resolved (2026-10-20, rebuild ae8edae17… deployed)
- Severity: blocking → resolved
- Location: `src/listener_stats.py`, `src/engine.py`
- Discovered: 2026-10-19 13:37 UTC (Cloudflare 524, radio.xecod.com Host Error)
- Description: Four stacked bugs froze the uvicorn event loop:
  (1) `record_connect()` called `save()` synchronously on EVERY connect —
      `tmp.write_text`+`replace` on the ext4 volume blocked thread 1 in
      `jbd2_log_wait_commit` (idle-gating cranked connects up via checkers);
  (2) idle-gate "pause" dead code sat after an unconditional `continue` →
      15 ffmpegs ran 24/7 with full stdout pipes and 0 listeners;
  (3) subscriber liveness counted QUEUE GROWTH as "client reading" → zombie
      queues blocked idle-gating forever; wake-on-`len(subscribers)>0` caused
      a 5s wake/log/re-arm thrash loop respected real listeners never;
  (4) mid-stream break fired while a brand-new listener's queue was still
      empty → catch-22: first listener after idle could NEVER receive audio
      (8s spawn cycles, "All listeners dropped" every 8s).
- Fix: background saver thread (disk never touched from request path) +
  crawler UA filter; gate rewritten (only consumption proves liveness; wake
  ONLY on resume event; gate engages only at zero raw subscribers); liveness
  entries carry born_ts + total_read; SPAWN_COOLDOWN_SECONDS=30 after a
  fruitless spawn; `subprocess.Popen(start_new_session=True)`; `_kill_ffmpeg`
  closes stdout first + reaps on daemon thread; ffmpeg pinned `-threads 1`
  (270→15-90 threads); `listener_stats.py` non-blocking + bot filter.
- Verified: albanna wake-after-idle 200 + 278KB; healthy 10min+; watchdog
  deploy-guard works; public xecod/serastores 200 fast.

### [ID-050] Watchdog false-positive during container recreate — RESOLVED (2026-10-20)
- Status: resolved
- Location: `scripts/watchdog.py`
- Description: During `docker compose up --force-recreate`, healthz is
  unreachable while the NEW container boots → watchdog kill+start mid-deploy
  (killed a test at 07:16, 07:27).
- Fix: `container_age_seconds()` + `FRESH_CONTAINER_GRACE=90` — skip restart
  if started <90s ago. Verified: "Skipping restart" log on deploy window.

### [ID-051] config/station_abouts.json corrupted (stray trailing `}`) — fixed 2026-10-20
- Status: resolved (line 194 deleted; JSON valid, 16 keys)
- Description: app logged "Failed to load station_abouts.json: Extra data:
  line 194 column 1 (char 12072)" every boot. Working copy is richer than
  git HEAD (16 vs 12 stations) — do NOT `git checkout` this file blindly.

### [ID-052] Checker bots keep remote upstreams semi-awake (medium, open)
- Status: open
- Severity: medium
- Location: `src/engine.py` (gating criteria), optional NGINX/CF rate limits
- Discovered: 2026-10-20
- Description: Station-directory checkers/probers connect to `/station/<id>`
  (audio route) and consume ≥32KB (ring prefill) before closing → counts as
  ACTIVE for up to 30s → each probe buys ~30-60s of egress spawn. With
  probes every ~40s per station, ffmpeg stays up most of the time. Duty
  cycle is now bounded (cooldown+grace) but not minimal.
- Suggested fix: raise ACTIVE_LISTENER_MIN_BYTES; or require per-IP connect
  rate sanity (CF); or per-connection token (redirect checkers to a /probe
  route that answers a 2s sine/mp3 sample instead of spawning relay).
