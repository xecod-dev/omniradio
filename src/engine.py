import os
import time
import asyncio
import logging
import random
import subprocess
import threading
from typing import List, Dict, Any, Optional, Set
from collections import deque
import json
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger("radio.engine")

CHUNK_SIZE = 4096  # 4KB per MP3 frame chunk
# archive.org burst-then-stall rate limiting means a healthy source can
# legitimately deliver nothing for 10-20s between bursts. These thresholds
# must be generous enough to ride out throttle windows, but still fail over
# a truly dead source.
STALL_TIMEOUT_SECONDS = 25   # cumulative silence before source is dead
READ_TIMEOUT_SECONDS = 30    # a single hung read is dead; archive.org can
                             # stall this long between bursts before resuming
RING_BUFFER_SIZE = 16  # Pre-buffer ~64KB for instant client audio playback

class StationRelay:
    def __init__(self, station_id: str, config: Dict[str, Any], audio_manager):
        self.station_id = station_id
        self.config = config
        self.audio_manager = audio_manager
        
        self.sources: List[str] = config.get("sources", [])
        self.active_source_idx: int = 0
        self.status: str = "starting"
        self.current_title: str = config.get("name", station_id)
        
        # Performance & Telemetry
        self.start_time: float = time.time()
        self.source_start_time: float = time.time()
        self.total_bytes_streamed: int = 0
        self.failover_history: deque = deque(maxlen=20)
        
        # Client Subscribers
        self.subscribers: Set[asyncio.Queue] = set()
        self.ring_buffer: deque = deque(maxlen=RING_BUFFER_SIZE)
        
        # Subprocess control
        self._running = False
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._relay_task: Optional[asyncio.Task] = None
        self._recovery_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        # When set, the next relay-loop exit was caused by an intentional
        # switch_source() kill, NOT a source failure — the loop must NOT
        # trigger_failover() back off of it (else recovery never sticks).
        self._switch_target: Optional[int] = None

    @property
    def name(self) -> str:
        return self.config.get("name", self.station_id)

    @property
    def active_source(self) -> str:
        if self.sources and 0 <= self.active_source_idx < len(self.sources):
            return self.sources[self.active_source_idx]
        return "none"

    @property
    def listeners_count(self) -> int:
        return len(self.subscribers)

    def get_status_info(self) -> Dict[str, Any]:
        return {
            "id": self.station_id,
            "name": self.name,
            "name_en": self.config.get("name_en", self.name),
            "category": self.config.get("category", "General"),
            "description": self.config.get("description", ""),
            "icon": self.config.get("icon", "📻"),
            "status": self.status,
            "active_source_idx": self.active_source_idx,
            "active_source": self.active_source,
            "sources": self.sources,
            "listeners": self.listeners_count,
            "current_title": self.current_title,
            "uptime_seconds": int(time.time() - self.source_start_time),
            "total_bytes_mb": round(self.total_bytes_streamed / (1024 * 1024), 2),
            "failover_count": len(self.failover_history),
            "failover_history": list(self.failover_history)
        }

    async def start(self):
        if self._running:
            return
        self._running = True
        self._relay_task = asyncio.create_task(self._run_relay_loop())
        self._recovery_task = asyncio.create_task(self._run_primary_recovery_checker())
        logger.info(f"[{self.station_id}] Station relay started with {len(self.sources)} sources")

    async def stop(self):
        self._running = False
        if self._relay_task:
            self._relay_task.cancel()
        if self._recovery_task:
            self._recovery_task.cancel()
        self._kill_ffmpeg()
        logger.info(f"[{self.station_id}] Station relay stopped")

    def _kill_ffmpeg(self):
        if self._ffmpeg_proc:
            try:
                self._ffmpeg_proc.terminate()
                self._ffmpeg_proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._ffmpeg_proc.kill()
                except Exception:
                    pass
            self._ffmpeg_proc = None

    def _build_archive_playlist(self, identifier: str) -> str:
        """Fetch archive.org item metadata and write a remote concat playlist.

        No audio is downloaded — the playlist references the item's MP3 files
        by their https://archive.org/download/... URLs. ffmpeg's concat demuxer
        streams each file on demand, and -stream_loop -1 replays the whole
        item forever.

        The sorted file list is rotated by a random offset so every restart
        begins at a different surah instead of always the first one. Order
        stays contiguous (cyclic rotation), so surahs still play in sequence
        from wherever the rotation lands.
        """
        meta_url = f"https://archive.org/metadata/{identifier}"
        req = urllib.request.Request(
            meta_url,
            headers={"User-Agent": "OmniRadio-Relay/2.0 (Windows Media Player Compatible)"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            meta = json.loads(resp.read().decode("utf-8"))

        names = sorted(
            f.get("name", "")
            for f in meta.get("files", [])
            if f.get("name", "").lower().endswith(".mp3")
        )
        names = [n for n in names if n]  # drop empties
        if not names:
            raise ValueError(f"No MP3 files found in archive.org item '{identifier}'")

        # Random start position (cyclic rotation keeps surah order intact)
        if len(names) > 1:
            offset = random.randrange(len(names))
            names = names[offset:] + names[:offset]

        playlist_file = f"/tmp/archive_{self.station_id}.txt"
        with open(playlist_file, "w", encoding="utf-8") as f:
            for name in names:
                url = f"https://archive.org/download/{identifier}/{urllib.parse.quote(name)}"
                f.write(f"file '{url}'\n")
        logger.info(f"[{self.station_id}] Archive playlist for '{identifier}': {len(names)} files, random start -> {playlist_file}")
        return playlist_file

    def _build_mp3quran_playlist(self, base_url: str) -> str:
        """Write a remote concat playlist for an mp3quran.net mus-haf mirror.

        mp3quran mirrors serve exactly 114 files named 001.mp3..114.mp3 (one per
        surah) under a reciter base URL like https://server6.mp3quran.net/balilah/.
        Same streaming approach as archive: no download, ffmpeg concat demuxer
        pulls each file on demand, -stream_loop -1 replays forever, and the list
        is cyclically rotated by a random offset so every restart begins at a
        different surah while keeping surah order contiguous.
        """
        base = base_url.rstrip("/") + "/"
        names = [f"{i:03d}.mp3" for i in range(1, 115)]  # 001..114
        if len(names) > 1:
            offset = random.randrange(len(names))
            names = names[offset:] + names[:offset]

        playlist_file = f"/tmp/mp3quran_{self.station_id}.txt"
        with open(playlist_file, "w", encoding="utf-8") as f:
            for name in names:
                f.write(f"file '{base}{name}'\n")
        logger.info(f"[{self.station_id}] mp3quran playlist for '{base}': {len(names)} files, random start -> {playlist_file}")
        return playlist_file

    def _build_ffmpeg_cmd(self, source: str) -> List[str]:
        """Constructs ffmpeg command for internet stream, local directory, or single file."""
        bitrate = f"{self.config.get('bitrate', 128)}k"
        
        if source.startswith("local:"):
            # Local directory or file playback
            local_target = source[6:].strip()
            audio_files = self.audio_manager.get_audio_files_in_folder(local_target)
            
            if len(audio_files) == 1:
                # Loop single file or standby chime
                return [
                    "ffmpeg", "-re", "-stream_loop", "-1",
                    "-i", audio_files[0],
                    "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
                    "-ar", "44100", "-ac", "2",
                    "-f", "mp3", "pipe:1"
                ]
            else:
                # Create a concat playlist for multiple files
                concat_list_file = f"/tmp/playlist_{self.station_id}.txt"
                try:
                    with open(concat_list_file, "w", encoding="utf-8") as f:
                        for af in audio_files:
                            safe_p = af.replace("'", "'\\''")
                            f.write(f"file '{safe_p}'\n")
                except Exception as e:
                    logger.error(f"Failed to write concat file: {e}")
                
                return [
                    "ffmpeg", "-re", "-f", "concat", "-safe", "0",
                    "-stream_loop", "-1",
                    "-i", concat_list_file,
                    "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
                    "-ar", "44100", "-ac", "2",
                    "-f", "mp3", "pipe:1"
                ]
        elif source.startswith("archive:"):
            # Archive.org item — stream the item's MP3 list remotely (no download).
            # A metadata fetch builds a concat playlist of https://archive.org/download/ URLs.
            identifier = source[8:].strip()
            try:
                archive_playlist_file = self._build_archive_playlist(identifier)
            except Exception as e:
                logger.error(f"[{self.station_id}] Archive.org source failed for '{identifier}': {e}")
                raise  # failed source -> failover to next source
            return [
                "ffmpeg", "-f", "concat", "-safe", "0",
                "-stream_loop", "-1",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-i", archive_playlist_file,
                "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
                "-ar", "44100", "-ac", "2",
                "-f", "mp3", "pipe:1"
            ]
        elif source.startswith("mp3quran:"):
            # mp3quran.net mirror — stream a full 114-surah mus-haf remotely (no download).
            # Mirrors (e.g. https://server6.mp3quran.net/balilah/) hold one file per
            # surah (001.mp3..114.mp3) and do NOT rate-limit like archive.org, so this
            # is used as a fallback source when archive.org throttles us.
            base_url = source[len("mp3quran:"):].strip()
            mp3quran_playlist_file = self._build_mp3quran_playlist(base_url)
            return [
                "ffmpeg", "-f", "concat", "-safe", "0",
                "-stream_loop", "-1",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-i", mp3quran_playlist_file,
                "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
                "-ar", "44100", "-ac", "2",
                "-f", "mp3", "pipe:1"
            ]
        else:
            # Internet Stream (HTTP, HTTPS, Icecast, Shoutcast, HLS)
            # Use user-agent and auto-reconnect options
            return [
                "ffmpeg",
                "-user_agent", "OmniRadio-Relay/2.0 (Windows Media Player Compatible)",
                "-reconnect", "1",
                "-reconnect_at_eof", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-timeout", "10000000",
                "-i", source,
                "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
                "-ar", "44100", "-ac", "2",
                "-f", "mp3", "pipe:1"
            ]

    async def _run_relay_loop(self):
        """Main non-blocking relay loop with auto failover."""
        while self._running:
            if not self.sources:
                self.status = "no_sources"
                await asyncio.sleep(5)
                continue

            current_source = self.active_source
            self.source_start_time = time.time()
            logger.info(f"[{self.station_id}] Connecting to source #{self.active_source_idx}: {current_source}")
            self.status = "online" if self.active_source_idx == 0 else f"backup_{self.active_source_idx}"

            try:
                # Build the ffmpeg command. This can raise (e.g. an archive.org
                # metadata fetch failure) — it must trigger failover, NOT kill
                # the relay loop (previously it was outside the try, so a
                # transient network error left the station 'online' with no
                # audio forever).
                cmd = self._build_ffmpeg_cmd(current_source)
                # Launch ffmpeg process in async executor to not block the event loop
                self._ffmpeg_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=CHUNK_SIZE * 8
                )
            except Exception as e:
                logger.error(f"[{self.station_id}] Source failed to start ({current_source}): {e}")
                await self._trigger_failover(f"Source start error: {e}")
                await asyncio.sleep(1)
                continue

            loop = asyncio.get_running_loop()
            bytes_received_in_session = 0
            last_data_time = time.time()

            # Read stream chunks from ffmpeg stdout
            while self._running and self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
                # Stall watchdog: if no data has arrived for STALL_TIMEOUT_SECONDS,
                # the source is effectively dead (archive.org throttle, hung
                # concat download, silence from upstream). Break WITHOUT waiting
                # on another blocking read — otherwise the station reports
                # "online" with frozen bytes forever.
                if time.time() - last_data_time > STALL_TIMEOUT_SECONDS:
                    logger.warning(f"[{self.station_id}] Source stall detected ({STALL_TIMEOUT_SECONDS}s no data) from {current_source}")
                    break
                try:
                    # Non-blocking read chunk in worker thread, wrapped in a
                    # generous hung-read backstop. NOTE: no -re on archive
                    # concat, so ffmpeg runs ahead and fills the pipe buffer
                    # as fast as the source delivers — the first chunk arrives
                    # promptly (a -re pacing would block-buffer ~5s+ before
                    # ffmpeg writes the first bytes to the pipe, which broke
                    # every archive station's first read).
                    chunk = await asyncio.wait_for(
                        loop.run_in_executor(None, self._ffmpeg_proc.stdout.read, CHUNK_SIZE),
                        timeout=READ_TIMEOUT_SECONDS
                    )
                    if not chunk:
                        # Stream ended or closed
                        logger.warning(f"[{self.station_id}] Stream EOF received from {current_source}")
                        break

                    last_data_time = time.time()
                    bytes_received_in_session += len(chunk)
                    self.total_bytes_streamed += len(chunk)

                    # Store in ring buffer for immediate delivery to new clients
                    self.ring_buffer.append(chunk)

                    # Broadcast chunk to all connected clients
                    dead_subscribers = []
                    for queue in list(self.subscribers):
                        try:
                            if queue.full():
                                # Discard oldest if queue is full to prevent lag
                                try:
                                    queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                            queue.put_nowait(chunk)
                        except Exception:
                            dead_subscribers.append(queue)

                    for dead in dead_subscribers:
                        self.subscribers.discard(dead)

                except asyncio.TimeoutError:
                    # A single read blocked for READ_TIMEOUT_SECONDS — the
                    # source is stalled; break so the stall/failover path runs.
                    logger.warning(f"[{self.station_id}] Read timeout on stream from {current_source}")
                    break
                except Exception as e:
                    logger.warning(f"[{self.station_id}] Read error on stream: {e}")
                    break

            # If we reached here, the active source died or produced no data
            self._kill_ffmpeg()
            
            if self._running:
                if self._switch_target is not None:
                    # Intentional switch requested by switch_source() — the
                    # ffmpeg kill above was the switch mechanism, not a source
                    # failure. Do NOT failover; just restart the loop on the
                    # (already updated) active source.
                    target = self._switch_target
                    self._switch_target = None
                    logger.info(f"[{self.station_id}] Switching to source #{target}: {self.active_source}")
                    await asyncio.sleep(0.5)
                    continue
                reason = "Stream ended or stalled" if bytes_received_in_session > 0 else "Connection failed immediately"
                await self._trigger_failover(reason)
                # Small backoff before attempting next source
                await asyncio.sleep(1.0)

    async def _trigger_failover(self, reason: str):
        """Switches to the next source in the backup list."""
        old_idx = self.active_source_idx
        old_src = self.active_source
        self.active_source_idx = (self.active_source_idx + 1) % len(self.sources)
        new_src = self.active_source
        
        event = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "from_source": old_src,
            "to_source": new_src,
            "from_index": old_idx,
            "to_index": self.active_source_idx,
            "reason": reason
        }
        self.failover_history.append(event)
        logger.warning(f"[{self.station_id}] FAILOVER TRIGGERED: {old_src} -> {new_src} (Reason: {reason})")

    async def switch_source(self, target_idx: int) -> bool:
        """Manually switches the active source."""
        if 0 <= target_idx < len(self.sources):
            self._switch_target = target_idx
            self.active_source_idx = target_idx
            self.failover_history.append({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "from_source": "manual",
                "to_source": self.sources[target_idx],
                "to_index": target_idx,
                "reason": "Manual operator switch"
            })
            self._kill_ffmpeg()  # This restarts the loop on the new source
            return True
        return False

    async def _run_primary_recovery_checker(self):
        """Periodically tests primary (source 0) if currently running on a backup source.

        Uses exponential backoff (60s -> 120s -> 240s -> ... -> cap 10min) on
        consecutive failed probes so we don't hammer archive.org every 60s
        while it is in a burst-then-stall rate-limit phase. Probe success
        resets the interval back to 60s.
        """
        interval = 60
        consecutive_failures = 0
        while self._running:
            await asyncio.sleep(interval)
            if self.active_source_idx > 0 and len(self.sources) > 1:
                primary_source = self.sources[0]
                if not primary_source.startswith("local:"):
                    # Test primary URL connectivity
                    is_alive = await self._test_stream_connectivity(primary_source)
                    if is_alive:
                        consecutive_failures = 0
                        interval = 60
                        logger.info(f"[{self.station_id}] Primary source {primary_source} is back ONLINE! Recovering to primary...")
                        await self.switch_source(0)
                    else:
                        consecutive_failures += 1
                        interval = min(60 * (2 ** consecutive_failures), 600)
                        logger.info(f"[{self.station_id}] Primary source {primary_source} still down (probe #{consecutive_failures}); next check in {interval}s")

    async def _test_stream_connectivity(self, url: str) -> bool:
        """Tests if a remote stream URL responds with 200/302 and audio content."""
        loop = asyncio.get_running_loop()
        def _check():
            try:
                if url.startswith("archive:"):
                    identifier = url[8:].strip()
                    # 1) metadata reachable (playlist can be built)
                    meta_url = f"https://archive.org/metadata/{identifier}"
                    req = urllib.request.Request(
                        meta_url,
                        headers={"User-Agent": "OmniRadio-HealthCheck/1.0"}
                    )
                    with urllib.request.urlopen(req, timeout=5) as response:
                        if response.getcode() not in (200, 206, 302):
                            return False
                        meta = json.loads(response.read().decode("utf-8"))
                    # 2) an actual MP3 in the item downloads audio bytes (not
                    #    just metadata) — archive.org rate-limits downloads
                    #    separately from metadata, so metadata 200 is NOT
                    #    proof the stream will play.
                    mp3 = next(
                        (f.get("name") for f in meta.get("files", [])
                         if f.get("name", "").lower().endswith(".mp3")),
                        None
                    )
                    if not mp3:
                        return False
                    file_req = urllib.request.Request(
                        f"https://archive.org/download/{identifier}/{mp3}",
                        headers={
                            "User-Agent": "OmniRadio-HealthCheck/1.0",
                            "Range": "bytes=0-4095",  # just the first frame
                        }
                    )
                    with urllib.request.urlopen(file_req, timeout=8) as fr:
                        # 403/503/429 or empty body => still throttled/alive
                        # 200/206 with audio bytes => usable
                        return fr.getcode() in (200, 206) and len(fr.read(4096)) > 0
                elif url.startswith("mp3quran:"):
                    # mp3quran.net mirror: probe the first surah file with a
                    # strict Range GET (metadata alone doesn't prove audio flows).
                    base = url[len("mp3quran:"):].strip().rstrip("/") + "/"
                    probe_url = f"{base}001.mp3"
                    req = urllib.request.Request(
                        probe_url,
                        headers={
                            "User-Agent": "OmniRadio-HealthCheck/1.0",
                            "Range": "bytes=0-4095",
                        }
                    )
                    with urllib.request.urlopen(req, timeout=8) as response:
                        return response.getcode() in (200, 206) and len(response.read(4096)) > 0
                else:
                    probe_url = url
                    req = urllib.request.Request(
                        probe_url,
                        headers={"User-Agent": "OmniRadio-HealthCheck/1.0"}
                    )
                    with urllib.request.urlopen(req, timeout=5) as response:
                        code = response.getcode()
                        return code in (200, 206, 302)
            except Exception:
                return False
        return await loop.run_in_executor(None, _check)

    def subscribe(self) -> asyncio.Queue:
        """Registers a new listener queue and pre-populates it with the ring buffer."""
        queue = asyncio.Queue(maxsize=32)
        for chunk in list(self.ring_buffer):
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                break
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        self.subscribers.discard(queue)


class RadioEngine:
    def __init__(self, config_manager, audio_manager):
        self.config_manager = config_manager
        self.audio_manager = audio_manager
        self.relays: Dict[str, StationRelay] = {}

    async def start(self):
        stations = self.config_manager.get_stations()
        for i, s in enumerate(stations):
            sid = s.get("id")
            if sid:
                relay = StationRelay(sid, s, self.audio_manager)
                self.relays[sid] = relay
                await relay.start()
                # Stagger starts so all stations don't open archive.org
                # connections simultaneously (that triggers per-IP download
                # rate-limiting: first-byte latencies of 10s+ and 170-byte
                # responses). 1.5s between relays keeps the fleet healthy.
                if i < len(stations) - 1:
                    await asyncio.sleep(1.5)
        logger.info(f"RadioEngine initialized {len(self.relays)} station relays")

    async def stop(self):
        for relay in self.relays.values():
            await relay.stop()
        self.relays.clear()

    def get_relay(self, station_id: str) -> Optional[StationRelay]:
        return self.relays.get(station_id)

    def get_all_stations_status(self) -> List[Dict[str, Any]]:
        return [relay.get_status_info() for relay in self.relays.values()]

    async def reload_station(self, station_id: str):
        station_config = self.config_manager.get_station(station_id)
        if not station_config:
            if station_id in self.relays:
                await self.relays[station_id].stop()
                del self.relays[station_id]
            return

        if station_id in self.relays:
            await self.relays[station_id].stop()
        
        relay = StationRelay(station_id, station_config, self.audio_manager)
        self.relays[station_id] = relay
        await relay.start()
