import os, shutil
from pathlib import Path

def find_ffmpeg():
    local = Path(__file__).resolve().parents[2] / "tools" / "ffmpeg"
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = local / name
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffmpeg")

def find_ffprobe():
    local = Path(__file__).resolve().parents[2] / "tools" / "ffmpeg"
    for name in ("ffprobe.exe", "ffprobe"):
        candidate = local / name
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffprobe")

def find_libreoffice():
    candidates = [
        shutil.which("soffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"
    ]
    return next((p for p in candidates if p and os.path.exists(p)), None)
