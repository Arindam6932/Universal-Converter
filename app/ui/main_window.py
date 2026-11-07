import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QStatusBar, QToolButton, QVBoxLayout, QWidget,
)

from app.core.formats import formats_for
from app.core.history import HistoryStore
from app.engines.pdf_engine import PdfEngine
from app.engines.archive_engine import ArchiveEngine
from app.ui.styles import build_app_qss, build_palette
from app.ui.workspaces import (
    ArchiveWorkspace, AudioStudioWorkspace, CompressionWorkspace, ConverterWorkspace, DocumentStudioWorkspace, FavoritesWorkspace,
    FileManagerWorkspace, HistoryWorkspace, HomeWorkspace, ImageStudioWorkspace, VideoStudioWorkspace,
    LandingWorkspace, SettingsWorkspace, UtilitiesWorkspace, source_extensions,
)
from app.workers.conversion_worker import ConversionWorker


DOCUMENT_TARGETS = formats_for("Document")

NAV_GROUPS = [
    ("WORKSPACE", [("⌂", "Home", "home"), ("✦", "Smart Converter", "smart")]),
    ("CONVERSION", [
        ("▣", "Document & Data Studio", "documents"), ("▧", "Images", "images"),
        ("♫", "Audio", "audio"), ("▶", "Video", "video"),
        ("◒", "Compression Studio", "compression"), ("▤", "Archives", "archives"),
        ("▦", "Data & Spreadsheets", "data"),
    ]),
    ("TOOLS", [
        ("▱", "File Manager", "files"), ("◇", "Security & Privacy", "security"),
        ("◎", "OCR & AI Tools", "ocr"), ("⚙", "Utilities", "utilities"),
    ]),
    ("PERSONAL", [("◷", "History", "history"), ("☆", "Favorites", "favorites"), ("⚙", "Settings", "settings")]),
]

NAV_FORMATS = {
    "documents": formats_for("Document"),
    "audio": formats_for("Audio"),
    "video": formats_for("Video"),
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Tools")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 720)
        self.setAcceptDrops(True)
        self.settings = QSettings("Universal Tools", "Universal File Converter")
        self.preference_values = {
            "theme": self.settings.value("theme", "light"),
            "glass": self.settings.value("glass", "light"),
            "text_style": self.settings.value("text_style", "Segoe UI Variable"),
            "background": self.settings.value("background", "mist"),
            "accent": self.settings.value("accent", "blue"),
            "custom_background": self.settings.value("custom_background", ""),
            "compact_nav": self.settings.value("compact_nav", False, type=bool),
            "confirm_clear": self.settings.value("confirm_clear", True, type=bool),
            "show_loss_warning": self.settings.value("show_loss_warning", True, type=bool),
            "open_output": self.settings.value("open_output", False, type=bool),
            "start_maximized": self.settings.value("start_maximized", True, type=bool),
        }
        self.output_dir = self.settings.value("output_dir", str(Path.home() / "Documents" / "Converted Files")) or str(Path.home() / "Documents" / "Converted Files")
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.history = HistoryStore()
        self.jobs = []
        self.worker = None
        self.recent_tools = []
        self._apply_preferences()
        self._build_shell()
        self._build_workspaces()
        self._navigate("home")

    def _build_shell(self):
        shell = QFrame(); shell.setObjectName("Shell")
        outer = QHBoxLayout(shell); outer.setContentsMargins(14, 14, 14, 10); outer.setSpacing(14)

        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(276)
        side_layout = QVBoxLayout(sidebar); side_layout.setContentsMargins(14, 18, 14, 16); side_layout.setSpacing(4)
        brand = QLabel("◈  Universal"); brand.setObjectName("Brand")
        subbrand = QLabel("UNIVERSAL TOOLS"); subbrand.setObjectName("Eyebrow")
        side_layout.addWidget(brand); side_layout.addWidget(subbrand); side_layout.addSpacing(10)

        nav_scroll = QScrollArea(); nav_scroll.setObjectName("NavScroll"); nav_scroll.setWidgetResizable(True); nav_scroll.setFrameShape(QFrame.NoFrame); nav_scroll.viewport().setAutoFillBackground(False)
        nav_content = QWidget(); nav_content.setObjectName("NavContent")
        nav_layout = QVBoxLayout(nav_content); nav_layout.setContentsMargins(0, 0, 0, 0); nav_layout.setSpacing(2)
        self.nav_buttons = {}
        self.nav_submenus = {}
        for group, entries in NAV_GROUPS:
            heading = QLabel(group); heading.setObjectName("NavGroup"); nav_layout.addWidget(heading)
            for icon, label, key in entries:
                suffix = "  ▾" if key in NAV_FORMATS else ""
                button = QPushButton(f"{icon}  {label}{suffix}"); button.setObjectName("Nav"); button.setCheckable(True); button.setAccessibleName(label)
                if key in NAV_FORMATS:
                    button.clicked.connect(lambda checked=False, target=key: self._toggle_submenu(target))
                else:
                    button.clicked.connect(lambda checked=False, target=key: self._navigate(target))
                nav_layout.addWidget(button); self.nav_buttons[key] = button
                if key in NAV_FORMATS:
                    submenu = QFrame(); submenu.setObjectName("NavSubmenu")
                    submenu_layout = QVBoxLayout(submenu); submenu_layout.setContentsMargins(10, 0, 0, 4); submenu_layout.setSpacing(1)
                    for target in NAV_FORMATS[key]:
                        child = QPushButton(f"↳  To {target}"); child.setObjectName("NavSub")
                        child.setToolTip(f"Open {label} with {target} as the target format")
                        child.clicked.connect(lambda checked=False, nav_key=key, target_format=target: self._open_format_shortcut(nav_key, target_format))
                        submenu_layout.addWidget(child)
                    submenu.setVisible(False); nav_layout.addWidget(submenu); self.nav_submenus[key] = submenu
        nav_layout.addStretch(); nav_scroll.setWidget(nav_content); side_layout.addWidget(nav_scroll, 1)

        privacy = QFrame(); privacy.setObjectName("GlassCard")
        privacy_layout = QVBoxLayout(privacy); privacy_layout.setContentsMargins(12, 10, 12, 10)
        local = QLabel("✓  Files stay on this PC"); local.setObjectName("PrivacyLabel")
        local_detail = QLabel("Local-first processing"); local_detail.setObjectName("SubTitle")
        privacy_layout.addWidget(local); privacy_layout.addWidget(local_detail); side_layout.addWidget(privacy)

        main = QFrame(); main.setObjectName("MainPanel")
        main_layout = QVBoxLayout(main); main_layout.setContentsMargins(8, 4, 8, 0); main_layout.setSpacing(12)
        top = QHBoxLayout()
        self.breadcrumb = QLabel("HOME"); self.breadcrumb.setObjectName("Eyebrow"); top.addWidget(self.breadcrumb); top.addStretch()
        theme_label = QLabel("Theme"); theme_label.setObjectName("Eyebrow")
        self.theme_combo = QComboBox(); self.theme_combo.setObjectName("ThemeSelector"); self.theme_combo.addItems(["Light", "Dark"]); self.theme_combo.currentTextChanged.connect(self._theme_changed)
        output = QPushButton("Output location  ▾"); output.clicked.connect(self.choose_output); self.output_button = output
        settings_button = QToolButton(); settings_button.setText("⚙"); settings_button.setObjectName("SettingsButton"); settings_button.setToolTip("Open Settings"); settings_button.setFixedSize(38, 38); settings_button.clicked.connect(lambda: self._navigate("settings"))
        top.addWidget(theme_label); top.addWidget(self.theme_combo); top.addWidget(output); top.addWidget(settings_button); main_layout.addLayout(top)

        self.stack = QStackedWidget(); self.stack.setObjectName("WorkspaceStack"); main_layout.addWidget(self.stack, 1)
        outer.addWidget(sidebar); outer.addWidget(main, 1); self.setCentralWidget(shell)
        self.setStatusBar(QStatusBar()); self.statusBar().showMessage("Ready  •  Local processing enabled")

    def _build_workspaces(self):
        self.pages = {}
        self.home_page = HomeWorkspace(); self.pages["home"] = self.home_page
        self.smart_page = ConverterWorkspace("Smart Converter", "Detect formats, recommend targets and process mixed batches in one workspace.", allow_mixed=True)
        self.pages["smart"] = self.smart_page
        self.pages["documents"] = DocumentStudioWorkspace("Document & Data Studio", "Convert Word, spreadsheet, presentation, text, web, structured-data and PDF files through one common queue-level output selector.", DOCUMENT_TARGETS)
        self.pages["images"] = ImageStudioWorkspace()
        self.pages["audio"] = AudioStudioWorkspace()
        self.pages["video"] = VideoStudioWorkspace()
        self.pages["compression"] = CompressionWorkspace()
        self.pages["archives"] = ArchiveWorkspace()
        self.pages["data"] = ConverterWorkspace("Data & Spreadsheets", "Convert spreadsheets and delimited data to common spreadsheet, PDF, HTML, CSV and TSV targets.", "Document", ["XLSX", "XLS", "XLSM", "XLSB", "ODS", "FODS", "CSV", "TSV", "PDF", "HTML"])
        self.pages["files"] = FileManagerWorkspace(self.output_dir)
        self.pages["security"] = LandingWorkspace("Security & Privacy", "Review local-first processing and keep sensitive files on this device.", [("Open File Manager", "files"), ("Open Settings", "settings")], "Universal Tools does not silently upload source files. Use this workspace to review the local output area and privacy settings.")
        self.pages["ocr"] = LandingWorkspace("OCR & AI Tools", "A ready workspace for text extraction and assisted file workflows.", [("Open Smart Converter", "smart"), ("Open Document & Data Studio", "documents")], "OCR and AI engines can be registered without changing the navigation shell or background job manager.")
        self.pages["utilities"] = UtilitiesWorkspace()
        self.pages["history"] = HistoryWorkspace()
        self.pages["favorites"] = FavoritesWorkspace(["Smart Converter", "Document & Data Studio", "Images", "Compression Studio"])
        self.settings_page = SettingsWorkspace(self.preference_values); self.pages["settings"] = self.settings_page

        for key, page in self.pages.items():
            self.stack.addWidget(page)
            if isinstance(page, ConverterWorkspace):
                page.set_output_dir(self.output_dir)
                page.run_requested.connect(lambda page=page: self.start_conversion(page))
                page.cancel_requested.connect(self.cancel_conversion)
                page.output_requested.connect(self.choose_output)
                page.status_requested.connect(self.statusBar().showMessage)
            if isinstance(page, DocumentStudioWorkspace):
                page.pdf_action_requested.connect(lambda action, page=page: self.run_pdf_action(page, action))
            if isinstance(page, ArchiveWorkspace):
                page.archive_action_requested.connect(lambda action, page=page: self.run_archive_action(page, action))
            if isinstance(page, HomeWorkspace):
                page.tool_requested.connect(self._navigate_by_label); page.files_dropped.connect(self._start_with_files)
            if isinstance(page, LandingWorkspace):
                page.launch_requested.connect(self._navigate); page.files_dropped.connect(self._start_with_files)
            if isinstance(page, FavoritesWorkspace): page.tool_requested.connect(self._navigate_by_label)
        self.settings_page.preference_changed.connect(self._preference_changed)
        self.settings_page.reset_requested.connect(self.reset_preferences)
        self.settings_page.custom_background_requested.connect(self.choose_background_image)
        self._sync_controls()

    def _apply_preferences(self):
        keys = ("theme", "glass", "text_style", "background", "accent", "compact_nav", "custom_background")
        QApplication.instance().setPalette(build_palette(self.preference_values["theme"]))
        QApplication.instance().setStyleSheet(build_app_qss(**{key: self.preference_values[key] for key in keys}))

    def _sync_controls(self):
        if not hasattr(self, "theme_combo"): return
        self.theme_combo.blockSignals(True); self.theme_combo.setCurrentText(str(self.preference_values["theme"]).title()); self.theme_combo.blockSignals(False)
        if hasattr(self, "settings_page"): self.settings_page.sync(self.preference_values)

    def _preference_changed(self, key, value):
        if key == "background" and value == "custom" and not self.preference_values.get("custom_background"):
            self.choose_background_image(); return
        self.preference_values[key] = value; self.settings.setValue(key, value); self.settings.sync(); self._apply_preferences()
        if key == "start_maximized":
            self.showMaximized() if value else self.showNormal()
        self._sync_controls()

    def _theme_changed(self, value): self._preference_changed("theme", value.lower())

    def choose_background_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose background image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.preference_values["custom_background"] = path; self.preference_values["background"] = "custom"
            self.settings.setValue("custom_background", path); self.settings.setValue("background", "custom"); self.settings.sync(); self._apply_preferences(); self._sync_controls()

    def reset_preferences(self):
        defaults = {"theme": "light", "glass": "light", "text_style": "Segoe UI Variable", "background": "mist", "accent": "blue", "custom_background": "", "compact_nav": False, "confirm_clear": True, "show_loss_warning": True, "open_output": False, "start_maximized": True}
        self.preference_values.update(defaults)
        for key, value in defaults.items(): self.settings.setValue(key, value)
        self.settings.sync(); self._apply_preferences(); self._sync_controls()
        self.showMaximized()

    def _navigate_by_label(self, label):
        lookup = {"Smart Converter": "smart", "Document & Data Studio": "documents", "Images": "images", "Audio": "audio", "Video": "video", "Compression Studio": "compression", "Archives": "archives", "Data & Spreadsheets": "data", "File Manager": "files", "Security & Privacy": "security", "OCR & AI Tools": "ocr", "Utilities": "utilities", "History": "history", "Favorites": "favorites", "Settings": "settings", "Home": "home"}
        self._navigate(lookup.get(label, "smart"))

    def _toggle_submenu(self, key):
        self._navigate(key)
        submenu = self.nav_submenus.get(key)
        if submenu is None:
            return
        visible = not submenu.isVisible()
        for other_key, other_menu in self.nav_submenus.items():
            other_menu.setVisible(visible if other_key == key else False)

    def _open_format_shortcut(self, key, target):
        self._navigate(key)
        page = self.pages.get(key)
        if page and hasattr(page, "set_preferred_target"):
            page.set_preferred_target(target)

    def _navigate(self, key):
        page = self.pages.get(key)
        if page is None: return
        if key not in self.nav_submenus:
            for submenu in self.nav_submenus.values(): submenu.setVisible(False)
        self.stack.setCurrentWidget(page)
        self.breadcrumb.setText(next((label.upper() for group, entries in NAV_GROUPS for icon, label, item_key in entries if item_key == key), key.upper()))
        for item_key, button in self.nav_buttons.items(): button.setChecked(item_key == key)
        if key == "home": self.home_page.refresh(self.history.load(), self.output_dir, self.recent_tools)
        if key == "history": self.pages["history"].set_history(self.history.load())
        if key == "files": self.pages["files"].set_output_dir(self.output_dir)
        if key != "settings":
            label = next((label for group, entries in NAV_GROUPS for icon, label, item_key in entries if item_key == key), key)
            if label not in self.recent_tools: self.recent_tools.insert(0, label); self.recent_tools = self.recent_tools[:6]
        self.statusBar().showMessage(f"{self.breadcrumb.text().title()} ready")

    def _start_with_files(self, paths):
        self._navigate("smart"); self.smart_page.add_files(paths)

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_dir)
        if not folder: return
        self.output_dir = folder; self.settings.setValue("output_dir", folder); self.settings.sync()
        self.output_button.setText(f"Output: {Path(folder).name}  ▾")
        for page in self.pages.values():
            if isinstance(page, ConverterWorkspace): page.set_output_dir(folder)
        self.pages["files"].set_output_dir(folder)

    def start_conversion(self, workspace):
        if self.worker and self.worker.isRunning(): return
        jobs = workspace.build_jobs(self.output_dir)
        if not jobs:
            workspace.update_jobs([])
            if getattr(workspace, "entries", []):
                QMessageBox.information(self, "Nothing to convert", "No compatible files are ready. Remove incompatible files, choose a common format, or select a different target.")
            else:
                QMessageBox.information(self, "Nothing to convert", "Add files to the workspace queue first.")
            return
        if self.preference_values.get("show_loss_warning") and any(job.quality == "Maximum" and job.category == "Document" for job in jobs):
            answer = QMessageBox.question(self, "Conversion quality", "Some document conversions may change layout between formats. Continue?", QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes: return
        unnecessary = [job.filename for job in jobs if job.detected_format.lower() in source_extensions(job.category, job.target_format)]
        if unnecessary and self.preference_values.get("show_loss_warning"):
            answer = QMessageBox.question(self, "Conversion may be unnecessary", f"{len(unnecessary)} file(s) are already in the selected target format. Continue anyway?", QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes: return
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.jobs = jobs; self.active_workspace = workspace; workspace.set_running(True)
        self.worker = ConversionWorker(jobs); self.worker.progress.connect(lambda index, status, detail: self._job_progress(workspace, index, status, detail)); self.worker.finished_all.connect(lambda: self._conversion_finished(workspace)); self.worker.start()

    def _job_progress(self, workspace, index=None, status="", detail=""): workspace.update_jobs(self.jobs)

    def _conversion_finished(self, workspace):
        workspace.update_jobs(self.jobs); workspace.set_running(False)
        for job in self.jobs:
            self.history.add({"date": datetime.now().isoformat(timespec="seconds"), "source": job.filename, "status": job.status, "detail": job.output or job.error})
        self.pages["history"].set_history(self.history.load()); self.home_page.refresh(self.history.load(), self.output_dir, self.recent_tools); self.pages["files"].refresh()
        self.statusBar().showMessage("Conversion queue finished")
        if self.preference_values.get("open_output"): self.pages["files"].open_folder()

    def cancel_conversion(self):
        if self.worker: self.worker.cancel()

    def _pdf_file(self, title="Choose a PDF"):
        files, _ = QFileDialog.getOpenFileNames(self, title, "", "PDF files (*.pdf)")
        return files

    def _pdf_output(self, stem, suffix="pdf"):
        output = Path(self.output_dir) / f"{stem}_pdfstudio.{suffix}"
        index = 2
        while output.exists():
            output = Path(self.output_dir) / f"{stem}_pdfstudio_{index}.{suffix}"; index += 1
        return str(output)

    def run_pdf_action(self, page, action):
        engine = PdfEngine(); params = page.pdf_parameters(); output_dir = Path(self.output_dir); output_dir.mkdir(parents=True, exist_ok=True)
        try:
            if action == "images_to_pdf":
                files, _ = QFileDialog.getOpenFileNames(self, "Choose images", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
                if not files: return
                output = engine.images_to_pdf(files, self._pdf_output("images")); detail = output
            elif action == "merge":
                files = self._pdf_file("Choose PDFs to merge")
                if not files: return
                output = engine.merge(files, self._pdf_output("merged")); detail = output
            else:
                files = self._pdf_file()
                if not files: return
                source = files[0]; stem = Path(source).stem
                if action == "to_images":
                    outputs = engine.to_images(source, output_dir); detail = f"Created {len(outputs)} image(s)"
                elif action == "split":
                    outputs = engine.split(source, output_dir); detail = f"Created {len(outputs)} page PDF(s)"
                elif action == "extract":
                    detail = engine.extract_pages(source, params["pages"], self._pdf_output(stem, "pdf"))
                elif action == "reorder":
                    detail = engine.reorder_pages(source, params["pages"], self._pdf_output(stem, "pdf"))
                elif action == "delete":
                    detail = engine.delete_pages(source, params["pages"], self._pdf_output(stem, "pdf"))
                elif action == "rotate":
                    detail = engine.rotate(source, self._pdf_output(stem, "pdf"))
                elif action == "page_numbers":
                    detail = engine.add_page_numbers(source, self._pdf_output(stem, "pdf"))
                elif action == "watermark":
                    detail = engine.watermark(source, self._pdf_output(stem, "pdf"), params["watermark"])
                elif action == "protect":
                    if not params["password"]: raise ValueError("Enter a password before protecting the PDF.")
                    detail = engine.protect(source, self._pdf_output(stem, "pdf"), params["password"])
                elif action == "remove_password":
                    if not params["password"]: raise ValueError("Enter the authorized PDF password first.")
                    detail = engine.remove_password(source, self._pdf_output(stem, "pdf"), params["password"])
                elif action == "metadata":
                    detail = engine.edit_metadata(source, self._pdf_output(stem, "pdf"), params["title"], params["author"])
                elif action == "optimize":
                    detail = engine.optimize(source, self._pdf_output(stem, "pdf"))
                elif action == "quality":
                    report = engine.inspect_layout(source)
                    warning_text = "\n".join(report["warnings"]) or "No obvious layout warnings detected."
                    QMessageBox.information(self, "PDF quality inspection", f"Pages: {report['pages']}\nText blocks: {report['text_blocks']}\nFonts: {len(report['fonts'])}\n\n{warning_text}")
                    return
                else:
                    return
            self.statusBar().showMessage(f"PDF operation complete: {detail}")
            self.pages["files"].refresh()
            self.history.add({"date": datetime.now().isoformat(timespec="seconds"), "source": Path(detail).name if isinstance(detail, str) and os.path.exists(detail) else action, "status": "Completed", "detail": str(detail)})
        except Exception as exc:
            QMessageBox.warning(self, "PDF operation failed", str(exc))

    def run_archive_action(self, page, action):
        if action != "browse": return
        files, _ = QFileDialog.getOpenFileNames(self, "Choose archive", "", "Archives (*.zip *.7z *.tar *.gz *.bz2 *.xz *.tar.gz *.tar.bz2 *.tar.xz)")
        if not files: return
        try:
            entries = ArchiveEngine().list_entries(files[0])
            page.show_entries(entries)
            if not any(item["path"] == files[0] for item in page.entries): page.add_files(files)
            lines = [f"{item['name']}  •  {item.get('size', 0) or 0} bytes" for item in entries[:80]]
            if len(entries) > 80: lines.append(f"… and {len(entries) - 80} more")
            QMessageBox.information(self, "Archive contents", "\n".join(lines) or "The archive is empty.")
        except Exception as exc:
            QMessageBox.warning(self, "Archive browse failed", str(exc))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths: self._start_with_files(paths)
