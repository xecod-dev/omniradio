#!/usr/bin/env python3
"""Radio App Health Watchdog.

Polls http://127.0.0.1:9000/healthz every 20 seconds.
If healthcheck fails 2 consecutive times (or times out > 5s),
it forces `docker kill radio-app && docker start radio-app`
and logs the event to /home/saas/radio/logs/watchdog.log.
"""
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

LOG_PATH = Path("/home/saas/radio/logs/watchdog.log")
HEALTH_URL = "http://127.0.0.1:9000/healthz"
CHECK_INTERVAL = 20
TIMEOUT = 5
MAX_FAILS = 2
# Don't force-restart a container younger than this — during
# `docker compose up --force-recreate` the old container vanishes while the
# new one boots, producing a short healthz outage that is NOT a hang.
FRESH_CONTAINER_GRACE = 90

def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def check_health() -> bool:
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "RadioWatchdog/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False

def restart_container():
    log("⚠️ Radio app unhealthy! Forcing docker kill & start...")
    try:
        subprocess.run(["docker", "kill", "radio-app"], capture_output=True, timeout=10)
        time.sleep(2)
        subprocess.run(["docker", "start", "radio-app"], capture_output=True, timeout=10)
        log("✅ radio-app successfully restarted by watchdog.")
    except Exception as e:
        log(f"❌ Failed to restart container: {e}")

def container_age_seconds() -> float:
    """How long ago the container process started (for deploy grace).
    During `docker compose up --force-recreate` healthz is unreachable for
    several seconds while a NEW, perfectly fine container boots — the
    watchdog must not kill+start over that (it ruined a deploy once)."""
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.StartedAt}}", "radio-app"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        from datetime import datetime, timezone
        started = datetime.fromisoformat(out.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - started).total_seconds()
    except Exception:
        return 999999.0


def main():
    log("🛡️ Radio Watchdog started.")
    fails = 0
    while True:
        time.sleep(CHECK_INTERVAL)
        ok = check_health()
        if ok:
            if fails > 0:
                log("🟢 radio-app recovered / healthy again.")
            fails = 0
        else:
            fails += 1
            log(f"⚠️ Healthcheck failed (consecutive fail #{fails}/{MAX_FAILS})")
            if fails >= MAX_FAILS:
                age = container_age_seconds()
                if age < FRESH_CONTAINER_GRACE:
                    log(
                        f"⏭️ Container started {int(age)}s ago (< {FRESH_CONTAINER_GRACE}s)"
                        " — likely boot/deploy, NOT a hang. Skipping restart."
                    )
                    fails = 0
                    continue
                restart_container()
                fails = 0
                # Give it time to boot up before next check
                time.sleep(15)

if __name__ == "__main__":
    main()
