import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase, QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QProgressBar, QScrollArea, QSlider, QSpinBox, QDoubleSpinBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLayout,
)

from app.core.formats import capabilities_for, category_for, extension_for, formats_for, source_extensions
from app.core.engines import find_ffprobe, find_libreoffice
from app.core.models import ConversionJob
from app.core.processing import unique_path
from app.engines.image_engine import ImageEngine


def panel(parent=None, object_name="GlassCard"):
    card = QFrame(parent)
    card.setObjectName(object_name)
    return card


class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self, title="Drop files here", hint="or browse your computer"):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)
        glyph = QLabel("⇧"); glyph.setObjectName("DropGlyph"); glyph.setAlignment(Qt.AlignCenter)
        heading = QLabel(title); heading.setObjectName("DropHeadline"); heading.setAlignment(Qt.AlignCenter)
        detail = QLabel(hint); detail.setObjectName("SubTitle"); detail.setAlignment(Qt.AlignCenter)
        browse = QPushButton("Browse files"); browse.setObjectName("Primary")
        browse.clicked.connect(self.browse)
        for widget in (glyph, heading, detail, browse):
            layout.addWidget(widget, 0, Qt.AlignCenter)
        self.setMinimumHeight(170)

    def browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files")
        if files:
            self.files_dropped.emit(files)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.files_dropped.emit([
            url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()
        ])


class BaseWorkspace(QWidget):
    def __init__(self, title, subtitle):
        super().__init__()
        self.setObjectName("PageSurface")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("WorkspaceScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget(); content.setObjectName("WorkspaceContent")
        self.root = QVBoxLayout(content)
        self.root.setSizeConstraint(QLayout.SetMinimumSize)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        self.root.setContentsMargins(0, 4, 0, 0)
        self.root.setSpacing(14)
        self.header = QWidget()
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(3)
        self.title_label = QLabel(title); self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel(subtitle); self.subtitle_label.setObjectName("SubTitle")
        self.subtitle_label.setWordWrap(True)
        header_layout.addWidget(self.title_label); header_layout.addWidget(self.subtitle_label)
        self.root.addWidget(self.header)

    def set_title(self, title, subtitle=None):
        self.title_label.setText(title)
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)


class StatCard(QFrame):
    def __init__(self, label, value="0"):
        super().__init__()
        self.setObjectName("StatCard")
        layout = QVBoxLayout(self); layout.setContentsMargins(14, 12, 14, 12); layout.setSpacing(3)
        self.value_label = QLabel(value); self.value_label.setObjectName("StatValue")
        caption = QLabel(label); caption.setObjectName("SubTitle")
        layout.addWidget(self.value_label); layout.addWidget(caption)

    def set_value(self, value):
        self.value_label.setText(str(value))


class ConverterWorkspace(BaseWorkspace):
    run_requested = Signal()
    cancel_requested = Signal()
    output_requested = Signal()
    status_requested = Signal(str)

    def __init__(self, title, subtitle, category=None, formats=None, allow_mixed=False, accepted_categories=None):
        super().__init__(title, subtitle)
        self.category = category
        self.formats = list(formats or formats_for(category))
        self.allow_mixed = allow_mixed
        self.accepted_categories = set(accepted_categories or ([category] if category else []))
        self.entries = []
        self.output_dir = ""
        self.preferred_target = ""
        self._build()

    def _build(self):
        self.drop_zone = DropZone(
            "Drop files here" if self.allow_mixed else f"Drop {self.category or 'supported'} files here",
            "Universal detection • multiple files supported" if self.allow_mixed
            else "or browse your computer • multiple files supported",
        )
        self.drop_zone.files_dropped.connect(self.add_files)
        self.root.addWidget(self.drop_zone)

        options = panel()
        option_layout = QHBoxLayout(options); option_layout.setContentsMargins(16, 11, 16, 11); option_layout.setSpacing(10)
        quality_label = QLabel("Quality"); quality_label.setObjectName("SectionTitle")
        self.quality_combo = QComboBox(); self.quality_combo.addItems(["Balanced", "High", "Maximum"])
        self.preserve_check = QCheckBox("Preserve structure"); self.preserve_check.setChecked(True)
        self.output_format = QComboBox(); self.output_format.setMinimumWidth(210)
        self.output_format.setToolTip("One output format shared by the entire conversion queue. Only formats supported by every file are listed.")
        self.output_format.addItem("Add files to detect common formats", "")
        self.output_format.currentIndexChanged.connect(self._common_target_changed)
        self.output_label = QLabel("Choose an output folder"); self.output_label.setObjectName("SettingHint")
        self.output_label.setMinimumWidth(180)
        output_button = QPushButton("Output folder")
        output_button.clicked.connect(self.output_requested.emit)
        option_layout.addWidget(quality_label); option_layout.addWidget(self.quality_combo)
        option_layout.addWidget(self.preserve_check); option_layout.addSpacing(6)
        option_layout.addWidget(QLabel("Common output format")); option_layout.addWidget(self.output_format)
        option_layout.addSpacing(4); option_layout.addWidget(QLabel("Save to")); option_layout.addWidget(self.output_label, 1); option_layout.addWidget(output_button)
        self.root.addWidget(options)

        self.compatibility_hint = QLabel("The output selector will be populated with formats supported by every queued file.")
        self.compatibility_hint.setObjectName("SettingHint"); self.compatibility_hint.setWordWrap(True)
        self.root.addWidget(self.compatibility_hint)

        queue_header = QHBoxLayout()
        queue_title = QLabel("Conversion queue"); queue_title.setObjectName("SectionTitle")
        self.queue_count = QLabel("0 files"); self.queue_count.setObjectName("SubTitle")
        remove = QPushButton("Remove selected"); remove.clicked.connect(self.remove_selected)
        clear = QPushButton("Clear"); clear.clicked.connect(self.clear_queue)
        queue_header.addWidget(queue_title); queue_header.addWidget(self.queue_count); queue_header.addStretch(); queue_header.addWidget(remove); queue_header.addWidget(clear)
        self.root.addLayout(queue_header)

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("QueueTable")
        self.table.setHorizontalHeaderLabels(["File", "Detected", "Category", "Output format", "Compatibility", "Progress", "Status", "Result"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(240)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self.open_result)
        self.root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setValue(0)
        self.progress_text = QLabel("Choose one common output format, then convert the compatible files"); self.progress_text.setObjectName("SubTitle")
        self.cancel_button = QPushButton("Cancel"); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.open_result_button = QPushButton("Open result"); self.open_result_button.setEnabled(False); self.open_result_button.clicked.connect(self.open_first_result)
        self.download_all_button = QPushButton("Download All (ZIP)"); self.download_all_button.setEnabled(False); self.download_all_button.clicked.connect(self.download_all_results)
        self.run_button = QPushButton("Convert  →"); self.run_button.setObjectName("Primary"); self.run_button.clicked.connect(self.run_requested.emit)
        bottom.addWidget(self.progress, 1); bottom.addWidget(self.progress_text); bottom.addWidget(self.open_result_button); bottom.addWidget(self.download_all_button); bottom.addWidget(self.cancel_button); bottom.addWidget(self.run_button)
        self.root.addLayout(bottom)

    def set_output_dir(self, path):
        self.output_dir = path
        self.output_label.setText(path or "Choose an output folder")

    def _target_options(self, category, path=None):
        if self.category == "Audio" and category == "Video":
            options = formats_for("Audio")
        elif self.category == "Document" and category == "Image":
            options = ["PDF"]
        else:
            options = capabilities_for(path, category) if path else (formats_for(category) if self.allow_mixed else list(self.formats))
        if self.formats:
            options = [option for option in options if option in self.formats]
        return options

    @staticmethod
    def _detected(path):
        suffix = Path(path).suffix.lower().lstrip(".")
        return suffix.upper() if suffix else "UNKNOWN"

    def _recommended_target(self, path, category, options):
        if self.preferred_target in options:
            return self.preferred_target
        preferred = {"Image": "PNG", "Audio": "MP3", "Video": "MP4", "Document": "PDF"}.get(category)
        if preferred in options and Path(path).suffix.lower().lstrip(".") not in source_extensions(category, preferred):
            return preferred
        for option in options:
            if Path(path).suffix.lower().lstrip(".") not in source_extensions(category, option):
                return option
        return options[0] if options else ""

    def set_preferred_target(self, target):
        """Apply a format shortcut to the one common queue selector."""
        self.preferred_target = target or ""
        index = self.output_format.findData(target)
        if index >= 0:
            self.output_format.setCurrentIndex(index)
        else:
            self._refresh_common_targets()

    def _compatibility(self, category, path, target):
        source_ext = Path(path).suffix.lower().lstrip(".")
        options = next((entry["options"] for entry in self.entries if entry["path"] == path), [])
        if not target:
            if not options:
                return "Incompatible — no supported target"
            if self.entries and not getattr(self, "common_targets", []):
                return "Incompatible with batch — remove file"
            return "Choose a common target"
        if target not in options:
            return "Incompatible — remove file"
        if source_ext in source_extensions(category, target):
            return "Already in target format"
        if category == "Document":
            return "Compatible — native/office route"
        if category == "Image":
            return "Compatible — image route"
        if category in ("Audio", "Video"):
            return "Compatible — FFmpeg route"
        return "Compatible"

    def add_files(self, paths):
        accepted = 0
        rejected = []
        duplicates = 0
        existing = {str(Path(item["path"]).resolve()).casefold() for item in self.entries}
        for path in paths:
            if not os.path.isfile(path):
                continue
            normalized = str(Path(path).resolve()).casefold()
            if normalized in existing:
                duplicates += 1
                continue
            category = category_for(path)
            if category == "Other" and not self.allow_mixed:
                rejected.append(path)
                continue
            if not self.allow_mixed and category not in self.accepted_categories:
                rejected.append(path)
                continue
            options = self._target_options(category, path)
            entry = {
                "path": path,
                "category": category,
                "detected": self._detected(path),
                "options": options,
                "target": "",
                "status": "Queued",
                "output": "",
                "error": "",
                "percent": 0,
            }
            self.entries.append(entry)
            existing.add(normalized)
            self._append_entry(entry)
            accepted += 1
        self._refresh_common_targets()
        self.queue_count.setText(f"{len(self.entries)} file(s)")
        if accepted:
            self.status_requested.emit(f"Added {accepted} file(s) to the queue")
        if duplicates:
            self.status_requested.emit(f"Ignored {duplicates} duplicate file(s)")
        if rejected:
            self.status_requested.emit(f"Skipped {len(rejected)} unsupported or incompatible file(s)")
        return accepted, rejected

    def _append_entry(self, entry):
        row = self.table.rowCount(); self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(Path(entry["path"]).name))
        detected = QTableWidgetItem(f"{entry['detected']}  •  .{Path(entry['path']).suffix.lower().lstrip('.') or 'unknown'}")
        detected.setToolTip(f"Detected extension: .{Path(entry['path']).suffix.lower().lstrip('.') or 'unknown'}\nCategory: {entry['category']}\nAvailable targets: {', '.join(entry['options']) or 'None'}")
        self.table.setItem(row, 1, detected)
        self.table.setItem(row, 2, QTableWidgetItem(entry["category"]))
        self.table.setItem(row, 3, QTableWidgetItem("—"))
        compatibility = QTableWidgetItem("Choose a common target")
        compatibility.setToolTip(f"Available targets for this file: {', '.join(entry['options']) or 'None'}")
        self.table.setItem(row, 4, compatibility)
        progress = QProgressBar(); progress.setRange(0, 100); progress.setValue(0); progress.setFormat("%p%")
        self.table.setCellWidget(row, 5, progress); entry["progress_bar"] = progress
        self.table.setItem(row, 6, QTableWidgetItem(entry["status"]))
        self.table.setItem(row, 7, QTableWidgetItem("Ready"))

    def _refresh_common_targets(self):
        if not self.entries:
            common = []
        else:
            for entry in self.entries:
                entry["options"] = self._target_options(entry["category"], entry["path"])
            common_set = set(self.entries[0]["options"])
            for entry in self.entries[1:]:
                common_set.intersection_update(entry["options"])
            entry_order = list(dict.fromkeys(option for entry in self.entries for option in entry["options"]))
            order = self.formats if self.formats and all(set(entry["options"]).issubset(self.formats) for entry in self.entries) else entry_order
            common = [option for option in order if option in common_set]
        self.common_targets = common
        current = self.output_format.currentData()
        preferred = self.preferred_target if self.preferred_target in common else current if current in common else ""
        if not preferred and common:
            preferred = self._recommended_target(self.entries[0]["path"], self.entries[0]["category"], common)
        self.output_format.blockSignals(True); self.output_format.clear()
        self.output_format.addItem("Select one common output format", "")
        for option in common:
            self.output_format.addItem(option, option)
        self.output_format.setCurrentIndex(self.output_format.findData(preferred) if preferred else 0)
        self.output_format.blockSignals(False)
        if self.entries and not common:
            detail = "No common conversion target is available for every queued file. Remove the incompatible file(s) or choose a different set of files."
            if any(entry["category"] == "Document" for entry in self.entries) and not find_libreoffice():
                detail += " Office conversions require LibreOffice; install it and restart the app."
            self.compatibility_hint.setText(detail)
        elif common:
            self.compatibility_hint.setText(f"{len(common)} common format(s) available for all {len(self.entries)} queued file(s). Already-target files will be skipped safely.")
        else:
            self.compatibility_hint.setText("The output selector will be populated with formats supported by every queued file.")
        self._apply_common_target(preferred)

    def _common_target_changed(self, *_):
        self._apply_common_target(self.output_format.currentData() or "")

    def _apply_common_target(self, target):
        for row, entry in enumerate(self.entries):
            entry["target"] = target
            if entry.get("status") in {"Already in target format", "Incompatible", "Failed", "Completed"}:
                entry["status"] = "Queued"
                entry["output"] = ""
                entry["error"] = ""
                entry["percent"] = 0
            self.table.setItem(row, 3, QTableWidgetItem(target or "—"))
            compatibility = QTableWidgetItem(self._compatibility(entry["category"], entry["path"], target))
            compatibility.setToolTip(f"Available targets for this file: {', '.join(entry['options']) or 'None'}")
            self.table.setItem(row, 4, compatibility)
            self.table.setItem(row, 6, QTableWidgetItem(entry.get("status", "Queued")))
            self.table.setItem(row, 7, QTableWidgetItem(entry.get("output") or entry.get("error") or "Ready"))
            if entry.get("progress_bar"):
                entry["progress_bar"].setValue(entry.get("percent", 0))

    def build_jobs(self, output_dir):
        jobs = []
        target = self.output_format.currentData() or ""
        for entry in self.entries:
            if entry["status"] not in ("Queued", "Failed"):
                continue
            compatibility = self._compatibility(entry["category"], entry["path"], target)
            if compatibility.startswith("Incompatible"):
                entry["status"] = "Incompatible"
                self.table.setItem(self.entries.index(entry), 6, QTableWidgetItem(entry["status"]))
                continue
            if compatibility.startswith("Already"):
                entry["status"] = "Already in target format"
                entry["percent"] = 100
                self.table.setItem(self.entries.index(entry), 6, QTableWidgetItem(entry["status"]))
                continue
            jobs.append(ConversionJob(
                entry["path"], target, entry["category"], output_dir,
                quality=self.quality_combo.currentText(),
                preserve_structure=self.preserve_check.isChecked(),
                detected_format=entry["detected"],
                recommendation=entry["target"],
            ))
        return jobs

    def update_jobs(self, jobs):
        by_path = {job.source: job for job in jobs}
        for row, entry in enumerate(self.entries):
            job = by_path.get(entry["path"])
            if not job:
                self.table.setItem(row, 6, QTableWidgetItem(entry.get("status", "Queued")))
                self.table.setItem(row, 7, QTableWidgetItem(entry.get("output") or entry.get("error") or "Ready"))
                if entry.get("progress_bar"):
                    entry["progress_bar"].setValue(entry.get("percent", 0))
                continue
            entry["status"] = job.status
            entry["output"] = job.output
            entry["error"] = job.error
            entry["percent"] = getattr(job, "percent", 100 if job.status in ("Completed", "Failed", "Cancelled") else 0)
            self.table.setItem(row, 6, QTableWidgetItem(job.status))
            self.table.setItem(row, 7, QTableWidgetItem(job.output or job.error or ""))
            if entry.get("progress_bar"):
                entry["progress_bar"].setValue(entry["percent"])
        total = len(self.entries)
        overall = int(sum(entry.get("percent", 0) for entry in self.entries) / max(1, total))
        finished = sum(entry["status"] in ("Completed", "Failed", "Cancelled", "Already in target format", "Incompatible") for entry in self.entries)
        errors = sum(entry["status"] == "Failed" for entry in self.entries)
        self.progress.setValue(overall)
        self.progress_text.setText(f"{overall}% overall • {finished} of {total} processed" + (f" • {errors} error(s)" if errors else ""))
        self._sync_result_buttons()

    def set_running(self, running):
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if running:
            self.progress.setValue(0); self.progress_text.setText("Processing…")
        self._sync_result_buttons()

    def clear_queue(self):
        if self.worker_is_running():
            return
        self.entries.clear(); self.table.setRowCount(0); self.queue_count.setText("0 file(s)")
        self._refresh_common_targets(); self.progress.setValue(0); self.progress_text.setText("Choose one common output format, then convert the compatible files")
        self._sync_result_buttons()

    def remove_selected(self):
        if self.worker_is_running():
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.entries):
                self.entries.pop(row)
                self.table.removeRow(row)
        if rows:
            self.queue_count.setText(f"{len(self.entries)} file(s)")
            self._refresh_common_targets()

    def _sync_result_buttons(self):
        outputs = [entry.get("output") for entry in self.entries if entry.get("output") and os.path.exists(entry["output"])]
        self.open_result_button.setEnabled(bool(outputs) and not self.worker_is_running())
        self.download_all_button.setEnabled(len(outputs) > 1 and not self.worker_is_running())

    def worker_is_running(self):
        return self.cancel_button.isEnabled()

    def open_first_result(self):
        for row, entry in enumerate(self.entries):
            if entry.get("output") and os.path.exists(entry["output"]):
                self.open_result(row, 7)
                return

    def download_all_results(self):
        outputs = [Path(entry["output"]) for entry in self.entries if entry.get("output") and os.path.exists(entry["output"])]
        if len(outputs) < 2:
            self.open_first_result(); return
        archive = unique_path(Path(self.output_dir) / "converted_files.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for output in outputs:
                if output.is_dir():
                    for item in output.rglob("*"):
                        if item.is_file(): bundle.write(item, item.relative_to(output.parent))
                else:
                    bundle.write(output, output.name)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(archive)))
        self.status_requested.emit(f"Created {archive.name} with {len(outputs)} result(s)")

    def open_result(self, row, column):
        if column != 7 or row >= len(self.entries):
            return
        result = self.entries[row].get("output")
        if result and os.path.exists(result):
            QDesktopServices.openUrl(QUrl.fromLocalFile(result))


class DocumentStudioWorkspace(ConverterWorkspace):
    pdf_action_requested = Signal(str)

    def __init__(self, title, subtitle, formats):
        super().__init__(title, subtitle, "Document", formats, accepted_categories={"Document", "Image"})
        self._build_document_controls()

    def _build_document_controls(self):
        controls = panel(); layout = QVBoxLayout(controls); layout.setContentsMargins(16, 12, 16, 12); layout.setSpacing(8)
        row = QHBoxLayout()
        label = QLabel("Conversion mode"); label.setObjectName("SectionTitle")
        self.conversion_mode = QComboBox(); self.conversion_mode.addItems(["Exact Visual Preservation", "Editable Conversion", "Smart Hybrid Conversion"])
        self.conversion_mode.currentTextChanged.connect(lambda *_: self._update_document_preview())
        row.addWidget(label); row.addWidget(self.conversion_mode, 1); layout.addLayout(row)
        hint = QLabel("The common output selector above is shared by every queued file. Exact Visual embeds rendered pages to preserve appearance; Editable reconstructs text and tables where possible; Hybrid combines both. Features unavailable in the target format can still require adaptation.")
        hint.setObjectName("SettingHint"); hint.setWordWrap(True); layout.addWidget(hint)
        self.document_preview = QLabel("Preview: choose a source and target to review the conversion mode before processing.")
        self.document_preview.setObjectName("SettingHint"); self.document_preview.setWordWrap(True); layout.addWidget(self.document_preview)
        self.root.insertWidget(1, controls)

        pdf_panel = panel(); pdf_layout = QVBoxLayout(pdf_panel); pdf_layout.setContentsMargins(16, 12, 16, 12); pdf_layout.setSpacing(8)
        pdf_title = QLabel("PDF Studio"); pdf_title.setObjectName("SectionTitle"); pdf_layout.addWidget(pdf_title)
        action_grid = QGridLayout(); action_grid.setSpacing(6)
        actions = [
            ("PDF → images", "to_images"), ("Images → PDF", "images_to_pdf"), ("Merge PDFs", "merge"),
            ("Split PDFs", "split"), ("Extract pages", "extract"), ("Reorder pages", "reorder"),
            ("Rotate pages", "rotate"), ("Delete pages", "delete"), ("Add page numbers", "page_numbers"),
            ("Add watermark", "watermark"), ("Protect PDF", "protect"), ("Remove password", "remove_password"),
            ("Edit metadata", "metadata"), ("Optimize PDF", "optimize"),
            ("Inspect quality", "quality"),
        ]
        for index, (text, action) in enumerate(actions):
            button = QPushButton(text); button.clicked.connect(lambda checked=False, value=action: self.pdf_action_requested.emit(value))
            action_grid.addWidget(button, index // 3, index % 3)
        pdf_layout.addLayout(action_grid)
        fields = QHBoxLayout()
        self.page_range = QLineEdit(); self.page_range.setPlaceholderText("Pages e.g. 1,3-5")
        self.watermark_text = QLineEdit(); self.watermark_text.setPlaceholderText("Watermark text")
        self.pdf_password = QLineEdit(); self.pdf_password.setPlaceholderText("Password (if authorized)"); self.pdf_password.setEchoMode(QLineEdit.Password)
        self.metadata_title = QLineEdit(); self.metadata_title.setPlaceholderText("PDF title")
        self.metadata_author = QLineEdit(); self.metadata_author.setPlaceholderText("PDF author")
        fields.addWidget(QLabel("Page range")); fields.addWidget(self.page_range, 1); fields.addWidget(self.watermark_text, 1); fields.addWidget(self.pdf_password, 1)
        pdf_layout.addLayout(fields)
        metadata = QHBoxLayout(); metadata.addWidget(QLabel("Metadata")); metadata.addWidget(self.metadata_title, 1); metadata.addWidget(self.metadata_author, 1)
        pdf_layout.addLayout(metadata)
        self.root.insertWidget(2, pdf_panel)

    def _target_options(self, category, path=None):
        if category == "Image":
            return ["PDF"]
        return super()._target_options(category, path)

    def build_jobs(self, output_dir):
        jobs = super().build_jobs(output_dir)
        for job in jobs:
            job.conversion_mode = self.conversion_mode.currentText()
        return jobs

    def add_files(self, paths):
        result = super().add_files(paths)
        self._update_document_preview()
        return result

    def _target_changed(self, entry, value):
        super()._target_changed(entry, value)
        self._update_document_preview(entry, value)

    def _update_document_preview(self, entry=None, target=None):
        if entry is None and self.entries:
            entry = self.entries[0]
        if entry is None:
            self.document_preview.setText("Preview: choose a source and target to review the conversion mode before processing.")
            return
        target = target or entry.get("target", "")
        self.document_preview.setText(f"Preview plan: {entry['detected']} → {target} • {self.conversion_mode.currentText()} • final output is created only when Convert is clicked.")

    def pdf_parameters(self):
        return {"pages": self.page_range.text(), "watermark": self.watermark_text.text(), "password": self.pdf_password.text(), "title": self.metadata_title.text(), "author": self.metadata_author.text()}


class ImageStudioWorkspace(ConverterWorkspace):
    def __init__(self):
        super().__init__("Image Studio", "Convert, edit and optimize images with non-destructive batch controls.", "Image", formats_for("Image"))
        self._build_image_controls()

    def _build_image_controls(self):
        controls = panel(); grid = QGridLayout(controls); grid.setContentsMargins(16, 12, 16, 12); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(6)
        self.width = QSpinBox(); self.width.setRange(0, 20000); self.width.setSpecialValueText("Original")
        self.height = QSpinBox(); self.height.setRange(0, 20000); self.height.setSpecialValueText("Original")
        self.keep_aspect = QCheckBox("Keep aspect ratio"); self.keep_aspect.setChecked(True)
        self.rotation = QComboBox(); self.rotation.addItems(["0", "90", "180", "270"])
        self.flip = QComboBox(); self.flip.addItems(["None", "Horizontal", "Vertical"])
        self.dpi = QSpinBox(); self.dpi.setRange(0, 2400); self.dpi.setSpecialValueText("Keep DPI")
        self.background = QLineEdit(); self.background.setPlaceholderText("Background color e.g. #ffffff")
        self.border = QSpinBox(); self.border.setRange(0, 100); self.border.setSuffix(" px")
        fields = [("Width", self.width), ("Height", self.height), ("Rotation", self.rotation), ("Flip", self.flip), ("DPI", self.dpi), ("Border", self.border)]
        for index, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label), index // 2, (index % 2) * 2); grid.addWidget(widget, index // 2, (index % 2) * 2 + 1)
        grid.addWidget(self.keep_aspect, 3, 0, 1, 2); grid.addWidget(QLabel("Background"), 3, 2); grid.addWidget(self.background, 3, 3)
        adjust = QHBoxLayout()
        self.brightness = self._slider(100); self.contrast = self._slider(100); self.saturation = self._slider(100)
        for label, slider in (("Brightness", self.brightness), ("Contrast", self.contrast), ("Saturation", self.saturation)):
            adjust.addWidget(QLabel(label)); adjust.addWidget(slider, 1)
        grid.addLayout(adjust, 4, 0, 1, 4)
        self.root.insertWidget(1, controls)

        preview = panel(); preview_layout = QHBoxLayout(preview); preview_layout.setContentsMargins(12, 10, 12, 10)
        self.before_preview = QLabel("Original preview"); self.before_preview.setObjectName("PreviewImage"); self.before_preview.setAlignment(Qt.AlignCenter); self.before_preview.setMinimumHeight(120)
        self.after_preview = QLabel("Output preview"); self.after_preview.setObjectName("PreviewImage"); self.after_preview.setAlignment(Qt.AlignCenter); self.after_preview.setMinimumHeight(120)
        self.edit_summary = QLabel("Preview changes will appear here. No output file is written until Convert is clicked.")
        self.edit_summary.setObjectName("SettingHint"); self.edit_summary.setWordWrap(True)
        preview_layout.addWidget(self.before_preview, 1); preview_layout.addWidget(self.after_preview, 1)
        preview_layout.addWidget(self.edit_summary); self.root.insertWidget(2, preview)
        controls_to_preview = (self.width, self.height, self.keep_aspect, self.rotation, self.flip, self.dpi, self.background, self.border, self.brightness, self.contrast, self.saturation, self.quality_combo)
        for control in controls_to_preview:
            signal = getattr(control, "valueChanged", None) or getattr(control, "currentTextChanged", None) or getattr(control, "textChanged", None)
            if signal:
                signal.connect(lambda *_: self._refresh_live_preview())

    @staticmethod
    def _slider(value):
        slider = QSlider(Qt.Horizontal); slider.setRange(50, 150); slider.setValue(value); slider.setToolTip("100% is unchanged")
        return slider

    def add_files(self, paths):
        result = super().add_files(paths)
        if self.entries:
            self._set_preview(self.entries[0]["path"], self.before_preview)
            self._refresh_live_preview()
        return result

    def _set_preview(self, path, label):
        pixmap = QPixmap(path)
        if not pixmap.isNull(): label.setPixmap(pixmap.scaled(360, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _target_changed(self, entry, value):
        super()._target_changed(entry, value)
        self._refresh_live_preview()

    def _preview_job(self):
        if not self.entries:
            return None
        entry = self.entries[0]
        job = ConversionJob(entry["path"], entry["target"], "Image", self.output_dir, quality=self.quality_combo.currentText())
        job.width = self.width.value(); job.height = self.height.value(); job.keep_aspect = self.keep_aspect.isChecked()
        job.rotation = int(self.rotation.currentText()); job.flip = self.flip.currentText(); job.dpi = self.dpi.value()
        job.background_color = self.background.text().strip(); job.border = self.border.value()
        job.brightness = self.brightness.value() / 100; job.contrast = self.contrast.value() / 100; job.saturation = self.saturation.value() / 100
        return job

    def _refresh_live_preview(self):
        job = self._preview_job()
        if not job:
            return
        try:
            image = ImageEngine().preview(job.source, job)
            buffer = io.BytesIO(); image.save(buffer, format="PNG")
            pixmap = QPixmap(); pixmap.loadFromData(buffer.getvalue(), "PNG")
            self.after_preview.setPixmap(pixmap.scaled(360, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            changes = []
            if job.width or job.height: changes.append(f"resize {job.width or 'auto'}×{job.height or 'auto'}")
            if job.rotation: changes.append(f"rotate {job.rotation}°")
            if job.flip != "None": changes.append(f"flip {job.flip.lower()}")
            if job.brightness != 1: changes.append(f"brightness {job.brightness:.0%}")
            if job.contrast != 1: changes.append(f"contrast {job.contrast:.0%}")
            if job.saturation != 1: changes.append(f"saturation {job.saturation:.0%}")
            if job.border: changes.append(f"{job.border}px border")
            if job.background_color: changes.append(f"background {job.background_color}")
            changes.append(f"{job.quality.lower()} encoding")
            detail = ", ".join(changes) if changes else "No visual edits selected"
            self.edit_summary.setText(f"Live preview: {detail}. Target format: {job.target_format}. No output is marked complete until Convert is clicked.")
        except Exception as exc:
            self.after_preview.setText("Preview unavailable for this source")
            self.edit_summary.setText(f"Preview unavailable: {exc}")

    def update_jobs(self, jobs):
        super().update_jobs(jobs)
        if self.entries and self.entries[0].get("output"):
            self._set_preview(self.entries[0]["output"], self.after_preview)
            self.edit_summary.setText(f"Final output ready: {Path(self.entries[0]['output']).name} • status is Completed.")

    def build_jobs(self, output_dir):
        jobs = super().build_jobs(output_dir)
        for job in jobs:
            job.width = self.width.value(); job.height = self.height.value(); job.keep_aspect = self.keep_aspect.isChecked()
            job.rotation = int(self.rotation.currentText()); job.flip = self.flip.currentText(); job.dpi = self.dpi.value()
            job.background_color = self.background.text().strip(); job.border = self.border.value()
            job.brightness = self.brightness.value() / 100; job.contrast = self.contrast.value() / 100; job.saturation = self.saturation.value() / 100
        return jobs


class WaveformPreview(QWidget):
    def __init__(self):
        super().__init__(); self.seed = 1; self.setMinimumHeight(90)

    def set_file(self, path):
        self.seed = abs(hash(path)) % 997 + 1; self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing); painter.setPen(QPen(QColor("#2878d0"), 2))
        mid = self.height() / 2; width = max(1, self.width())
        for x in range(0, width, 5):
            amplitude = 10 + ((x * self.seed) % 31); painter.drawLine(x, mid - amplitude, x, mid + amplitude)


class AudioStudioWorkspace(ConverterWorkspace):
    def __init__(self):
        super().__init__("Audio Studio", "Convert, trim and optimize audio with waveform-aware batch controls.", "Audio", formats_for("Audio"), accepted_categories={"Audio", "Video"})
        self._build_audio_controls()

    def _build_audio_controls(self):
        controls = panel(); grid = QGridLayout(controls); grid.setContentsMargins(16, 12, 16, 12); grid.setSpacing(8)
        self.trim_start = QDoubleSpinBox(); self.trim_start.setRange(0, 86400); self.trim_start.setSuffix(" s")
        self.trim_end = QDoubleSpinBox(); self.trim_end.setRange(0, 86400); self.trim_end.setSuffix(" s")
        self.volume = QSlider(Qt.Horizontal); self.volume.setRange(0, 200); self.volume.setValue(100)
        self.speed = QComboBox(); self.speed.addItems(["0.5", "0.75", "1.0", "1.25", "1.5", "2.0"]); self.speed.setCurrentText("1.0")
        self.bitrate = QComboBox(); self.bitrate.addItems(["Auto", "96k", "128k", "192k", "256k", "320k"])
        self.sample_rate = QComboBox(); self.sample_rate.addItems(["Original", "44100", "48000", "96000"])
        self.channels = QComboBox(); self.channels.addItems(["Original", "Mono", "Stereo"])
        self.fade_in = QDoubleSpinBox(); self.fade_in.setRange(0, 120); self.fade_in.setSuffix(" s")
        self.fade_out = QDoubleSpinBox(); self.fade_out.setRange(0, 120); self.fade_out.setSuffix(" s")
        fields = [("Trim start", self.trim_start), ("Trim end", self.trim_end), ("Speed", self.speed), ("Bitrate", self.bitrate), ("Sample rate", self.sample_rate), ("Channels", self.channels), ("Fade in", self.fade_in), ("Fade out", self.fade_out)]
        for index, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label), index // 2, (index % 2) * 2); grid.addWidget(widget, index // 2, (index % 2) * 2 + 1)
        grid.addWidget(QLabel("Volume"), 4, 0); grid.addWidget(self.volume, 4, 1, 1, 3)
        self.root.insertWidget(1, controls)
        wave_panel = panel(); wave_layout = QVBoxLayout(wave_panel); wave_layout.setContentsMargins(12, 10, 12, 10)
        self.waveform = WaveformPreview(); wave_layout.addWidget(self.waveform)
        self.audio_info = QLabel("Drop an audio or video file to preview its waveform"); self.audio_info.setObjectName("SettingHint"); wave_layout.addWidget(self.audio_info)
        self.audio_plan = QLabel("Preview plan: adjust settings first; Convert writes the file."); self.audio_plan.setObjectName("SettingHint"); self.audio_plan.setWordWrap(True); wave_layout.addWidget(self.audio_plan)
        self.root.insertWidget(2, wave_panel)
        for control in (self.trim_start, self.trim_end, self.volume, self.speed, self.bitrate, self.sample_rate, self.channels, self.fade_in, self.fade_out):
            signal = getattr(control, "valueChanged", None) or getattr(control, "currentTextChanged", None)
            if signal:
                signal.connect(lambda *_: self._update_audio_plan())

    def add_files(self, paths):
        result = super().add_files(paths)
        if self.entries:
            path = self.entries[0]["path"]; self.waveform.set_file(path)
            duration = "duration unavailable"
            ffprobe = find_ffprobe()
            if ffprobe:
                try:
                    probe = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json", "-show_entries", "format=duration", path], capture_output=True, text=True, check=True)
                    seconds = float(json.loads(probe.stdout).get("format", {}).get("duration", 0))
                    duration = f"{int(seconds // 60)}:{int(seconds % 60):02d}"
                except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
                    pass
            self.audio_info.setText(f"Preview: {Path(path).name}  •  {self.entries[0]['detected']} source  •  {duration}")
            self._update_audio_plan()
        return result

    def _update_audio_plan(self):
        self.audio_plan.setText(f"Preview plan: trim {self.trim_start.value():g}s–{self.trim_end.value():g}s • volume {self.volume.value()}% • speed {self.speed.currentText()}× • {self.bitrate.currentText()} • {self.channels.currentText()} channels. Convert when satisfied.")

    def build_jobs(self, output_dir):
        jobs = super().build_jobs(output_dir)
        for job in jobs:
            job.trim_start = self.trim_start.value(); job.trim_end = self.trim_end.value(); job.volume = self.volume.value() / 100
            job.speed = float(self.speed.currentText()); job.bitrate = "" if self.bitrate.currentText() == "Auto" else self.bitrate.currentText()
            job.sample_rate = 0 if self.sample_rate.currentText() == "Original" else int(self.sample_rate.currentText())
            job.channels = 0 if self.channels.currentText() == "Original" else (1 if self.channels.currentText() == "Mono" else 2)
            job.fade_in = self.fade_in.value(); job.fade_out = self.fade_out.value()
        return jobs


class VideoStudioWorkspace(ConverterWorkspace):
    def __init__(self):
        super().__init__("Video Studio", "Convert, edit, compress and preview video through FFmpeg.", "Video", formats_for("Video"))
        self._build_video_controls()

    def _build_video_controls(self):
        controls = panel(); grid = QGridLayout(controls); grid.setContentsMargins(16, 12, 16, 12); grid.setSpacing(8)
        self.operation = QComboBox(); self.operation.addItems(["Convert video", "Extract audio", "Video to GIF", "Create thumbnail", "Extract frames", "Merge selected videos", "Split video"])
        self.width = QSpinBox(); self.width.setRange(0, 10000); self.width.setSpecialValueText("Original")
        self.height = QSpinBox(); self.height.setRange(0, 10000); self.height.setSpecialValueText("Original")
        self.fps = QSpinBox(); self.fps.setRange(0, 240); self.fps.setSpecialValueText("Original")
        self.video_bitrate = QLineEdit(); self.video_bitrate.setPlaceholderText("e.g. 2M")
        self.video_codec = QComboBox(); self.video_codec.addItems(["Auto", "libx264", "libx265", "libvpx-vp9", "libaom-av1"])
        self.audio_codec = QComboBox(); self.audio_codec.addItems(["Auto", "aac", "libopus", "libmp3lame"])
        self.rotation = QComboBox(); self.rotation.addItems(["0", "90", "180", "270"])
        self.flip = QComboBox(); self.flip.addItems(["None", "Horizontal", "Vertical"])
        self.crop = QLineEdit(); self.crop.setPlaceholderText("w:h:x:y (optional)")
        self.speed = QComboBox(); self.speed.addItems(["0.5", "0.75", "1.0", "1.25", "1.5", "2.0"])
        self.mute = QCheckBox("Mute audio")
        self.subtitle = QLineEdit(); self.subtitle.setPlaceholderText("Subtitle file (.srt/.ass)")
        subtitle_button = QPushButton("Browse"); subtitle_button.clicked.connect(lambda: self._choose_file(self.subtitle, "Subtitle files (*.srt *.ass *.vtt)"))
        self.audio_track = QLineEdit(); self.audio_track.setPlaceholderText("Replacement audio track")
        audio_button = QPushButton("Browse"); audio_button.clicked.connect(lambda: self._choose_file(self.audio_track, "Audio files (*)"))
        self.timestamp = QDoubleSpinBox(); self.timestamp.setRange(0, 86400); self.timestamp.setSuffix(" s")
        self.trim_start = QDoubleSpinBox(); self.trim_start.setRange(0, 86400); self.trim_start.setSuffix(" s")
        self.trim_end = QDoubleSpinBox(); self.trim_end.setRange(0, 86400); self.trim_end.setSuffix(" s")
        fields = [("Operation", self.operation), ("Trim start", self.trim_start), ("Trim end / split", self.trim_end), ("Width", self.width), ("Height", self.height), ("Frame rate", self.fps), ("Video bitrate", self.video_bitrate), ("Video codec", self.video_codec), ("Audio codec", self.audio_codec), ("Rotation", self.rotation), ("Flip", self.flip), ("Crop", self.crop), ("Speed", self.speed), ("Thumbnail time", self.timestamp)]
        for index, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label), index // 4, (index % 4) * 2); grid.addWidget(widget, index // 4, (index % 4) * 2 + 1)
        grid.addWidget(self.mute, 4, 0, 1, 2); grid.addWidget(QLabel("Subtitles"), 4, 2); grid.addWidget(self.subtitle, 4, 3); grid.addWidget(subtitle_button, 4, 4)
        grid.addWidget(QLabel("Audio track"), 5, 0); grid.addWidget(self.audio_track, 5, 1, 1, 3); grid.addWidget(audio_button, 5, 4)
        self.root.insertWidget(1, controls)
        preview = panel(); preview_layout = QVBoxLayout(preview); preview_layout.setContentsMargins(12, 10, 12, 10)
        self.audio_output = QAudioOutput(); self.player = QMediaPlayer(); self.player.setAudioOutput(self.audio_output)
        self.video_preview = QVideoWidget(); self.video_preview.setObjectName("VideoPreview"); self.video_preview.setMinimumHeight(170); self.player.setVideoOutput(self.video_preview)
        self.video_info = QLabel("Drop a video to inspect its format and preview it externally"); self.video_info.setObjectName("SettingHint")
        self.video_plan = QLabel("Preview plan: adjust settings first; the source preview is unchanged until the final output is processed."); self.video_plan.setObjectName("SettingHint"); self.video_plan.setWordWrap(True)
        preview_layout.addWidget(self.video_preview)
        playback = QHBoxLayout(); self.play_button = QPushButton("Play / Pause"); self.play_button.clicked.connect(self._toggle_play); self.timeline = QSlider(Qt.Horizontal); self.timeline.setRange(0, 0); self.timeline.sliderMoved.connect(self.player.setPosition)
        self.player.positionChanged.connect(self.timeline.setValue); self.player.durationChanged.connect(lambda value: self.timeline.setRange(0, value)); playback.addWidget(self.play_button); playback.addWidget(self.timeline, 1); preview_layout.addLayout(playback); preview_layout.addWidget(self.video_info); preview_layout.addWidget(self.video_plan); self.root.insertWidget(2, preview)
        self.operation.currentTextChanged.connect(lambda *_: self._refresh_common_targets())
        for control in (self.operation, self.width, self.height, self.fps, self.video_bitrate, self.video_codec, self.audio_codec, self.rotation, self.flip, self.crop, self.speed, self.mute, self.subtitle, self.audio_track, self.trim_start, self.trim_end):
            signal = getattr(control, "valueChanged", None) or getattr(control, "currentTextChanged", None) or getattr(control, "textChanged", None) or getattr(control, "stateChanged", None)
            if signal:
                signal.connect(lambda *_: self._update_video_plan())

    @staticmethod
    def _choose_file(widget, filter_text):
        path, _ = QFileDialog.getOpenFileName(widget, "Choose file", "", filter_text)
        if path: widget.setText(path)

    def add_files(self, paths):
        result = super().add_files(paths)
        if self.entries:
            entry = self.entries[0]; self.player.setSource(QUrl.fromLocalFile(entry["path"])); self.video_info.setText(f"{Path(entry['path']).name}  •  {entry['detected']}  •  {Path(entry['path']).stat().st_size // 1024} KB")
            self._update_video_plan()
        return result

    def _update_video_plan(self):
        self.video_plan.setText(f"Preview plan: {self.operation.currentText()} • {self.width.value() or 'original'}×{self.height.value() or 'original'} • {self.fps.value() or 'original'} FPS • codec {self.video_codec.currentText()} / {self.audio_codec.currentText()} • speed {self.speed.currentText()}×. Convert when satisfied.")

    def _target_options(self, category, path=None):
        if category != "Video":
            return super()._target_options(category, path)
        operation = getattr(self, "operation", None)
        operation = operation.currentText() if operation else "Convert video"
        if operation == "Extract audio":
            return formats_for("Audio")
        if operation == "Video to GIF":
            return ["GIF"]
        if operation == "Create thumbnail":
            return ["JPEG"]
        if operation == "Extract frames":
            return ["PNG", "JPEG"]
        return super()._target_options(category, path)

    def _toggle_play(self):
        self.player.pause() if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState else self.player.play()

    def build_jobs(self, output_dir):
        jobs = super().build_jobs(output_dir); operation = self.operation.currentText()
        for job in jobs:
            job.operation = {"Convert video": "convert", "Extract audio": "convert", "Video to GIF": "convert", "Create thumbnail": "thumbnail", "Extract frames": "extract_frames", "Merge selected videos": "merge", "Split video": "split"}[operation]
            if operation == "Extract audio": job.target_format = self.output_format.currentData()
            elif operation == "Video to GIF": job.target_format = "GIF"
            elif operation == "Create thumbnail": job.target_format = "JPEG"
            elif operation == "Extract frames": job.target_format = self.output_format.currentData() or "PNG"
            job.width = self.width.value(); job.height = self.height.value(); job.frame_rate = self.fps.value()
            job.video_bitrate = self.video_bitrate.text().strip(); job.video_codec = "" if self.video_codec.currentText() == "Auto" else self.video_codec.currentText()
            job.audio_codec = "" if self.audio_codec.currentText() == "Auto" else self.audio_codec.currentText(); job.rotation = int(self.rotation.currentText()); job.flip = self.flip.currentText(); job.crop = self.crop.text().strip(); job.speed = float(self.speed.currentText()); job.mute = self.mute.isChecked(); job.subtitle_file = self.subtitle.text().strip(); job.audio_track = self.audio_track.text().strip(); job.options["thumbnail_time"] = self.timestamp.value()
            job.trim_start = self.trim_start.value(); job.trim_end = self.trim_end.value()
            if operation == "Merge selected videos": job.options["sources"] = [entry["path"] for entry in self.entries]
        return jobs[:1] if operation == "Merge selected videos" else jobs


class CompressionWorkspace(ConverterWorkspace):
    def __init__(self):
        super().__init__("Compression Studio", "Measure real size savings across images, video, audio, PDF, Office and archive files.", allow_mixed=True)
        self._build_compression_controls()

    def _build_compression_controls(self):
        controls = panel(); layout = QHBoxLayout(controls); layout.setContentsMargins(16, 12, 16, 12); layout.setSpacing(10)
        self.profile = QComboBox(); self.profile.addItems(["Smallest Size", "Balanced", "Best Quality", "Custom"])
        self.custom_quality = QSpinBox(); self.custom_quality.setRange(1, 100); self.custom_quality.setValue(82); self.custom_quality.setSuffix(" quality")
        self.target_width = QSpinBox(); self.target_width.setRange(0, 10000); self.target_width.setSpecialValueText("Original width")
        self.target_size = QSpinBox(); self.target_size.setRange(0, 1024 * 1024); self.target_size.setSpecialValueText("No target size"); self.target_size.setSuffix(" MB")
        layout.addWidget(QLabel("Compression profile")); layout.addWidget(self.profile); layout.addWidget(self.custom_quality); layout.addWidget(QLabel("Width")); layout.addWidget(self.target_width); layout.addWidget(QLabel("Target")); layout.addWidget(self.target_size); layout.addStretch()
        self.root.insertWidget(1, controls)

    def _target_options(self, category, path=None):
        allowed = {"Image": ["PNG", "JPEG", "WEBP", "AVIF"], "Audio": ["MP3", "AAC", "OGG", "OPUS"], "Video": ["MP4", "WEBM", "MKV"], "Document": ["PDF", "DOCX", "XLSX", "ODS", "ODT"], "Archive": ["ZIP", "7Z"]}.get(category, [])
        actual = capabilities_for(path, category) if path else allowed
        return [option for option in allowed if option in actual]

    def build_jobs(self, output_dir):
        jobs = super().build_jobs(output_dir)
        for job in jobs:
            source_category = job.category
            job.category = "Compression"; job.operation = "compress"; job.options.update({"profile": self.profile.currentText(), "custom_quality": self.custom_quality.value(), "target_width": self.target_width.value(), "target_bytes": self.target_size.value() * 1024 * 1024, "source_category": source_category})
            if source_category == "Image": job.quality = "Maximum" if self.profile.currentText() == "Best Quality" else ("Balanced" if self.profile.currentText() == "Balanced" else "High")
            if source_category == "Image" and self.target_width.value(): job.width = self.target_width.value(); job.keep_aspect = True
            if source_category == "Document":
                suffix = Path(job.source).suffix.lower().lstrip(".")
                job.target_format = {"pdf": "PDF", "docx": "DOCX", "pptx": "PPTX", "xlsx": "XLSX", "odt": "ODT", "ods": "ODS", "odp": "ODP"}.get(suffix, job.target_format)
        return jobs

    def update_jobs(self, jobs):
        super().update_jobs(jobs)
        by_path = {job.source: job for job in jobs}
        for row, entry in enumerate(self.entries):
            job = by_path.get(entry["path"])
            if not job: continue
            if job.status == "Completed":
                saved = job.original_bytes - job.output_bytes
                ratio = (job.output_bytes / job.original_bytes) if job.original_bytes else 0
                text = f"{job.output_bytes:,} bytes • saved {saved:,} • ratio {ratio:.2%} • {job.elapsed_seconds:.2f}s"
                self.table.setItem(row, 7, QTableWidgetItem(text))


class ArchiveWorkspace(ConverterWorkspace):
    archive_action_requested = Signal(str)

    def __init__(self):
        super().__init__("Archive Studio", "Create, browse, extract, test and safely edit supported archives.", "Archive", formats_for("Archive"), accepted_categories={"Archive"})
        self._build_archive_controls()

    def _build_archive_controls(self):
        controls = panel(); grid = QGridLayout(controls); grid.setContentsMargins(16, 12, 16, 12); grid.setSpacing(8)
        self.operation = QComboBox(); self.operation.addItems(["Create archive", "Extract archive", "Browse contents", "Test integrity", "Add files", "Remove selected", "Rename selected", "Split volumes", "Join volumes"])
        self.level = QSpinBox(); self.level.setRange(0, 9); self.level.setValue(6)
        self.password = QLineEdit(); self.password.setPlaceholderText("Optional password"); self.password.setEchoMode(QLineEdit.Password)
        self.new_name = QLineEdit(); self.new_name.setPlaceholderText("New archive entry name")
        self.volume_mb = QSpinBox(); self.volume_mb.setRange(1, 4096); self.volume_mb.setValue(100); self.volume_mb.setSuffix(" MB")
        fields = [("Operation", self.operation), ("Compression level", self.level), ("Password", self.password), ("New name", self.new_name), ("Volume size", self.volume_mb)]
        for index, (label, widget) in enumerate(fields): grid.addWidget(QLabel(label), index // 3, (index % 3) * 2); grid.addWidget(widget, index // 3, (index % 3) * 2 + 1)
        self.root.insertWidget(1, controls)
        browse = QPushButton("Browse selected archive"); browse.clicked.connect(lambda: self.archive_action_requested.emit("browse")); self.root.insertWidget(2, browse)
        self.entry_table = QTableWidget(0, 4); self.entry_table.setHorizontalHeaderLabels(["Entry", "Size", "Packed", "Type"]); self.entry_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.entry_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.entry_table.setMinimumHeight(180); self.root.insertWidget(3, self.entry_table)

    def show_entries(self, entries):
        self.entry_table.setRowCount(0)
        for entry in entries:
            row = self.entry_table.rowCount(); self.entry_table.insertRow(row)
            values = (entry.get("name", ""), entry.get("size", ""), entry.get("packed", ""), "Folder" if entry.get("directory") else "File")
            for column, value in enumerate(values): self.entry_table.setItem(row, column, QTableWidgetItem(str(value)))

    def selected_entries(self):
        return [self.entry_table.item(index.row(), 0).text() for index in self.entry_table.selectionModel().selectedRows() if self.entry_table.item(index.row(), 0)]

    def add_files(self, paths):
        if self.operation.currentText() not in ("Create archive", "Add files"):
            return super().add_files(paths)
        accepted = 0; rejected = []
        for path in paths:
            if not os.path.exists(path) or any(item["path"] == path for item in self.entries): continue
            entry = {"path": path, "category": "Archive", "detected": Path(path).suffix.upper().lstrip("."), "options": list(self.formats), "target": "ZIP", "status": "Queued", "output": "", "error": ""}
            self.entries.append(entry); self._append_entry(entry); accepted += 1
        self.queue_count.setText(f"{len(self.entries)} items")
        if accepted: self.status_requested.emit(f"Added {accepted} archive source item(s)")
        return accepted, rejected

    def build_jobs(self, output_dir):
        jobs = super().build_jobs(output_dir); operation = self.operation.currentText()
        action = {"Create archive": "create", "Extract archive": "extract", "Browse contents": "browse", "Test integrity": "test", "Add files": "add", "Remove selected": "remove", "Rename selected": "rename", "Split volumes": "split_volumes", "Join volumes": "join_volumes"}[operation]
        for job in jobs:
            job.operation = action; job.options.update({"level": self.level.value(), "password": self.password.text(), "new_name": self.new_name.text(), "volume_mb": self.volume_mb.value(), "selected": self.selected_entries()})
            if action == "create": job.options["sources"] = [entry["path"] for entry in self.entries]
        return jobs[:1] if action in {"create", "merge", "split_volumes", "join_volumes"} else jobs

class HomeWorkspace(BaseWorkspace):
    tool_requested = Signal(str)
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__("Welcome to Universal Tools", "A focused Windows workspace for converting, organizing and protecting your files locally.")
        hero = panel(); hero_layout = QVBoxLayout(hero); hero_layout.setContentsMargins(20, 18, 20, 18); hero_layout.setSpacing(8)
        greeting = QLabel("Everything you need for everyday files")
        greeting.setObjectName("SectionTitle")
        detail = QLabel("Drop files into Smart Converter, choose one format supported by the complete queue, and keep the batch moving in the background.")
        detail.setObjectName("SubTitle"); detail.setWordWrap(True)
        hero_layout.addWidget(greeting); hero_layout.addWidget(detail)
        actions = QHBoxLayout()
        for label, key in (("Smart Converter", "Smart Converter"), ("Document & Data Studio", "Document & Data Studio"), ("Compression Studio", "Compression Studio")):
            button = QPushButton(label); button.setObjectName("Primary" if key == "Smart Converter" else "")
            button.clicked.connect(lambda checked=False, value=key: self.tool_requested.emit(value)); actions.addWidget(button)
        actions.addStretch(); hero_layout.addLayout(actions)
        self.root.addWidget(hero)

        stats = QGridLayout(); stats.setSpacing(10)
        self.stat_files = StatCard("Files processed")
        self.stat_completed = StatCard("Completed conversions")
        self.stat_saved = StatCard("Output folder")
        stats.addWidget(self.stat_files, 0, 0); stats.addWidget(self.stat_completed, 0, 1); stats.addWidget(self.stat_saved, 0, 2)
        self.root.addLayout(stats)

        lower = QHBoxLayout(); lower.setSpacing(12)
        drop = DropZone("Drop files to start", "Universal Smart Converter will detect each format")
        drop.files_dropped.connect(self.files_dropped.emit)
        lower.addWidget(drop, 1)
        recent_column = QVBoxLayout(); recent_column.setSpacing(10)
        recent = panel(); recent_layout = QVBoxLayout(recent); recent_layout.setContentsMargins(16, 14, 16, 14)
        recent_title = QLabel("Recently used tools"); recent_title.setObjectName("SectionTitle"); recent_layout.addWidget(recent_title)
        self.recent_list = QListWidget(); self.recent_list.setObjectName("RecentList"); self.recent_list.setMaximumHeight(180)
        self.recent_list.itemClicked.connect(lambda item: self.tool_requested.emit(item.data(Qt.UserRole)))
        recent_layout.addWidget(self.recent_list)
        recent_column.addWidget(recent)
        activity = panel(); activity_layout = QVBoxLayout(activity); activity_layout.setContentsMargins(16, 14, 16, 14)
        activity_title = QLabel("Recent conversions"); activity_title.setObjectName("SectionTitle"); activity_layout.addWidget(activity_title)
        self.activity_list = QListWidget(); self.activity_list.setObjectName("RecentList"); self.activity_list.setMaximumHeight(150); activity_layout.addWidget(self.activity_list)
        recent_column.addWidget(activity)
        lower.addLayout(recent_column, 1)
        self.root.addLayout(lower)
        self.root.addStretch()

    def refresh(self, history, output_dir, recent_tools=None):
        completed = sum(item.get("status") == "Completed" for item in history)
        self.stat_files.set_value(len(history))
        self.stat_completed.set_value(completed)
        self.stat_saved.set_value(Path(output_dir).name or output_dir)
        self.recent_list.clear()
        for tool in (recent_tools or ["Smart Converter", "Document & Data Studio", "Images", "Compression Studio"]):
            item = QListWidgetItem(tool); item.setData(Qt.UserRole, tool); self.recent_list.addItem(item)
        self.activity_list.clear()
        for record in history[:6]:
            source = Path(record.get("source", "")).name or "Unknown file"
            self.activity_list.addItem(QListWidgetItem(f"{source}  •  {record.get('status', 'Queued')}"))


class LandingWorkspace(BaseWorkspace):
    launch_requested = Signal(str)
    files_dropped = Signal(list)

    def __init__(self, title, subtitle, actions, body):
        super().__init__(title, subtitle)
        card = panel(); layout = QVBoxLayout(card); layout.setContentsMargins(20, 18, 20, 18); layout.setSpacing(10)
        text = QLabel(body); text.setObjectName("SubTitle"); text.setWordWrap(True); layout.addWidget(text)
        action_row = QHBoxLayout()
        for label, key in actions:
            button = QPushButton(label); button.clicked.connect(lambda checked=False, value=key: self.launch_requested.emit(value)); action_row.addWidget(button)
        action_row.addStretch(); layout.addLayout(action_row)
        self.root.addWidget(card)
        drop = DropZone("Drop files into this workspace", "Choose a tool above or send files to Smart Converter")
        drop.files_dropped.connect(self.files_dropped.emit); self.root.addWidget(drop)
        self.root.addStretch()


class FileManagerWorkspace(BaseWorkspace):
    def __init__(self, output_dir):
        super().__init__("File Manager", "Review converted files and open the folders used by Universal Tools.")
        toolbar = QHBoxLayout()
        self.path_label = QLabel(output_dir); self.path_label.setObjectName("SettingHint")
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        open_button = QPushButton("Open folder"); open_button.setObjectName("Primary"); open_button.clicked.connect(self.open_folder)
        toolbar.addWidget(self.path_label, 1); toolbar.addWidget(refresh); toolbar.addWidget(open_button); self.root.addLayout(toolbar)
        self.files = QListWidget(); self.files.itemDoubleClicked.connect(self.open_item); self.root.addWidget(self.files, 1)
        self.output_dir = output_dir; self.refresh()

    def set_output_dir(self, path): self.output_dir = path; self.path_label.setText(path); self.refresh()

    def refresh(self):
        self.files.clear()
        folder = Path(self.output_dir)
        if not folder.exists(): return
        for item in sorted(folder.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
            if item.is_file():
                list_item = QListWidgetItem(f"{item.name}  •  {item.stat().st_size // 1024} KB")
                list_item.setData(Qt.UserRole, str(item)); self.files.addItem(list_item)

    def open_item(self, item):
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))

    def open_folder(self):
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))


class UtilitiesWorkspace(BaseWorkspace):
    def __init__(self):
        super().__init__("Utilities", "Inspect files, review metadata and make quick local checks before converting.")
        drop = DropZone("Drop a file to inspect", "File details stay on this PC")
        drop.files_dropped.connect(self.inspect)
        self.root.addWidget(drop)
        card = panel(); layout = QVBoxLayout(card); layout.setContentsMargins(18, 16, 18, 16)
        self.details = QLabel("No file selected"); self.details.setObjectName("SubTitle"); self.details.setWordWrap(True); layout.addWidget(self.details)
        self.root.addWidget(card); self.root.addStretch()

    def inspect(self, paths):
        if not paths: return
        path = Path(paths[0])
        self.details.setText(f"Name: {path.name}\nType: {path.suffix.upper() or 'Unknown'}\nSize: {path.stat().st_size:,} bytes\nLocation: {path.parent}")


class FavoritesWorkspace(BaseWorkspace):
    tool_requested = Signal(str)

    def __init__(self, favorites):
        super().__init__("Favorites", "Your quick access tools.")
        card = panel(); layout = QVBoxLayout(card); layout.setContentsMargins(18, 16, 18, 16); layout.setSpacing(8)
        for name in favorites:
            button = QPushButton(f"☆  {name}"); button.setObjectName("Nav")
            button.clicked.connect(lambda checked=False, value=name: self.tool_requested.emit(value)); layout.addWidget(button)
        self.root.addWidget(card); self.root.addStretch()


class HistoryWorkspace(BaseWorkspace):
    def __init__(self):
        super().__init__("Conversion history", "Recent activity from this device.")
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["Date", "Source", "Status", "Output / Details"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False); self.root.addWidget(self.table, 1)

    def set_history(self, records):
        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount(); self.table.insertRow(row)
            for column, value in enumerate((record.get("date", ""), record.get("source", ""), record.get("status", ""), record.get("detail", ""))):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))


class SettingsWorkspace(BaseWorkspace):
    preference_changed = Signal(str, object)
    reset_requested = Signal()
    custom_background_requested = Signal()

    def __init__(self, preferences):
        super().__init__("Settings", "Personalize Universal Tools and keep conversion behavior predictable.")
        scroll = QScrollArea(); scroll.setObjectName("SettingsScroll"); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget(); content.setObjectName("SettingsContent")
        layout = QVBoxLayout(content); layout.setContentsMargins(0, 0, 10, 0); layout.setSpacing(12)

        appearance = panel(); appearance_layout = QVBoxLayout(appearance); appearance_layout.setContentsMargins(17, 14, 17, 14); appearance_layout.setSpacing(8)
        title = QLabel("Appearance"); title.setObjectName("SectionTitle"); appearance_layout.addWidget(title)
        self.theme_combo = self._combo(appearance_layout, "Theme", [("Light", "light"), ("Dark", "dark")], "theme")
        self.glass_combo = self._combo(appearance_layout, "Glassmorphism density", [("Light", "light"), ("Dense", "dense")], "glass")
        families = ["Segoe UI Variable", "Segoe UI", "Arial", "Calibri", "Tahoma", "Verdana", "Consolas"]
        available = set(QFontDatabase.families()); families = [family for family in families if family in available] or families
        self.text_style_combo = self._combo(appearance_layout, "Text style", [(family, family) for family in families], "text_style")
        self.accent_combo = self._combo(appearance_layout, "Accent color", [("Blue", "blue"), ("Teal", "teal"), ("Violet", "violet"), ("Rose", "rose")], "accent")
        layout.addWidget(appearance)

        background = panel(); background_layout = QVBoxLayout(background); background_layout.setContentsMargins(17, 14, 17, 14); background_layout.setSpacing(8)
        background_title = QLabel("Background"); background_title.setObjectName("SectionTitle"); background_layout.addWidget(background_title)
        self.background_combo = self._combo(background_layout, "Built-in background theme", [("Mist", "mist"), ("Sky", "sky"), ("Aurora", "aurora"), ("Graphite", "graphite"), ("Custom image", "custom")], "background")
        self.custom_background_button = QPushButton("Choose custom image…"); self.custom_background_button.clicked.connect(self.custom_background_requested.emit); background_layout.addWidget(self.custom_background_button)
        self.custom_background_label = QLabel("No custom image selected"); self.custom_background_label.setObjectName("SettingHint"); self.custom_background_label.setWordWrap(True); background_layout.addWidget(self.custom_background_label)
        self.compact_nav = QCheckBox("Use compact navigation spacing"); self.compact_nav.stateChanged.connect(lambda value: self.preference_changed.emit("compact_nav", bool(value))); background_layout.addWidget(self.compact_nav)
        layout.addWidget(background)

        behavior = panel(); behavior_layout = QVBoxLayout(behavior); behavior_layout.setContentsMargins(17, 14, 17, 14); behavior_layout.setSpacing(8)
        behavior_title = QLabel("Conversion behavior"); behavior_title.setObjectName("SectionTitle"); behavior_layout.addWidget(behavior_title)
        self.confirm_clear = QCheckBox("Ask before clearing the conversion queue"); self.confirm_clear.stateChanged.connect(lambda value: self.preference_changed.emit("confirm_clear", bool(value))); behavior_layout.addWidget(self.confirm_clear)
        self.show_loss_warning = QCheckBox("Warn when a conversion may lose information"); self.show_loss_warning.stateChanged.connect(lambda value: self.preference_changed.emit("show_loss_warning", bool(value))); behavior_layout.addWidget(self.show_loss_warning)
        self.open_output = QCheckBox("Open the output folder after a completed batch"); self.open_output.stateChanged.connect(lambda value: self.preference_changed.emit("open_output", bool(value))); behavior_layout.addWidget(self.open_output)
        self.start_maximized = QCheckBox("Open Universal Tools maximized"); self.start_maximized.stateChanged.connect(lambda value: self.preference_changed.emit("start_maximized", bool(value))); behavior_layout.addWidget(self.start_maximized)
        fidelity = QLabel("Smart Converter detects each file independently, recommends a target, and routes document exports through native office filters. Exact Visual mode is available when preserving the rendered appearance is more important than independent editability."); fidelity.setObjectName("SettingHint"); fidelity.setWordWrap(True); behavior_layout.addWidget(fidelity)
        layout.addWidget(behavior)

        info = panel(); info_layout = QVBoxLayout(info); info_layout.setContentsMargins(17, 14, 17, 14)
        for heading, body in (("Privacy", "Files are processed locally by default."), ("Accessibility", "Keyboard-focusable controls, readable contrast and native file dialogs are used throughout."), ("Reset", "Restore the default light Windows-inspired workspace.")):
            label = QLabel(heading); label.setObjectName("SectionTitle"); text = QLabel(body); text.setObjectName("SettingHint"); text.setWordWrap(True); info_layout.addWidget(label); info_layout.addWidget(text)
        reset = QPushButton("Reset appearance and preferences"); reset.clicked.connect(self.reset_requested.emit); info_layout.addWidget(reset, 0, Qt.AlignRight)
        layout.addWidget(info); layout.addStretch()
        scroll.setWidget(content); self.root.addWidget(scroll, 1)
        self.sync(preferences)

    def _combo(self, layout, label, items, key):
        caption = QLabel(label); caption.setObjectName("SettingHint"); layout.addWidget(caption)
        combo = QComboBox();
        for text, value in items: combo.addItem(text, value)
        combo.currentIndexChanged.connect(lambda index, widget=combo, preference=key: self.preference_changed.emit(preference, widget.itemData(index)))
        layout.addWidget(combo)
        setattr(self, f"{key}_combo", combo)
        return combo

    def sync(self, preferences):
        for key, widget in (("theme", self.theme_combo), ("glass", self.glass_combo), ("text_style", self.text_style_combo), ("accent", self.accent_combo), ("background", self.background_combo)):
            widget.blockSignals(True); widget.setCurrentIndex(max(0, widget.findData(preferences.get(key)))); widget.blockSignals(False)
        for key, widget in (("compact_nav", self.compact_nav), ("confirm_clear", self.confirm_clear), ("show_loss_warning", self.show_loss_warning), ("open_output", self.open_output), ("start_maximized", self.start_maximized)):
            widget.blockSignals(True); widget.setChecked(bool(preferences.get(key, False))); widget.blockSignals(False)
        self.custom_background_label.setText(preferences.get("custom_background") or "No custom image selected")


def source_extensions(category, label):
    # Reverse the public format map without adding another format registry.
    from app.core.formats import IMAGE_FORMATS, AUDIO_FORMATS, VIDEO_FORMATS, DOCUMENT_FORMATS, ARCHIVE_FORMATS
    mapping = {"Image": IMAGE_FORMATS, "Audio": AUDIO_FORMATS, "Video": VIDEO_FORMATS, "Document": DOCUMENT_FORMATS, "Archive": ARCHIVE_FORMATS}
    return mapping.get(category, {}).get(label, [label.lower()])


def source_ext_for(category, label):
    return source_extensions(category, label)[0]
