import os
import logging
import threading
from pathlib import Path
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

logger = logging.getLogger("radio.ftp")

class EmbeddedFTPServer:
    def __init__(self, audio_dir: str = "/app/audio", port: int = 2121, pasv_ports: list = None, user: str = "radio", password: str = "RadioMaster2026!"):
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.port = port
        self.pasv_ports = pasv_ports or [2122, 2123, 2124, 2125]
        self.user = user
        self.password = password
        self.server = None
        self.thread = None
        self._running = False

    def start(self):
        if self._running:
            return

        try:
            authorizer = DummyAuthorizer()
            # Full permissions: read, write, delete, make dir, etc.
            authorizer.add_user(
                self.user,
                self.password,
                str(self.audio_dir.resolve()),
                perm="elradfmwMT"
            )
            # Optional anonymous read access
            authorizer.add_anonymous(str(self.audio_dir.resolve()), perm="elr")

            handler = FTPHandler
            handler.authorizer = authorizer
            handler.banner = "OmniRadio Audio Storage FTP Server Ready."
            
            # Set passive ports range for NAT / container port forwarding
            if self.pasv_ports:
                handler.passive_ports = range(self.pasv_ports[0], self.pasv_ports[-1] + 1)

            # Bind to all interfaces
            self.server = FTPServer(("0.0.0.0", self.port), handler)
            self.server.max_cons = 32
            self.server.max_cons_per_ip = 8

            self._running = True
            self.thread = threading.Thread(target=self._run_server, daemon=True)
            self.thread.start()
            logger.info(f"FTP Server started on port {self.port} (User: {self.user}, Root: {self.audio_dir})")
        except Exception as e:
            logger.error(f"Failed to start embedded FTP server: {e}")

    def _run_server(self):
        try:
            self.server.serve_forever()
        except Exception as e:
            logger.info(f"FTP server loop terminated: {e}")

    def stop(self):
        if self._running and self.server:
            self._running = False
            try:
                self.server.close_all()
            except Exception:
                pass
            logger.info("FTP Server stopped")
