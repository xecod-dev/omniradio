# History Log (append-only)

## [2026-10-10] Fixed new archive stations skipping surahs and initial loading delay
- Change: Fixed root causes causing new archive stations (majid-farouk, khaledabushady, salah-bukhatir, abubakr-shatri) to get stuck loading for 1-2s and rapidly skip/jump between surahs
- Why:
  1. Concat stream-copy (`-c:a copy`) without transcoding: Archive MP3s from different uploaders have disparate sample rates (8000 Hz for khaledabushady, 22050 Hz for majid-farouk, 44100 Hz for others), embedded PNG/MJPEG album art, ID3 tags at every surah boundary, and Xing VBR headers. When concatenated with `-c:a copy`, FFmpeg emitted non-monotonic DTS timestamp errors, and browser MP3 demuxers treated each embedded Xing/ID3 header as a new file/stream end, causing rapid skipping through short surahs.
  2. Missing `-re` real-time flag + pacing mismatch: FFmpeg read archive.org streams at unthrottled line speed (up to 15x), filling buffers with multiple short surahs, while the relay loop's `pace_delay` was calibrated for 128k CBR and ran low-bitrate (26k-32k) streams at 4x-5x speed.
  3. Archive metadata HTTP latency: Every station startup made an uncached HTTP call to `https://archive.org/metadata/{ident}`, taking 1-3s (causing "stuck loading 1 sec").
- Fixes applied:
  1. `src/engine.py` `_build_ffmpeg_cmd`: Switched `archive:` and `mp3quran:` from `-c:a copy` to `-re -probesize 32768 -analyzeduration 0 -vn -c:a libmp3lame -b:a {bitrate}k -ar 44100 -ac {channels}`. All audio is cleanly normalized to 44100 Hz mono/stereo, album art and ID3 boundaries are stripped, and output is strictly paced at 1.0x real-time speed.
  2. `src/engine.py` `_build_archive_playlist`: Persistent playlist metadata cache in `/app/data/archive_meta_{ident}.json`. Subsequent connections start in ~0.15s without querying archive.org metadata API.
  3. `src/engine.py` `_run_relay_loop`: Removed artificial `pace_delay` sleep; rate-pacing is handled natively and accurately by FFmpeg `-re`.
- Impact: TTFB for archive stations dropped from 24s to ~0.15s. Audio plays at exactly 1.0x speed, surahs transition smoothly without skipping, and browser decoders receive continuous 44100 Hz MP3 streams.
- Reverses/supersedes: n/a

## [2026-10-10] Fixed mobile playback stops after 5-10 seconds
- Change: Fixed 5 root causes causing mobile phones (iOS Safari, Android Chrome/Samsung) to stop loading/playing after 5-10 seconds
- Why: Mobile browsers exhibited underruns, false stall watchdog reconnects, background audio termination, and decoder errors after 5-10 seconds
- Root causes and fixes:
  1. `src/engine.py` Queue liveness bug: Active listeners with `q.qsize() == 0` (draining instantly) were mistakenly matched by `q.qsize() == info[1]` without checking `q.full()`, leading to active mobile listeners being prematurely discarded from `self.subscribers` after 30s. Fixed: only discard queues that are completely full (`q.full()`) and unconsumed for 30s.
  2. `src/engine.py` Queue & Ring Buffer capacity: Increased `RING_BUFFER_SIZE` to 128 (512 KB) and `asyncio.Queue(maxsize=128)` (was 32 / 128 KB). At 64kbps, 512KB gives mobile devices 64 seconds of buffer headroom against cellular network jitter.
  3. `src/app.py` HTTP Headers: Removed `"Accept-Ranges": "none"` and `"X-Content-Type-Options": "nosniff"` from stream endpoints. Mobile Safari and Android ExoPlayer reject or prematurely close live audio connections when `Accept-Ranges: none` is sent.
  4. `static/station_player.html` MediaSession API: Added `navigator.mediaSession` integration with title, artist, artwork, and action handlers. Mobile OSs (iOS lock screen / Android MediaSession) previously suspended or killed background audio after 5-10s when screen was locked.
  5. `static/station_player.html` Screen WakeLock & Cache-busting: Added Screen WakeLock API (`navigator.wakeLock`) while playing to keep mobile screens awake; added cache-busting timestamp `_t=${Date.now()}` on `audio.src` to prevent mobile socket reuse; updated `ended` event to auto-reconnect live stream instead of stopping playback.
- Impact: Stream tests confirm continuous playback past 20s. Container rebuilt and healthy.
- Reverses/supersedes: n/a

## [2026-10-03] Added new station: الشيخ ماجد فاروق (majid-farouk)
- Change: Added new archive.org-based station for Sheikh Majid Farouk using identifier `irgui82_majid-farok`
- Why: User requested adding this station like others
- Files changed:
  - `config/stations.json` — added station entry with archive source and local fallback
  - `config/station_abouts.json` — added About modal content with summary, facts, sources
- Impact: Station available at `/listen/majid-farouk`, 64kbps mono, idle-gated when no listeners. Test stream delivered 139KB in 20s without interruption.
- Reverses/supersedes: n/a

## [2026-10-03] Added audio buffering to fix 10s stream stops
- Change: Three fixes for the "plays 10 seconds then stops" issue on Mishary Alafasi / Abdulbasit / Hussary stations
- Why: The browser's `<audio>` element had `preload="none"` (no buffering) and the server ring buffer was only 16 chunks (64KB). When archive.org burst-then-stall sources had a brief gap (10-20s), the audio pipeline drained and the player's 30s watchdog detected no progress → tear down + reconnect loop.
- Fixes applied:
  1. `src/engine.py` — RING_BUFFER_SIZE: 16 → 64 chunks (64KB → 256KB pre-buffer)
  2. `static/station_player.html` — `<audio preload="none">` → `<audio preload="auto">`
  3. `static/station_player.html` — STALL_MS: 30s → 60s (rides out archive.org throttle windows)
- Impact: Continuous 20s+ stream test on alafasi received 405KB without interruption. Station remains "online" throughout.
- Reverses/supersedes: n/a

## [2026-10-03] Raised uvicorn global concurrency limit to 900
- Change: Added `--limit-concurrency 900 --loop asyncio` to uvicorn CMD in Dockerfile
- Why: Without a concurrency limit, uvicorn could accept unlimited simultaneous connections,
  each consuming memory for request/response processing. Under a traffic spike, this could
  exhaust the 4 GiB memory limit even without the known leak. A limit of 900 concurrent
  HTTP connections is generous for this app (10 stations, ~50 listeners typical) while
  providing a hard ceiling to prevent unbounded memory growth.
- Alternatives considered:
  - `--limit-concurrency 100` (too restrictive for burst traffic)
  - `--workers 2` (would require process-level state coordination; deferred to ID-001 long-term)
- Impact: Dockerfile CMD updated; `--limit-concurrency 900` and `--loop asyncio` (explicit)
  now applied. Container rebuilt and healthy. All stations operational at <5ms TTFB.
- Reverses/supersedes: n/a

## [2026-10-03] Fixed idle-gating lifecycle bugs — relay loop spin resolved
- Change: Fixed three bugs in engine.py's idle-gating / async task lifecycle that were
  causing continuous "Idle-gating" log spam, "Task was destroyed but it is pending" warnings,
  and preventing stations from properly entering/resting in idle state.
- Why: Stations were showing "connecting" or "online" with 0 listeners and wasting CPU/memory
  because the relay loop cycled endlessly between idle-gating and the streaming inner loop.
- Fixes applied:
  1. Replaced bare coroutines in `asyncio.wait()` with `asyncio.ensure_future()` tasks + explicit
     `t.cancel()` on pending tasks (Python 3.14 compatibility; fixes "Task was destroyed" warnings).
  2. Added stale subscriber queue pruning (30s qsize-unchanged = dead) at the TOP of the relay loop,
     before idle-gating check, so zombie queues from dropped HTTP connections don't prevent
     stations from idle-gating. Also cleanup tracking dict in `unsubscribe()`.
  3. Clear `_resume_event` before waiting on it in `_wait_for_listener_or_running_stop()`.
  4. Added listener-drop detection in the inner streaming loop: break immediately when all
     subscribers disconnect on remote sources (instead of continuing to stream to empty set).
- Impact: Files changed: src/engine.py. Stations now properly go idle when no listeners,
  come online when listener connects (~3s), and return to idle when listener disconnects.
  Memory stable at ~117 MiB. Log spam eliminated. All 10 remote stations idle-gated,
  local-library remains online (by design).
- Reverses/supersedes: n/a

## [2026-10-03] Applied memory-exhaustion mitigations — site restored
- Change: Applied 5 code fixes and rebuilt container image. Site is healthy at <5ms TTFB.
- Why: radio-app had reached 4 GiB mem_limit (uvicorn in D/disk-sleep state), causing "loads loading"
- Fixes applied:
  1. **Container restart** — immediate: RSS dropped from 3.95 GiB to ~70 MiB
  2. **Dockerfile HEALTHCHECK** — added `--max-time 5 --connect-timeout 3` to curl so stuck healthchecks self-terminate instead of accumulating. Also extended `--start-period` from 5s to 15s. Resolves ID-002.
  3. **yp_client.py** — replaced `requests` library with stdlib `urllib.request` (no external sessions, no connection pool state, lower memory baseline). Removed `requests` from requirements.txt. Resolves ID-006.
  4. **dashboard.html** — poll interval increased from 3s to 10s; added `visibilitychange` listener that pauses polling when tab is hidden. Resolves ID-005.
  5. **docker-compose.yml** — added `MALLOC_TRIM_THRESHOLD_=131072` and `MALLOC_MMAP_THRESHOLD_=131072` env vars to instruct glibc malloc to release freed pages back to OS more aggressively.
  6. **app.py** — added `_memory_watchdog()` async task: runs every 60s, calls `gc.collect()` + `malloc_trim(0)`, logs a warning at 75% of limit, and sends SIGTERM + forced exit at 2800 MiB (configurable via `WATCHDOG_RSS_LIMIT_MiB` env var). Docker `restart: unless-stopped` brings it back clean.
  7. **engine.py** — fixed pre-existing syntax error: trailing `.` after `asyncio.sleep(5.0)` (line 537). This was masked by the cached Docker layer but broke fresh builds. Resolves ID-007.
- Alternatives considered:
  - Switching to gunicorn with multiple workers (would isolate leak per-worker but adds complexity)
  - Increasing mem_limit to 8 GiB (symptom management, doesn't address leak)
- Impact: Files changed: Dockerfile, src/yp_client.py, src/app.py, src/engine.py, static/dashboard.html, docker-compose.yml, requirements.txt
- Reverses/supersedes: "Fix plan decisions" entry above

## [2026-10-03] Baseline established — ContextGuard bootstrap
- Change: Initial ContextGuard memory files created for OmniRadio repository
- Why: Site was down ("loads loading" at http://172.30.0.90:9000/); bootstrapped during live diagnosis
- Alternatives considered: n/a
- Impact: Created AGENTS.md, .context/architecture.md, .context/active_issues.md, .context/history_log.md
- Reverses/supersedes: n/a

## [2026-10-03] Memory exhaustion diagnosis — radio-app container
- Change: Identified root cause of "loads loading" symptom
- Why: Container radio-app hitting 4 GiB mem_limit (99.9% utilization), uvicorn process in D state (disk sleep), 77 stuck curl healthcheck processes, container status=unhealthy
- Alternatives considered: Suspected network issue, slow SQLite, slow /api/stations endpoint — ruled out. Cause is memory exhaustion in uvicorn parent process (RssAnon=3.94 GiB, all anonymous heap).
- Impact: Logged as ID-001 (blocking), ID-002 (high), ID-003 (medium) in active_issues.md
- Reverses/supersedes: n/a

## [2026-10-03] Fix plan decisions
- Change: Documented 3-phase fix plan (immediate restart → short-term curl/yp fixes → long-term monitoring)
- Why: Container needs immediate relief; root causes also need structural fixes to prevent recurrence
- Alternatives considered:
  - Kill individual curl processes (doesn't help; root is memory, not curl count)
  - Just increase mem_limit to 8g (symptom management, doesn't address leak)
  - Switch to gunicorn multi-worker (best long-term but requires testing)
- Impact: Next session should apply: (1) container restart, (2) Dockerfile HEALTHCHECK curl --max-time fix, (3) yp_client requests→urllib refactor, (4) MALLOC_TRIM env var, (5) dashboard poll interval increase
- Reverses/supersedes: n/a

- Change: Initial ContextGuard memory files created for OmniRadio repository
- Why: Site was down ("loads loading" at http://172.30.0.90:9000/); bootstrapped during live diagnosis
- Alternatives considered: n/a
- Impact: Created AGENTS.md, .context/architecture.md, .context/active_issues.md, .context/history_log.md
- Reverses/supersedes: n/a

## [2026-10-03] Memory exhaustion diagnosis — radio-app container
- Change: Identified root cause of "loads loading" symptom
- Why: Container radio-app hitting 4 GiB mem_limit (99.9% utilization), uvicorn process in D state (disk sleep), 77 stuck curl healthcheck processes, container status=unhealthy
- Alternatives considered: Suspected network issue, slow SQLite, slow /api/stations endpoint — ruled out. Cause is memory exhaustion in uvicorn parent process (RssAnon=3.94 GiB, all anonymous heap).
- Impact: Logged as ID-001 (blocking), ID-002 (high), ID-003 (medium) in active_issues.md
- Reverses/supersedes: n/a

## [2026-10-03] Fix plan decisions
- Change: Documented 3-phase fix plan (immediate restart → short-term curl/yp fixes → long-term monitoring)
- Why: Container needs immediate relief; root causes also need structural fixes to prevent recurrence
- Alternatives considered:
  - Kill individual curl processes (doesn't help; root is memory, not curl count)
  - Just increase mem_limit to 8g (symptom management, doesn't address leak)
  - Switch to gunicorn multi-worker (best long-term but requires testing)
- Impact: Next session should apply: (1) container restart, (2) Dockerfile HEALTHCHECK curl --max-time fix, (3) yp_client requests→urllib refactor, (4) MALLOC_TRIM env var, (5) dashboard poll interval increase
- Reverses/supersedes: n/a

## [2026-10-20] Root-cause fixes for the 524 / loop-wedge family (rebuilds 1bce3f3c → ae8edae17)
- Change: listener stats moved off the request path (daemon saver thread 60s +
  dirty flag); idle-gating re-architected: liveness only counts CONSUMPTION
  (qsize DECREASE), wake only on resume_event, gate engages only when
  active_listeners()==0 AND raw subscribers==0; fruitless-spawn cooldown 30s;
  ffmpeg pinned `-threads 1` (5 cmd builders) and Popen start_new_session;
  _kill_ffmpeg closes stdout first + reaps in daemon thread; watchdog gained
  fresh-container deploy grace (90s); station_abouts.json stray brace removed.
- Why: sync disk writes on the event loop wedged thread 1 in
  jbd2_log_wait_commit under checker load; dead-code pause branch left 15
  ffmpegs running forever; zombie-queue liveness + wake-on-subscribers>0
  caused a 5s thrash; empty-queue catch-22 starved first listeners.
- Alternatives considered: switch to asyncio subprocess (bigger refactor);
  egress proxy for stats (unneeded — data is tiny); leave watchdog-only masking.
- Impact: src/engine.py (gate, liveness, kill, spawn, -threads), src/app.py
  (untouched — record_connect still called, now non-blocking),
  src/listener_stats.py, scripts/watchdog.py, config/station_abouts.json.
  Radio-app rebuilt + deployed; acceptance: wake-after-idle 200/278KB,
  10min uptime, cpu ~246% across 14 live ffmpegs + 33 real consumer sockets.
- Reverses/supersedes: partial fixes from 2026-10-19 (watchdog-only band-aid).

## [2026-10-20] Auto-fix watchdog for radio-app (radio-watchdog in PM2)
- Change: `/home/saas/radio/scripts/watchdog.py` polls
  http://127.0.0.1:9000/healthz every 20s; 2 consecutive fails →
  `docker kill radio-app && docker start radio-app`; logs to logs/watchdog.log;
  registered in PM2 (pm2 save — boot persistent).
- Why: uvicorn hangs (event-loop wedge) do NOT trip Docker's restart policy
  (container process keeps running); docker kill+start is required.
- Alternatives considered: willfarrell/autoheal container; systemd unit (no
  passwordless sudo for user saas); cron @reboot loop.
- Impact: PM2 process table gained `radio-watchdog` (id 3). NOTE: docker
  compose recreate makes healthz briefly unreachable — deploy grace added
  (see same-day entry).
