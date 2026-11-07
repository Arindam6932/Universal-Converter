import bz2
import gzip
import hashlib
import json
import lzma
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from app.core.processing import check_cancel, unique_path


ARCHIVE_FORMATS = ['ZIP', '7Z', 'TAR', 'TAR.GZ', 'TAR.BZ2', 'TAR.XZ', 'GZ', 'BZ2', 'XZ']


def safe_name(name):
    name = str(name).replace('\\', '/')
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or any(':' in part for part in path.parts):
        raise ValueError(f'Unsafe archive entry: {name}')
    return path.as_posix()


class ArchiveEngine:
    def can_handle(self, category):
        return category == 'Archive'

    def convert_job(self, job, cancel=None, progress=None):
        options = job.options
        sources = options.get('sources', [job.source])
        output_dir = Path(job.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        operation = job.operation
        password = options.get('password', '')
        if operation in ('create', 'convert', 'compress'):
            return self.create(sources, unique_path(output_dir / f'{Path(job.source).stem}_archive.{job.target_format.lower()}'),
                               job.target_format, options.get('level', 6), password, cancel, progress)
        if operation == 'browse':
            options['listing'] = self.list_entries(job.source, password)
            return job.source
        if operation == 'test':
            self.test(job.source, password, cancel)
            options['message'] = 'Integrity test passed'
            return job.source
        if operation == 'extract':
            destination = unique_path(output_dir / f'{Path(job.source).stem}_extracted')
            return self.extract(job.source, destination, options.get('selected'), password, cancel, progress)
        if operation in ('add', 'remove', 'rename'):
            with tempfile.TemporaryDirectory(prefix='universal_archive_') as temp:
                staging = Path(temp) / 'contents'
                self.extract(job.source, staging, password=password, cancel=cancel)
                if operation == 'remove':
                    for name in options.get('selected', []):
                        target = staging / safe_name(name)
                        if target.is_dir(): shutil.rmtree(target)
                        elif target.exists(): target.unlink()
                if operation == 'rename':
                    selected = options.get('selected', [])
                    if len(selected) != 1: raise ValueError('Select one archive entry to rename.')
                    original = staging / safe_name(selected[0])
                    destination = staging / safe_name(options.get('new_name', ''))
                    if destination.exists(): raise ValueError('The destination entry already exists.')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    original.rename(destination)
                if operation == 'add':
                    for source in options.get('add_sources', []):
                        check_cancel(cancel)
                        source = Path(source); destination = staging / source.name
                        if destination.exists(): raise ValueError(f'Entry already exists: {source.name}')
                        if source.is_dir(): shutil.copytree(source, destination)
                        else: shutil.copy2(source, destination)
                archive_format = self.archive_format(job.source)
                return self.create(list(staging.iterdir()), unique_path(output_dir / f'{Path(job.source).stem}_edited.{archive_format.lower()}'),
                                   archive_format, options.get('level', 6), password, cancel, progress)
        if operation == 'split_volumes':
            return self.split_volumes(job.source, output_dir, options.get('volume_mb', 100), cancel)
        if operation == 'join_volumes':
            return self.join_volumes(job.source, output_dir, cancel)
        raise ValueError(f'Unknown archive operation: {operation}')

    @staticmethod
    def archive_format(source):
        name = str(source).lower()
        for suffix in ('tar.gz', 'tar.bz2', 'tar.xz'):
            if name.endswith('.' + suffix): return suffix.upper()
        return Path(source).suffix.lstrip('.').upper()

    def list_entries(self, source, password=''):
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as archive:
                return [dict(name=item.filename, size=item.file_size, packed=item.compress_size,
                             directory=item.is_dir(), encrypted=bool(item.flag_bits & 1)) for item in archive.infolist()]
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as archive:
                return [dict(name=item.name, size=item.size, packed=None, directory=item.isdir(), encrypted=False) for item in archive]
        if str(source).lower().endswith('.7z'):
            import py7zr
            with py7zr.SevenZipFile(source, password=password or None) as archive:
                return [dict(name=item.filename, size=item.uncompressed or 0, packed=item.compressed,
                             directory=item.is_directory, encrypted=archive.needs_password()) for item in archive.list()]
        if self.archive_format(source) in ('GZ', 'BZ2', 'XZ'):
            return [dict(name=Path(source).stem, size=None, packed=Path(source).stat().st_size, directory=False, encrypted=False)]
        raise ValueError('Unsupported or corrupted archive.')

    @staticmethod
    def _zip_reader(source, password):
        if password:
            import pyzipper
            archive = pyzipper.AESZipFile(source)
            archive.setpassword(password.encode('utf-8'))
            return archive
        return zipfile.ZipFile(source)

    def _copy(self, source, destination, cancel=None):
        while True:
            check_cancel(cancel)
            chunk = source.read(1024 * 1024)
            if not chunk: break
            destination.write(chunk)

    def extract(self, source, destination, selected=None, password='', cancel=None, progress=None):
        destination = Path(destination)
        if destination.exists(): raise ValueError('Extraction destination already exists. Choose a new folder.')
        listing = self.list_entries(source, password)
        selected_set = set(selected or [])
        names = [item['name'] for item in listing if not selected_set or item['name'] in selected_set]
        for name in names: safe_name(name)
        try:
            destination.mkdir(parents=True)
            if zipfile.is_zipfile(source):
                with self._zip_reader(source, password) as archive:
                    for index, name in enumerate(names):
                        check_cancel(cancel)
                        info = archive.getinfo(name)
                        if stat.S_ISLNK(info.external_attr >> 16): raise ValueError('Symbolic links are not extracted.')
                        output = destination / safe_name(name)
                        if info.is_dir(): output.mkdir(parents=True, exist_ok=True)
                        else:
                            output.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(name) as incoming, output.open('xb') as outgoing:
                                self._copy(incoming, outgoing, cancel)
                        if progress: progress(int((index + 1) / max(1, len(names)) * 100))
            elif tarfile.is_tarfile(source):
                with tarfile.open(source) as archive:
                    for index, name in enumerate(names):
                        check_cancel(cancel); info = archive.getmember(name); output = destination / safe_name(name)
                        if info.isdir(): output.mkdir(parents=True, exist_ok=True)
                        elif info.isfile():
                            output.parent.mkdir(parents=True, exist_ok=True)
                            with archive.extractfile(info) as incoming, output.open('xb') as outgoing:
                                self._copy(incoming, outgoing, cancel)
                        else: raise ValueError('Links and special archive entries are not extracted.')
                        if progress: progress(int((index + 1) / max(1, len(names)) * 100))
            elif str(source).lower().endswith('.7z'):
                import py7zr
                with py7zr.SevenZipFile(source, password=password or None) as archive:
                    for info in archive.files:
                        safe_name(info.filename)
                        if info.is_symlink or info.is_junction: raise ValueError('Links are not extracted.')
                    archive.extract(path=destination, targets=names, recursive=True)
                check_cancel(cancel)
            else:
                opener = {'GZ': gzip.open, 'BZ2': bz2.open, 'XZ': lzma.open}[self.archive_format(source)]
                with opener(source, 'rb') as incoming, (destination / Path(source).stem).open('xb') as outgoing:
                    self._copy(incoming, outgoing, cancel)
            return str(destination)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def create(self, sources, output, archive_format='ZIP', level=6, password='', cancel=None, progress=None):
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        archive_format = archive_format.upper()
        files = []
        for source in sources:
            source = Path(source)
            if not source.exists(): raise FileNotFoundError(source)
            files.extend(item for item in (source.rglob('*') if source.is_dir() else [source]) if item.is_file())
        if archive_format == 'ZIP':
            if password:
                try:
                    import pyzipper
                    archive = pyzipper.AESZipFile(output, 'w', compression=pyzipper.ZIP_DEFLATED, compresslevel=level)
                    archive.setencryption(pyzipper.WZ_AES, nbits=256); archive.setpassword(password.encode('utf-8'))
                except ImportError as exc: raise RuntimeError('Password ZIP creation requires pyzipper.') from exc
            else:
                archive = zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=level)
            with archive:
                written = 0
                for source in sources:
                    source = Path(source)
                    candidates = [item for item in source.rglob('*') if item.is_file()] if source.is_dir() else [source]
                    for file in candidates:
                        check_cancel(cancel)
                        arcname = str(Path(source.name) / file.relative_to(source)) if source.is_dir() else file.name
                        archive.write(file, arcname=arcname)
                        written += 1
                        if progress: progress(int(written / max(1, len(files)) * 100))
            return str(output)
        if password: raise RuntimeError('Password protection is only implemented for ZIP when pyzipper is installed.')
        if archive_format in ('TAR', 'TAR.GZ', 'TAR.BZ2', 'TAR.XZ'):
            mode = {'TAR': 'w', 'TAR.GZ': 'w:gz', 'TAR.BZ2': 'w:bz2', 'TAR.XZ': 'w:xz'}[archive_format]
            with tarfile.open(output, mode) as archive:
                for index, source in enumerate(sources):
                    check_cancel(cancel); archive.add(source, arcname=Path(source).name, recursive=True)
                    if progress: progress(int((index + 1) / max(1, len(sources)) * 100))
            return str(output)
        if archive_format == '7Z':
            try:
                import py7zr
            except ImportError as exc: raise RuntimeError('7Z support requires py7zr.') from exc
            with py7zr.SevenZipFile(output, 'w', password=password or None, filters=[{'id': py7zr.FILTER_LZMA2, 'preset': level}]) as archive:
                for source in sources: check_cancel(cancel); archive.writeall(source, arcname=Path(source).name)
            return str(output)
        if archive_format in ('GZ', 'BZ2', 'XZ') and len(sources) == 1:
            opener = {'GZ': gzip.open, 'BZ2': bz2.open, 'XZ': lzma.open}[archive_format]
            with Path(sources[0]).open('rb') as incoming, opener(output, 'wb') as outgoing: self._copy(incoming, outgoing, cancel)
            return str(output)
        raise ValueError(f'Unsupported archive format: {archive_format}')

    def test(self, source, password='', cancel=None):
        if zipfile.is_zipfile(source):
            with self._zip_reader(source, password) as archive:
                for info in archive.infolist(): check_cancel(cancel); archive.read(info)
            return True
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as archive:
                for info in archive: check_cancel(cancel); archive.extractfile(info) if info.isfile() else None
            return True
        if self.archive_format(source) == '7Z':
            import py7zr
            with py7zr.SevenZipFile(source, password=password or None) as archive: archive.test()
            return True
        self.list_entries(source, password); return True

    def split_volumes(self, source, output_dir, volume_mb=100, cancel=None):
        source = Path(source); size = max(1, int(volume_mb)) * 1024 * 1024; outputs = []
        with source.open('rb') as incoming:
            index = 1
            while True:
                check_cancel(cancel); block = incoming.read(size)
                if not block: break
                output = Path(output_dir) / f'{source.name}.part{index:03d}'; output.write_bytes(block); outputs.append(str(output)); index += 1
        return outputs

    def join_volumes(self, first_volume, output_dir, cancel=None):
        first = Path(first_volume); volumes = sorted(first.parent.glob(first.name.split('.part')[0] + '.part*'))
        output = Path(output_dir) / first.name.split('.part')[0]
        with output.open('wb') as combined:
            for volume in volumes:
                check_cancel(cancel)
                with volume.open('rb') as incoming: self._copy(incoming, combined, cancel)
        return str(output)
