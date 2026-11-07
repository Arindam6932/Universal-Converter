from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum

class JobStatus(str, Enum):
    QUEUED = "Queued"
    RUNNING = "Converting"
    DONE = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

@dataclass
class ConversionJob:
    source: str
    target_format: str
    category: str
    output_dir: str
    status: str = JobStatus.QUEUED.value
    output: str = ""
    error: str = ""
    quality: str = "Balanced"
    preserve_structure: bool = True
    detected_format: str = ""
    recommendation: str = ""
    conversion_mode: str = "Smart Hybrid Conversion"
    width: int = 0
    height: int = 0
    keep_aspect: bool = True
    rotation: int = 0
    flip: str = "None"
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    dpi: int = 0
    background_color: str = ""
    border: int = 0
    trim_start: float = 0.0
    trim_end: float = 0.0
    volume: float = 1.0
    speed: float = 1.0
    channels: int = 0
    bitrate: str = ""
    sample_rate: int = 0
    fade_in: float = 0.0
    fade_out: float = 0.0
    metadata: dict = field(default_factory=dict)
    quality_report: str = ""
    operation: str = "convert"
    options: dict = field(default_factory=dict)
    original_bytes: int = 0
    output_bytes: int = 0
    elapsed_seconds: float = 0.0
    percent: int = 0
    crop: str = ""
    frame_rate: int = 0
    video_bitrate: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    mute: bool = False
    subtitle_file: str = ""
    audio_track: str = ""
    thumbnail: bool = False
    extract_frames: bool = False

    @property
    def filename(self):
        return Path(self.source).name
