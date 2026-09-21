# 📻 OmniRadio Multi-Station Studio

> **Designed and developed by [xecod.com](https://xecod.com)**  
> High-performance streaming radio relay engine with multi-source automatic failover, dedicated mobile web players, embedded FTP audio storage, Web ZIP upload & auto-extraction, and universal Windows Media Player support.

---

## 🌟 Key Features

* **Multi-Source Redundancy & Auto-Failover**:
  Configure an array of primary streams, backup feeds, and local folder fallbacks for each station. If a stream drops or stalls for > 4 seconds, the engine automatically fails over to the next source without dropping connected listener audio queues.
* **Auto-Recovery**:
  Periodically probes the primary stream and automatically restores primary broadcast when online.
* **Dedicated Mobile Themed Player Pages**:
  Each station features a dedicated responsive player URL (`/listen/quran-cairo`, `/quran`, `/chill`, `/paradise`) with customized visual themes, live audio waveforms, big touch controls, and 1-tap WhatsApp sharing.
* **Universal 128kbps MP3 Streaming**:
  All sources (HLS, AAC, HTTP streams, local files) are transcoded and remuxed to standard 128kbps 44.1kHz stereo MP3 with ICY metadata headers, guaranteeing compatibility with Windows Media Player, VLC, Winamp, iOS Safari, and Android.
* **Dual Ingestion (Web ZIP & FTP)**:
  - **Web Upload**: Drag-and-drop `.zip` archives with automatic extraction into categorized folders (`quran/`, `ambient/`, `uploads/`).
  - **Embedded FTP Server**: High-throughput file management on port `2121` via FileZilla, WinSCP, or Windows Explorer.
* **Admin Security Lock**:
  Public visitors only see station cards, players, and master playlists. Management actions (FTP credentials, uploads, source-switching) are locked behind password authentication (`/admin`).
* **Zero External Dependencies**:
  100% self-contained frontend UI with inline CSS and pure vanilla JavaScript — loads in under 40ms without reliance on external CDNs.

---

## 🚀 Quick Start (Docker)

### 1. Clone & Launch
```bash
git clone https://github.com/xecod-dev/omniradio.git
cd omniradio
docker compose up -d --build
```

### 2. Access
* **Studio Dashboard**: `http://localhost:9000/`
* **Dedicated Quran Player**: `http://localhost:9000/quran`
* **Master Playlist (Windows Media Player / VLC)**: `http://localhost:9000/playlist.m3u`
* **Embedded FTP Server**: `ftp://radio:RadioMaster2026!@localhost:2121`

---

## 📻 Pre-Configured Stations

1. **🕌 Holy Quran Radio Cairo (إذاعة القرآن الكريم - القاهرة)**
   - Sources: Radiojar Live Cairo Stream ➔ MP3Quran Direct ➔ Qurango Live ➔ Local recitations
   - Dedicated URL: `/quran` or `/listen/quran-cairo`
2. **📖 Sheikh Abdulbasit Abdulsamad (الشيخ عبد الباسط عبد الصمد - المصحف المجود)**
   - Dedicated URL: `/abdulbasit` or `/listen/abdulbasit`
3. **📖 Sheikh Mohammed Siddiq Al-Minshawi (الشيخ محمد صديق المنشاوي - المصحف المرتل)**
   - Dedicated URL: `/minshawi` or `/listen/alminshawi`
4. **📖 Sheikh Mahmoud Khalil Al-Hussary (الشيخ محمود خليل الحصري - المصحف المرتل)**
   - Dedicated URL: `/hussary` or `/listen/alhussary`
5. **📖 Sheikh Mishary Rashid Al-Afasy (الشيخ مشاري بن راشد العفاسي)**
   - Dedicated URL: `/afasi` or `/listen/alafasi`
6. **📁 Islamic Audio Library & Uploads (المكتبة الصوتية الإسلامية والملفات المرفوعة)**
   - Dedicated URL: `/library` or `/listen/local-library`

---

## 🛠 Configuration (`config/stations.json`)

```json
{
  "server": {
    "name": "OmniRadio Multi-Station Studio",
    "port": 9000,
    "admin_password": "YourAdminPassword",
    "ftp_port": 2121,
    "ftp_pasv_ports": [2122, 2123, 2124, 2125],
    "ftp_user": "radio",
    "ftp_password": "YourFTPPassword"
  },
  "stations": [
    {
      "id": "my-station",
      "name": "Station Name",
      "name_en": "Station Name EN",
      "category": "Talk / Music",
      "description": "Station description",
      "icon": "📻",
      "sources": [
        "https://primary-stream.com/live",
        "https://backup-stream.com/live",
        "local:/app/audio/uploads"
      ],
      "bitrate": 128
    }
  ]
}
```

---

## 🎧 Playing in Media Players

### Windows Media Player
1. Open Windows Media Player.
2. Press <kbd>Ctrl</kbd> + <kbd>U</kbd>.
3. Enter: `http://<SERVER_IP>:9000/playlist.m3u` (or `https://<DOMAIN>/playlist.m3u`).

### VLC Media Player (Desktop & Mobile)
1. Media ➔ Open Network Stream.
2. Enter: `http://<SERVER_IP>:9000/playlist.m3u`.

---

## 📁 Project Structure

```
.
├── config/
│   └── stations.json          # Server & station configuration
├── src/
│   ├── app.py                 # FastAPI endpoints & streaming router
│   ├── engine.py              # Multi-source relay engine with auto-failover
│   ├── ftp_server.py          # Embedded pyftpdlib FTP server
│   ├── audio_manager.py       # ZIP extractor, file indexer, standby chime
│   └── config.py              # Config manager
├── static/
│   ├── dashboard.html         # Studio management web UI (self-contained)
│   └── station_player.html    # Themed dedicated mobile station player
├── audio/                     # Storage volume (quran, ambient, uploads)
├── scripts/
│   ├── duckdns_update.sh      # Automated Dynamic DNS updater
│   └── duckdns.conf.example   # DuckDNS config template
├── Dockerfile                 # Lightweight Alpine Python + FFmpeg image
└── docker-compose.yml
```

---

## 📄 License & Credits

Designed and developed by **[xecod.com](https://xecod.com)**.  
Released under the [MIT License](LICENSE).
