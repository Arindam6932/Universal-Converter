import subprocess
import time
from pathlib import Path


class JobCancelled(Exception):
    pass


def check_cancel(cancel=None):
    if cancel and cancel():
        raise JobCancelled("Processing cancelled")


def unique_path(path):
    path = Path(path)
    candidate = path
    number = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        number += 1
    return candidate


def byte_size(path):
    path = Path(path)
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob('*') if item.is_file() and not item.is_symlink())
    return path.stat().st_size if path.exists() else 0


def run_process(command, cancel=None, progress=None, duration=0):
    """Drain both pipes while retaining responsive cancellation on Windows/Linux."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            check_cancel(cancel)
            try:
                stdout, stderr = process.communicate(timeout=0.15)
                break
            except subprocess.TimeoutExpired as exc:
                if progress and duration and exc.output:
                    lines = exc.output.decode('utf-8', errors='replace').splitlines()
                    values = [line.split('=', 1)[1] for line in lines if line.startswith('out_time_us=')]
                    if values and values[-1].isdigit():
                        progress(min(99, int(int(values[-1]) / 1_000_000 / duration * 100)))
        if process.returncode:
            raise RuntimeError(stderr.decode('utf-8', errors='replace')[-3000:] or 'Processing failed')
        check_cancel(cancel)
        if progress:
            progress(100)
        return stdout
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
