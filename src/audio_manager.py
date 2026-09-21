import os
import zipfile
import shutil
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("radio.audio")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac", ".wma"}

class AudioManager:
    def __init__(self, base_dir: str = "/app/audio"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # Ensure default subdirectories
        for sub in ["quran", "ambient", "uploads"]:
            (self.base_dir / sub).mkdir(parents=True, exist_ok=True)
        self._ensure_fallback_chime()

    def _ensure_fallback_chime(self):
        """Generates a pleasant 5-second standby chime MP3 if no files exist, for seamless fallback."""
        standby_file = self.base_dir / "standby_chime.mp3"
        if not standby_file.exists():
            try:
                # Generate a soft 440Hz / 880Hz acoustic chime via ffmpeg synth
                cmd = [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=528:duration=3",
                    "-af", "volume=0.2,afade=t=in:ss=0:d=0.5,afade=t=out:st=2.5:d=0.5",
                    "-c:a", "libmp3lame", "-b:a", "128k",
                    str(standby_file)
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                logger.info(f"Created fallback standby chime at {standby_file}")
            except Exception as e:
                logger.warning(f"Could not generate standby chime: {e}")

    def list_files(self, subpath: str = "") -> List[Dict[str, Any]]:
        target_dir = self.base_dir / subpath.strip("/")
        if not target_dir.exists() or not target_dir.is_dir():
            return []

        results = []
        for p in sorted(target_dir.rglob("*")):
            if p.is_file():
                ext = p.suffix.lower()
                rel_path = p.relative_to(self.base_dir).as_posix()
                results.append({
                    "name": p.name,
                    "path": rel_path,
                    "full_path": str(p),
                    "size_bytes": p.stat().st_size,
                    "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                    "extension": ext,
                    "is_audio": ext in AUDIO_EXTENSIONS
                })
        return results

    def get_audio_files_in_folder(self, folder_path: str) -> List[str]:
        """Returns full paths to all playable audio files inside folder_path."""
        p = Path(folder_path)
        if not p.is_absolute():
            p = self.base_dir / folder_path.lstrip("/")
        
        if not p.exists():
            return [str(self.base_dir / "standby_chime.mp3")]

        if p.is_file():
            return [str(p)]

        audio_files = []
        for file_path in sorted(p.rglob("*")):
            if file_path.is_file() and file_path.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(str(file_path))

        if not audio_files:
            standby = self.base_dir / "standby_chime.mp3"
            if standby.exists():
                audio_files.append(str(standby))

        return audio_files

    def save_uploaded_file(self, filename: str, content: bytes, target_subfolder: str = "uploads") -> Dict[str, Any]:
        """Saves an uploaded file. If it's a zip file, extracts audio files safely."""
        target_dir = self.base_dir / target_subfolder.strip("/")
        target_dir.mkdir(parents=True, exist_ok=True)
        
        safe_filename = Path(filename).name
        dest_path = target_dir / safe_filename

        with open(dest_path, "wb") as f:
            f.write(content)

        extracted_files = []
        if safe_filename.lower().endswith(".zip"):
            extracted_files = self._extract_zip(dest_path, target_dir)
            # Remove the original zip after extraction to save disk space
            try:
                dest_path.unlink()
            except Exception:
                pass
            return {
                "type": "zip_extracted",
                "extracted_count": len(extracted_files),
                "files": extracted_files,
                "folder": target_subfolder
            }
        else:
            return {
                "type": "single_file",
                "filename": safe_filename,
                "path": dest_path.relative_to(self.base_dir).as_posix(),
                "size_mb": round(len(content) / (1024 * 1024), 2)
            }

    def _extract_zip(self, zip_path: Path, extract_dir: Path) -> List[str]:
        """Safely extracts audio files from a zip file with path traversal protection."""
        extracted = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    
                    # Prevent zip-slip (path traversal)
                    target_file = extract_dir.resolve() / Path(member.filename).name
                    if not target_file.resolve().is_relative_to(extract_dir.resolve()):
                        logger.warning(f"Skipping dangerous zip entry {member.filename}")
                        continue

                    # Only extract audio files or m3u
                    ext = Path(member.filename).suffix.lower()
                    if ext in AUDIO_EXTENSIONS or ext in {".m3u", ".pls"}:
                        with zf.open(member) as source, open(target_file, "wb") as dest:
                            shutil.copyfileobj(source, dest)
                        extracted.append(target_file.name)
                        logger.info(f"Extracted audio file: {target_file.name}")
        except Exception as e:
            logger.error(f"Error extracting zip {zip_path}: {e}")
        return extracted

    def delete_file(self, rel_path: str) -> bool:
        target = (self.base_dir / rel_path.lstrip("/")).resolve()
        if target.is_relative_to(self.base_dir.resolve()) and target.exists() and target.is_file():
            target.unlink()
            return True
        return False
