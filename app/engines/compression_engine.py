import time
import tempfile
import shutil
from pathlib import Path

from app.core.processing import byte_size, check_cancel
from app.engines.archive_engine import ArchiveEngine
from app.engines.ffmpeg_engine import FFmpegEngine
from app.engines.image_engine import ImageEngine
from app.engines.office_engine import OfficeEngine
from app.engines.pdf_engine import PdfEngine


class CompressionEngine:
    def can_handle(self, category): return category == "Compression"

    def convert_job(self, job, cancel=None, progress=None):
        source_category = job.options.get("source_category", "")
        if not source_category:
            source_category = self._category_from_suffix(job.source)
        original = byte_size(job.source); started = time.perf_counter()
        if source_category == "Image":
            result = ImageEngine().convert_job(job, cancel, progress)
        elif source_category in ("Audio", "Video"):
            result = FFmpegEngine().convert_job(job, cancel, progress)
        elif source_category == "Document":
            result = OfficeEngine().convert_job(job, cancel, progress)
        elif source_category == "Archive":
            with tempfile.TemporaryDirectory(prefix="universal_archive_compress_") as temp:
                extracted = Path(ArchiveEngine().extract(job.source, Path(temp) / "contents", password=job.options.get("password", "")))
                job.operation = "create"; job.options["sources"] = [str(item) for item in extracted.iterdir()]
                result = ArchiveEngine().convert_job(job, cancel, progress)
        else:
            raise RuntimeError(f"No meaningful compression profile is available for {Path(job.source).suffix}.")
        job.original_bytes = original; job.output_bytes = byte_size(result); job.elapsed_seconds = time.perf_counter() - started
        return result

    @staticmethod
    def _category_from_suffix(source):
        suffix = Path(source).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".avif"}: return "Image"
        if suffix in {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".ac3", ".amr", ".mka", ".ape"}: return "Audio"
        if suffix in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".mpeg", ".mpg", ".3gp", ".m4v", ".ts", ".m2ts", ".mts", ".ogv", ".vob", ".m2v"}: return "Video"
        if suffix in {".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt", ".html", ".htm", ".xlsx", ".xls", ".ods", ".csv", ".pptx", ".ppt", ".odp"}: return "Document"
        if suffix in {".zip", ".7z", ".tar", ".gz", ".bz2", ".xz"}: return "Archive"
        return ""
