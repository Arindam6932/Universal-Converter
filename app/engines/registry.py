from app.engines.image_engine import ImageEngine
from app.engines.ffmpeg_engine import FFmpegEngine
from app.engines.office_engine import OfficeEngine
from app.engines.markdown_engine import MarkdownEngine
from app.engines.structured_data_engine import StructuredDataEngine
from app.engines.spreadsheet_engine import SpreadsheetEngine
from app.engines.archive_engine import ArchiveEngine
from app.engines.compression_engine import CompressionEngine

class EngineRegistry:
    def __init__(self, engines=None):
        self.engines = list(engines or [ImageEngine(), FFmpegEngine(), SpreadsheetEngine(), StructuredDataEngine(), MarkdownEngine(), OfficeEngine(), ArchiveEngine(), CompressionEngine()])

    def register(self, engine):
        self.engines.append(engine)

    def unregister(self, engine):
        if engine in self.engines:
            self.engines.remove(engine)

    def convert(self, job, cancel=None, progress=None):
        for engine in self.engines:
            if engine.can_handle(job.category):
                if hasattr(engine, "supports") and not engine.supports(job):
                    continue
                if hasattr(engine, "convert_job"):
                    return engine.convert_job(job, cancel=cancel, progress=progress)
                return engine.convert(job.source, job.target_format, job.output_dir)
        raise RuntimeError(f"No conversion engine is registered for {job.category}.")
