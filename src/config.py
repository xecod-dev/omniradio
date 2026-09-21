import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("radio.config")

CONFIG_FILE = os.getenv("CONFIG_FILE", "/app/config/stations.json")
SECRETS_FILE = os.getenv("SECRETS_FILE", "/app/config/secrets.json")
DEFAULT_AUDIO_DIR = os.getenv("AUDIO_DIR", "/app/audio")

# Keys considered credentials when overlaying secrets.json over the server config
SECRET_KEYS = ("admin_password", "ftp_user", "ftp_password")

DEFAULT_CONFIG = {
    "server": {
        "name": "OmniRadio Multi-Station Studio",
        "port": 9000,
        "admin_password": "",
        "ftp_port": 2121,
        "ftp_pasv_ports": [2122, 2123, 2124, 2125],
        "ftp_user": "radio",
        "ftp_password": ""
    },
    "stations": []
}

class ConfigManager:
    def __init__(self, config_path: str = CONFIG_FILE, secrets_path: str = SECRETS_FILE):
        self.config_path = Path(config_path)
        self.secrets_path = Path(secrets_path)
        self.data = self.load()
        self._merge_secrets()

    def load(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to parse config file {self.config_path}: {e}")
        return DEFAULT_CONFIG.copy()

    def _merge_secrets(self) -> None:
        """Overlay credentials from the gitignored secrets file onto the server config.

        stations.json stays public; real admin/FTP credentials live in
        config/secrets.json (volume-mounted, not tracked by git).
        Falls back to stations.json server keys when the secrets file is absent.
        """
        if not self.secrets_path.exists():
            logger.warning(
                f"Secrets file {self.secrets_path} not found — using credentials "
                "from stations.json / defaults. Create config/secrets.json to "
                "keep credentials out of git."
            )
            return
        try:
            with open(self.secrets_path, "r", encoding="utf-8") as f:
                secrets = json.load(f)
        except Exception as e:
            logger.error(f"Failed to parse secrets file {self.secrets_path}: {e}")
            return
        self.data.setdefault("server", {})
        for key in SECRET_KEYS:
            if key in secrets and secrets[key]:
                self.data["server"][key] = secrets[key]
        logger.info(f"Credentials loaded from {self.secrets_path}")

    def save(self):
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            logger.info("Configuration saved successfully")
        except Exception as e:
            logger.error(f"Failed to write config file {self.config_path}: {e}")

    def get_server_config(self) -> Dict[str, Any]:
        return self.data.get("server", DEFAULT_CONFIG["server"])

    def get_admin_password(self) -> str:
        return self.get_server_config().get("admin_password", "")

    def get_stations(self) -> List[Dict[str, Any]]:
        return self.data.get("stations", [])

    def get_station(self, station_id: str) -> Optional[Dict[str, Any]]:
        for s in self.get_stations():
            if s.get("id") == station_id:
                return s
        return None

    def add_station(self, station_data: Dict[str, Any]) -> Dict[str, Any]:
        sid = station_data.get("id")
        if not sid:
            raise ValueError("Station ID is required")
        if self.get_station(sid):
            raise ValueError(f"Station with ID '{sid}' already exists")
        
        station_data.setdefault("bitrate", 128)
        station_data.setdefault("sources", [])
        self.data.setdefault("stations", []).append(station_data)
        self.save()
        return station_data

    def update_station(self, station_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for i, s in enumerate(self.data.get("stations", [])):
            if s.get("id") == station_id:
                s.update(update_data)
                # Keep ID immutable
                s["id"] = station_id
                self.data["stations"][i] = s
                self.save()
                return s
        return None

    def delete_station(self, station_id: str) -> bool:
        stations = self.data.get("stations", [])
        initial_len = len(stations)
        self.data["stations"] = [s for s in stations if s.get("id") != station_id]
        if len(self.data["stations"]) != initial_len:
            self.save()
            return True
        return False
