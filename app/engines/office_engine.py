import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.core.engines import find_libreoffice
from app.core.processing import unique_path


# Explicit filters keep LibreOffice on its native export paths instead of
# relying on whichever filter alias a particular installed version prefers.
EXPORT_FILTERS = {
    "PDF": "pdf",
    "DOCX": "docx:Office Open XML Text",
    "DOC": "doc:MS Word 97",
    "ODT": "odt:writer8",
    "RTF": "rtf:Rich Text Format",
    "TXT": "txt:Text",
    "HTML": "html:HTML (StarWriter)",
    "XHTML": "xhtml:HTML (StarWriter)",
    "EPUB": "epub:EPUB",
    "XLSX": "xlsx:Calc MS Excel 2007 XML",
    "XLS": "xls:MS Excel 97",
    "XLSM": "xlsm:Calc MS Excel 2007 VBA XML",
    "ODS": "ods:calc8",
    "FODS": "fods:OpenDocument Spreadsheet Flat XML",
    "CSV": "csv:Text - txt - csv (StarCalc)",
    "TSV": "csv:Text - txt - csv (StarCalc)",
    "PPTX": "pptx:Impress MS PowerPoint 2007 XML",
    "PPT": "ppt:MS PowerPoint 97",
    "ODP": "odp:impress8",
    "OTP": "otp:impress8",
    "POTX": "potx:Impress MS PowerPoint 2007 XML",
    "PPSX": "ppsx:Impress MS PowerPoint 2007 XML",
}

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".odp", ".otp", ".potx", ".ppsx"}
WORD_TARGETS = {"DOCX", "DOC", "ODT", "RTF"}
OFFICE_SOURCES = {
    ".doc", ".docx", ".odt", ".rtf", ".txt", ".html", ".htm", ".xhtml", ".epub",
    ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".fods", ".csv", ".tsv",
    ".ppt", ".pptx", ".odp", ".otp", ".potx", ".ppsx", ".pdf",
}
OFFICE_TARGETS = set(EXPORT_FILTERS) | {"TSV"}


class OfficeEngine:
    def can_handle(self, category): return category == "Document"

    def supports(self, job):
        source = Path(job.source).suffix.lower()
        target = job.target_format.upper()
        if source not in OFFICE_SOURCES or target not in OFFICE_TARGETS:
            return False
        if source == ".pdf" and target in {"TXT", "HTML", "XHTML", "MARKDOWN"}:
            return False
        if target in {"JSON", "XML", "YAML", "TOML", "MARKDOWN"}:
            return False
        return bool(find_libreoffice())

    def convert_job(self, job, cancel=None, progress=None):
        if job.operation == "compress":
            return self.compress(job, cancel, progress)
        return self.convert(job.source, job.target_format, job.output_dir, job.conversion_mode)

    def compress(self, job, cancel=None, progress=None):
        source = Path(job.source); output = unique_path(Path(job.output_dir) / f"{source.stem}_compressed{source.suffix}")
        if source.suffix.lower() == ".pdf":
            from app.engines.pdf_engine import PdfEngine
            return PdfEngine().optimize(source, output)
        if source.suffix.lower() not in {".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp"}:
            return self.convert(source, job.target_format, job.output_dir, job.conversion_mode)
        with zipfile.ZipFile(source, "r") as incoming, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as outgoing:
            entries = incoming.infolist()
            for index, info in enumerate(entries):
                if cancel: cancel()
                outgoing.writestr(info.filename, incoming.read(info.filename))
                if progress: progress(int((index + 1) / max(1, len(entries)) * 100))
        return str(output)

    def convert(self, source, target_format, output_dir, conversion_mode="Smart Hybrid Conversion"):
        office = find_libreoffice()
        if not office:
            raise RuntimeError("LibreOffice was not found. Install LibreOffice to convert Office documents.")
        src = Path(source)
        target = target_format.upper()
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Impress cannot export directly to Writer formats. Rendering each
        # slide first preserves its complete visual design in a Word document.
        if src.suffix.lower() in PRESENTATION_EXTENSIONS and target in WORD_TARGETS:
            return self._presentation_to_document(office, src, target, Path(output_dir), conversion_mode)
        if src.suffix.lower() == ".pdf" and target in WORD_TARGETS:
            return self._pdf_to_document(office, src, target, Path(output_dir), conversion_mode)

        expected = self._run_libreoffice(office, src, Path(output_dir), target)
        return str(self._rename_output(expected))

    def _run_libreoffice(self, office, source, output_dir, target_format):
        source = Path(source)
        output_dir = Path(output_dir)
        ext = target_format.lower()
        export_filter = EXPORT_FILTERS.get(target_format.upper(), ext)
        if target_format.upper() in {"HTML", "XHTML"} and source.suffix.lower() in {".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".fods", ".csv", ".tsv"}:
            export_filter = "html:HTML (StarCalc)"
        profile = (output_dir / ".lo_profile").resolve()
        expected = output_dir / f"{source.stem}.{ext}"
        if expected.resolve() == source.resolve():
            expected = output_dir / f"{source.stem}_export.{ext}"
        existing_outputs = set(output_dir.glob(f"{source.stem}.*"))
        if expected.exists():
            expected.unlink()

        filters = [export_filter] if export_filter == ext else [export_filter, ext]
        result = None
        for selected_filter in filters:
            command = [
                office,
                f"-env:UserInstallation=file:///{profile.as_posix()}",
                "--headless",
                "--convert-to",
                selected_filter,
                "--outdir",
                str(output_dir),
                str(source),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0 and expected.exists():
                return expected
            if result.returncode == 0:
                # Some LibreOffice filters use their native extension even
                # when an alias was requested (for example template/output
                # filters). Normalize that result to the user's target.
                candidates = [
                    item for item in output_dir.glob(f"{source.stem}.*")
                    if item not in existing_outputs and item != source and item != expected and item.is_file()
                ]
                if candidates:
                    candidate = max(candidates, key=lambda item: item.stat().st_mtime)
                    if expected.exists(): expected.unlink()
                    candidate.rename(expected)
                    return expected

        detail = ((result.stderr or result.stdout) if result else "")
        raise RuntimeError((detail or "LibreOffice conversion failed")[-2500:])

    def _presentation_to_document(self, office, source, target, output_dir, conversion_mode):
        try:
            import fitz
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.shared import Inches, Pt
        except ImportError as exc:
            raise RuntimeError("PPT-to-Word conversion requires PyMuPDF and python-docx.") from exc

        with tempfile.TemporaryDirectory(prefix=".presentation_", dir=output_dir) as temp:
            temp_dir = Path(temp)
            pdf = self._run_libreoffice(office, source, temp_dir, "PDF")
            pdf_document = fitz.open(pdf)
            if not pdf_document.page_count:
                pdf_document.close()
                raise RuntimeError("The presentation did not contain any slides.")

            document = Document()
            editable_shapes = None
            if conversion_mode in {"Editable Conversion", "Smart Hybrid Conversion"}:
                try:
                    from pptx import Presentation
                    editable_shapes = Presentation(source).slides
                except ImportError:
                    editable_shapes = None
            first_page = pdf_document[0].rect
            section = document.sections[0]
            section.page_width = Inches(first_page.width / 72)
            section.page_height = Inches(first_page.height / 72)
            section.top_margin = Inches(0)
            section.bottom_margin = Inches(0)
            section.left_margin = Inches(0)
            section.right_margin = Inches(0)

            for index, page in enumerate(pdf_document):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                slide_image = temp_dir / f"slide_{index + 1}.png"
                pixmap.save(slide_image)

                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.add_run().add_picture(str(slide_image), width=Inches(page.rect.width / 72))
                if conversion_mode in {"Editable Conversion", "Smart Hybrid Conversion"} and editable_shapes is not None and index < len(editable_shapes):
                    text_parts = []
                    for shape in editable_shapes[index].shapes:
                        if getattr(shape, "has_text_frame", False) and shape.text.strip():
                            text_parts.append(shape.text.strip())
                    if text_parts:
                        note = document.add_paragraph()
                        note.paragraph_format.space_before = Pt(4)
                        note.add_run("Editable slide text\n").bold = True
                        note.add_run("\n".join(text_parts))
                if conversion_mode == "Editable Conversion" and editable_shapes is not None and index < len(editable_shapes):
                    # Editable mode adds extracted text and embedded images after
                    # a slide heading; the native slide image remains available
                    # as a visual reference when exact positioning is impossible.
                    for shape in editable_shapes[index].shapes:
                        if getattr(shape, "shape_type", None) == 13 and getattr(shape, "image", None):
                            image_file = temp_dir / f"slide_{index + 1}_{shape.shape_id}.png"
                            image_file.write_bytes(shape.image.blob)
                            document.add_picture(str(image_file), width=Inches(min(5.5, shape.width / 914400)))
                if index < pdf_document.page_count - 1:
                    document.add_page_break()

            pdf_document.close()
            document.core_properties.title = f"{source.stem} converted from presentation"
            intermediate = temp_dir / f"{source.stem}_snapshot.docx"
            document.save(intermediate)

            final = unique_path(output_dir / f"{source.stem}_converted.{target.lower()}")
            if target == "DOCX":
                shutil.copy2(intermediate, final)
            else:
                converted = self._run_libreoffice(office, intermediate, temp_dir, target)
                shutil.copy2(converted, final)
            return str(final)

    def _pdf_to_document(self, office, source, target, output_dir, conversion_mode):
        """Keep PDF appearance by placing rendered pages in a document.

        Editable and hybrid modes add extracted text below each page because a
        PDF's exact positioning and a word processor's editable flow are not
        equivalent representations.
        """
        try:
            import fitz
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.shared import Inches, Pt
        except ImportError as exc:
            raise RuntimeError("PDF-to-document conversion requires PyMuPDF and python-docx.") from exc

        with tempfile.TemporaryDirectory(prefix=".pdf_document_", dir=output_dir) as temp:
            temp_dir = Path(temp)
            pdf_document = fitz.open(source)
            if not pdf_document.page_count:
                pdf_document.close()
                raise RuntimeError("The PDF did not contain any pages.")
            document = Document()
            first_page = pdf_document[0].rect
            section = document.sections[0]
            section.page_width = Inches(first_page.width / 72)
            section.page_height = Inches(first_page.height / 72)
            section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Inches(0)
            for index, page in enumerate(pdf_document):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                page_image = temp_dir / f"page_{index + 1}.png"
                pixmap.save(page_image)
                paragraph = document.add_paragraph(); paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.space_before = Pt(0); paragraph.paragraph_format.space_after = Pt(0)
                paragraph.add_run().add_picture(str(page_image), width=Inches(page.rect.width / 72))
                if conversion_mode in {"Editable Conversion", "Smart Hybrid Conversion"}:
                    text = page.get_text().strip()
                    if text:
                        note = document.add_paragraph(); note.paragraph_format.space_before = Pt(4)
                        note.add_run("Extracted page text\n").bold = True; note.add_run(text)
                if index < pdf_document.page_count - 1:
                    document.add_page_break()
            pdf_document.close()
            intermediate = temp_dir / f"{source.stem}_snapshot.docx"; document.save(intermediate)
            final = unique_path(output_dir / f"{source.stem}_converted.{target.lower()}")
            if target == "DOCX":
                shutil.copy2(intermediate, final)
            else:
                converted = self._run_libreoffice(office, intermediate, temp_dir, target)
                shutil.copy2(converted, final)
            return str(final)

    @staticmethod
    def _rename_output(output):
        renamed = unique_path(output.with_name(f"{output.stem}_converted{output.suffix}"))
        output.rename(renamed)
        return renamed
