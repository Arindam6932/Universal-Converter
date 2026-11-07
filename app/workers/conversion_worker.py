from PySide6.QtCore import QThread, Signal
from app.engines.registry import EngineRegistry
from app.core.processing import JobCancelled
from app.core.processing import byte_size
import time

class ConversionWorker(QThread):
    progress = Signal(int, str, str)
    finished_all = Signal()

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs
        self.cancel_requested = False
        self.registry = EngineRegistry()

    def cancel(self): self.cancel_requested = True

    def run(self):
        total = len(self.jobs)
        for index, job in enumerate(self.jobs):
            if self.cancel_requested:
                job.status = "Cancelled"
                job.percent = 100
                continue
            job.status = "Converting"
            job.percent = 0
            started = time.perf_counter(); job.original_bytes = byte_size(job.source)
            self.progress.emit(index, job.status, "")
            try:
                job.output = self.registry.convert(job, cancel=lambda: self.cancel_requested,
                                                   progress=lambda value: self._report_progress(index, job, value))
                job.status = "Completed"
                job.percent = 100
                job.output_bytes = byte_size(job.output); job.elapsed_seconds = time.perf_counter() - started
                self.progress.emit(index, job.status, job.output)
            except JobCancelled:
                job.status = "Cancelled"
                job.error = "Cancelled by user"
                job.percent = 100
                self.progress.emit(index, job.status, job.error)
            except Exception as exc:
                job.status = "Failed"
                job.error = str(exc)
                job.elapsed_seconds = time.perf_counter() - started
                job.percent = 100
                self.progress.emit(index, job.status, job.error)
        self.finished_all.emit()

    def _report_progress(self, index, job, value):
        try:
            job.percent = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            job.percent = 0
        self.progress.emit(index, job.status, str(job.percent))
