import csv
import html
import textwrap
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from app.core.processing import unique_path


SPREADSHEET_SOURCES = {".csv", ".tsv", ".xlsx", ".xlsm"}
DELIMITED_TARGETS = {"CSV", "TSV", "XLSX", "ODS", "PDF", "HTML"}


class SpreadsheetEngine:
    """Reliable native routes for delimited data and simple table output."""

    def can_handle(self, category):
        return category == "Document"

    def supports(self, job):
        return Path(job.source).suffix.lower() in SPREADSHEET_SOURCES and job.target_format.upper() in DELIMITED_TARGETS

    def convert_job(self, job, cancel=None, progress=None):
        source = Path(job.source)
        target = job.target_format.upper()
        rows = self._read_rows(source)
        if cancel and cancel():
            from app.core.processing import JobCancelled
            raise JobCancelled("Processing cancelled")
        if target in {"CSV", "TSV"}:
            output = unique_path(Path(job.output_dir) / f"{source.stem}_converted.{target.lower()}")
            self._write_delimited(output, rows, target)
        elif target == "XLSX":
            output = self._to_xlsx(source, rows, job.output_dir)
        elif target == "ODS":
            output = self._to_ods(source, rows, job.output_dir)
        elif target == "HTML":
            output = unique_path(Path(job.output_dir) / f"{source.stem}_converted.html")
            output.write_text(self._to_html(rows), encoding="utf-8")
        elif target == "PDF":
            output = unique_path(Path(job.output_dir) / f"{source.stem}_converted.pdf")
            self._to_pdf(rows, output)
        else:
            raise RuntimeError(f"Delimited-data conversion to {target} is not supported.")
        if progress:
            progress(100)
        return str(output)

    @staticmethod
    def _read_rows(source):
        if source.suffix.lower() in {".xlsx", ".xlsm"}:
            try:
                from openpyxl import load_workbook
            except ImportError as exc:
                raise RuntimeError("Spreadsheet conversion requires openpyxl. Install it with: pip install openpyxl") from exc
            workbook = load_workbook(source, read_only=True, data_only=False)
            sheet = workbook.active
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            workbook.close()
            return [["" if value is None else value for value in row] for row in rows]
        delimiter = "\t" if source.suffix.lower() == ".tsv" else ","
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle, delimiter=delimiter))

    @staticmethod
    def _write_delimited(output, rows, target):
        output.parent.mkdir(parents=True, exist_ok=True)
        delimiter = "\t" if target == "TSV" else ","
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=delimiter)
            writer.writerows(rows)

    @staticmethod
    def _to_xlsx(source, rows, output_dir):
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise RuntimeError("CSV/TSV to XLSX conversion requires openpyxl. Install it with: pip install openpyxl") from exc
        output = unique_path(Path(output_dir) / f"{source.stem}_converted.xlsx")
        output.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook(); sheet = workbook.active; sheet.title = "Data"
        for row in rows:
            sheet.append(row)
        for column in sheet.columns:
            width = min(60, max(len(str(cell.value or "")) for cell in column) + 2)
            sheet.column_dimensions[column[0].column_letter].width = width
        workbook.save(output)
        return output

    @staticmethod
    def _to_ods(source, rows, output_dir):
        output = unique_path(Path(output_dir) / f"{source.stem}_converted.ods")
        output.parent.mkdir(parents=True, exist_ok=True)
        content_rows = []
        for row in rows:
            cells = "".join(
                '<table:table-cell office:value-type="string"><text:p>' + escape(str(value)) + "</text:p></table:table-cell>"
                for value in row
            )
            content_rows.append(f"<table:table-row>{cells}</table:table-row>")
        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:spreadsheet><table:table table:name="Data">{"".join(content_rows)}</table:table></office:spreadsheet></office:body></office:document-content>'''
        manifest = '''<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>'''
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
            archive.writestr("content.xml", content, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("META-INF/manifest.xml", manifest, compress_type=zipfile.ZIP_DEFLATED)
        return output

    @staticmethod
    def _to_html(rows):
        if not rows:
            return "<!doctype html><html><body><table></table></body></html>"
        header, body = rows[0], rows[1:]
        head_html = "".join(f"<th>{html.escape(str(cell))}</th>" for cell in header)
        body_html = "".join("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>" for row in body)
        return f"<!doctype html><html><body><table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table></body></html>"

    @staticmethod
    def _to_pdf(rows, output):
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("Spreadsheet-to-PDF conversion requires PyMuPDF. Install it with: pip install PyMuPDF") from exc
        document = fitz.open(); page = document.new_page(); y = 48
        for row in rows or [[]]:
            line = "  |  ".join(str(cell) for cell in row)
            for wrapped in textwrap.wrap(line, width=110) or [""]:
                if y > 760:
                    page = document.new_page(); y = 48
                page.insert_text((42, y), wrapped, fontsize=10)
                y += 15
        document.save(output); document.close()
