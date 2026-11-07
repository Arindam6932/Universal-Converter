import subprocess
import tempfile
from pathlib import Path
from app.core.engines import find_ffmpeg
from app.core.processing import run_process, check_cancel, unique_path


AUDIO_TARGETS = {"MP3", "WAV", "FLAC", "AAC", "M4A", "OGG", "OPUS", "WMA", "AIFF", "AC3", "AMR", "MKA", "APE"}

class FFmpegEngine:
    def can_handle(self, category): return category in ("Audio", "Video")

    def convert_job(self, job, cancel=None, progress=None):
        if job.operation == "thumbnail":
            return self.thumbnail(job, cancel, progress)
        if job.operation == "extract_frames":
            return self.extract_frames(job, cancel, progress)
        if job.operation == "merge":
            return self.merge(job, cancel, progress)
        if job.operation == "split":
            return self.split(job, cancel, progress)
        return self.convert(source=job.source, target_format=job.target_format, output_dir=job.output_dir, job=job, cancel=cancel, progress=progress)

    def convert(self, source, target_format, output_dir, job=None, cancel=None, progress=None):
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("FFmpeg was not found. Install FFmpeg and add it to PATH.")
        src = Path(source)
        ext = {"MPEG": "mpg", "AIFF": "aiff"}.get(target_format.upper(), target_format.lower())
        output = unique_path(Path(output_dir) / f"{src.stem}_converted.{ext}")
        command = [ffmpeg, "-hide_banner", "-y"]
        if job and job.trim_start:
            command.extend(["-ss", str(job.trim_start)])
        command.extend(["-i", str(src)])
        if job and job.trim_end and job.trim_end > job.trim_start:
            command.extend(["-t", str(job.trim_end - job.trim_start)])
        if job:
            video_filters = []
            if job.rotation in (90, 180, 270):
                video_filters.append({90: "transpose=1", 180: "transpose=2,transpose=2", 270: "transpose=2"}[job.rotation])
            if job.flip == "Horizontal": video_filters.append("hflip")
            elif job.flip == "Vertical": video_filters.append("vflip")
            if job.crop: video_filters.append(job.crop)
            if job.width or job.height:
                video_filters.append(f"scale={job.width or -2}:{job.height or -2}")
            if job.frame_rate: video_filters.append(f"fps={job.frame_rate}")
            if job.subtitle_file: video_filters.append(f"subtitles={job.subtitle_file}")
            if job.speed != 1: video_filters.append(f"setpts=PTS/{job.speed:g}")
            if video_filters: command.extend(["-vf", ",".join(video_filters)])
            audio_filters = []
            if job.volume != 1:
                audio_filters.append(f"volume={job.volume:g}")
            if job.speed != 1:
                speed = job.speed
                while speed > 2:
                    audio_filters.append("atempo=2.0"); speed /= 2
                while speed < 0.5:
                    audio_filters.append("atempo=0.5"); speed /= 0.5
                audio_filters.append(f"atempo={speed:g}")
            if job.fade_in:
                audio_filters.append(f"afade=t=in:st=0:d={job.fade_in:g}")
            if job.fade_out:
                audio_filters.append(f"afade=t=out:st={max(0, job.trim_end - job.fade_out):g}:d={job.fade_out:g}")
            if audio_filters:
                command.extend(["-filter:a", ",".join(audio_filters)])
            if job.channels:
                command.extend(["-ac", str(job.channels)])
            if job.sample_rate:
                command.extend(["-ar", str(job.sample_rate)])
            if job.bitrate and target_format.upper() not in ("WAV", "FLAC", "AIFF", "APE"):
                command.extend(["-b:a", job.bitrate])
            if job.video_bitrate: command.extend(["-b:v", job.video_bitrate])
            if job.video_codec: command.extend(["-c:v", job.video_codec])
            if job.audio_codec: command.extend(["-c:a", job.audio_codec])
            if job.mute: command.extend(["-an"])
            if job.audio_track: command.extend(["-i", job.audio_track, "-map", "0:v:0", "-map", "1:a:0", "-shortest"])
        if target_format.upper() in AUDIO_TARGETS:
            command.extend(["-vn"])
        if job and job.options.get("target_bytes"):
            command.extend(["-fs", str(job.options["target_bytes"])])
        command.extend(["-map_metadata", "0"])
        command.append(str(output))
        try:
            run_process(command, cancel=cancel, progress=progress)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return str(output)

    def thumbnail(self, job, cancel=None, progress=None):
        ffmpeg = find_ffmpeg()
        if not ffmpeg: raise RuntimeError("FFmpeg was not found. Install FFmpeg and add it to PATH.")
        output = Path(job.output_dir) / f"{Path(job.source).stem}_thumbnail.jpg"
        command = [ffmpeg, "-hide_banner", "-y", "-i", str(job.source), "-frames:v", "1", "-q:v", "2", str(output)]
        run_process(command, cancel=cancel, progress=progress); return str(output)

    def extract_frames(self, job, cancel=None, progress=None):
        ffmpeg = find_ffmpeg()
        if not ffmpeg: raise RuntimeError("FFmpeg was not found. Install FFmpeg and add it to PATH.")
        folder = Path(job.output_dir) / f"{Path(job.source).stem}_frames"; folder.mkdir(parents=True, exist_ok=True)
        command = [ffmpeg, "-hide_banner", "-y", "-i", str(job.source), "-vf", f"fps={job.frame_rate or 1}", str(folder / "frame_%05d.png")]
        run_process(command, cancel=cancel, progress=progress); return str(folder)

    def merge(self, job, cancel=None, progress=None):
        ffmpeg = find_ffmpeg()
        if not ffmpeg: raise RuntimeError("FFmpeg was not found. Install FFmpeg and add it to PATH.")
        sources = job.options.get("sources", [job.source])
        output = Path(job.output_dir) / f"{Path(job.source).stem}_merged.{job.target_format.lower()}"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as listing:
            listing_path = listing.name
            for source in sources: listing.write(f"file '{Path(source).resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")
        try:
            command = [ffmpeg, "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", listing_path, "-c", "copy", str(output)]
            run_process(command, cancel=cancel, progress=progress); return str(output)
        finally:
            Path(listing_path).unlink(missing_ok=True)

    def split(self, job, cancel=None, progress=None):
        ffmpeg = find_ffmpeg()
        if not ffmpeg: raise RuntimeError("FFmpeg was not found. Install FFmpeg and add it to PATH.")
        duration = max(1.0, job.trim_end or job.options.get("segment_seconds", 60))
        folder = Path(job.output_dir) / f"{Path(job.source).stem}_parts"; folder.mkdir(parents=True, exist_ok=True)
        command = [ffmpeg, "-hide_banner", "-y", "-i", str(job.source), "-map", "0", "-c", "copy", "-f", "segment", "-segment_time", str(duration), str(folder / f"{Path(job.source).stem}_%03d.{job.target_format.lower()}")]
        run_process(command, cancel=cancel, progress=progress); return str(folder)
