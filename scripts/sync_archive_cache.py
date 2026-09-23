#!/usr/bin/env python3
"""Resumable mirror of an archive.org item's MP3 files into a local cache dir.

Why: archive.org rate-limits our server with burst-then-stall behaviour, so
archive-only stations (ammar-almulla, ahmad-tamim) drop to standby chime
during throttle windows. This script mirrors the item's MP3 files to
audio/cache/<station_id>/; the engine's existing `local:` source then plays
that folder as a looping concat when archive.org throttles.

Design:
  - Sequential downloads only (1 at a time) with a 30s per-read timeout:
    respects archive.org's rate limiter instead of hammering it.
  - Resumable: metadata fetch lists expected sizes; any file whose on-disk
    size matches is skipped; .part files resume via HTTP Range on retry.
  - Infinite-ish: 5 attempts per file with exponential backoff (30s..8min
    cap), then continues on the next file instead of aborting the whole run.

Usage:
  python3 scripts/sync_archive_cache.py <item_identifier> <station_id> [--dir /home/saas/radio/audio/cache]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

UA = {"User-Agent": "OmniRadio-CacheSync/1.0 (https://radio.serastores.com)"}
READ_TIMEOUT = 30
CHUNK = 256 * 1024
MAX_ATTEMPTS = 5


def fetch_metadata(identifier: str) -> dict:
    req = urllib.request.Request(
        f"https://archive.org/metadata/{identifier}", headers=UA)
    with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def sanitize(name: str) -> str:
    """Keep the original filename but drop any path traversal."""
    base = os.path.basename(name)
    return base


def expected_sizes(meta: dict) -> dict:
    out = {}
    for f in meta.get("files", []):
        name = f.get("name", "")
        if name.lower().endswith(".mp3") and name:
            size = int(f.get("size") or 0)
            if size > 0:
                out[name] = size
    return out


def download_with_resume(url: str, dest: Path, expected: int) -> bool:
    """Download url to dest with Range resume. Returns True on full success."""
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            existing = part.stat().st_size if part.exists() else 0
            headers = dict(UA)
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as r:
                code = r.getcode()
                # archive.org returns 200 (ignore our Range) or 206
                if code not in (200, 206):
                    raise RuntimeError(f"HTTP {code}")
                mode = "ab" if existing > 0 and code == 206 else "wb"
                with open(part, mode) as out:
                    while True:
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
            final = part.stat().st_size
            if final >= expected:
                part.rename(dest)
                return True
            # Got less than expected (throttle cut us off?) — retry resumes.
            print(f"      partial {final}/{expected} — retrying resume", flush=True)
        except Exception as e:
            print(f"      attempt {attempt} failed: {e}", flush=True)
        time.sleep(min(30 * (2 ** (attempt - 1)), 480))
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("identifier")
    ap.add_argument("station_id")
    ap.add_argument("--dir", default="/home/saas/radio/audio/cache")
    args = ap.parse_args()

    meta = fetch_metadata(args.identifier)
    sizes = expected_sizes(meta)
    if not sizes:
        print(f"No MP3 files found in item '{args.identifier}'", file=sys.stderr)
        return 1

    target = Path(args.dir) / args.station_id
    target.mkdir(parents=True, exist_ok=True)

    # Sort: numeric 001..114 first (natural order), others after — matches the
    # engine's sorted() concat order so playback stays surah-contiguous.
    def sort_key(name: str):
        m = re.match(r"(\d+)\.mp3$", name)
        return (0, int(m.group(1))) if m else (1, name)

    names = sorted(sizes.keys(), key=sort_key)
    ok = 0
    missing = 0
    failed = []
    for i, name in enumerate(names, 1):
        expected = sizes[name]
        dest = target / sanitize(name)
        if dest.exists() and dest.stat().st_size >= expected:
            ok += 1
            continue
        print(f"[{i}/{len(names)}] {name} ({expected/1e6:.1f}MB)", flush=True)
        if download_with_resume(
                f"https://archive.org/download/{args.identifier}/{urllib.parse.quote(name)}",
                dest, expected):
            ok += 1
            print(f"      OK ({dest.stat().st_size/1e6:.1f}MB)", flush=True)
        else:
            missing += 1
            failed.append(name)
            print(f"      FAILED after {MAX_ATTEMPTS} attempts", flush=True)
        time.sleep(1.5)  # polite pacing between files

    print(f"\nDone: {ok}/{len(names)} files complete, {missing} failed", flush=True)
    if failed:
        print("Failed:", ", ".join(failed), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())