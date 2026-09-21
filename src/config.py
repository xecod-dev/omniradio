import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("radio.config")

CONFIG_FILE = os.getenv("CONFIG_FILE", "/app/config/stations.json")
DEFAULT_AUDIO_DIR = os.getenv("AUDIO_DIR", "/app/audio")

DEFAULT_CONFIG = {
    "server": {
        "name": "OmniRadio Multi-Station Studio",
        "port": 9000,
        "admin_password": "RadioMaster2026!",
        "ftp_port": 2121,
        "ftp_pasv_ports": [2122, 2123, 2124, 2125],
        "ftp_user": "radio",
        "ftp_password": "RadioMaster2026!"
    },
    "stations": []
}

class ConfigManager:
    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = Path(config_path)
        self.data = self.load()

    def load(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to parse config file {self.config_path}: {e}")
        return DEFAULT_CONFIG.copy()

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
        return self.get_server_config().get("admin_password", "RadioMaster2026!")

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
