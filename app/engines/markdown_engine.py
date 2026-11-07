import html
import re
import shutil
import textwrap
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from app.core.processing import unique_path
from app.core.engines import find_libreoffice


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, data): self.parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}: self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "h1", "h2", "h3"}: self.parts.append("\n")


def plain_text(source):
    path = Path(source); suffix = path.suffix.lower()
    if suffix in {".html", ".htm", ".xhtml"}:
        parser = _TextParser(); parser.feed(path.read_text(encoding="utf-8", errors="replace")); return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
    if suffix == ".docx":
        from docx import Document
        return "\n\n".join(paragraph.text for paragraph in Document(path).paragraphs)
    if suffix == ".pdf":
        import fitz
        document = fitz.open(path); text = "\n\n".join(page.get_text() for page in document); document.close(); return text
    if suffix == ".epub":
        parts = []
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.lower().endswith((".html", ".htm", ".xhtml")):
                    parser = _TextParser(); parser.feed(archive.read(name).decode("utf-8", errors="replace")); parts.append("".join(parser.parts))
        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts)).strip()
    if suffix in {".ppt", ".pptx", ".odp", ".otp", ".potx", ".ppsx"}:
        try:
            from pptx import Presentation
            slides = Presentation(path).slides
            return "\n\n".join(
                "\n".join(shape.text.strip() for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text.strip())
                for slide in slides
            ).strip()
        except ImportError as exc:
            raise RuntimeError("Presentation text extraction requires python-pptx. Install it with: pip install python-pptx") from exc
    if suffix in {".doc", ".odt"}:
        from app.core.engines import find_libreoffice
        from app.engines.office_engine import OfficeEngine
        office = find_libreoffice()
        if not office:
            raise RuntimeError("Reading this document requires LibreOffice. Install LibreOffice to continue.")
        with tempfile.TemporaryDirectory(prefix=".text_extract_") as temp:
            converted = OfficeEngine().convert(path, "TXT", temp)
            return Path(converted).read_text(encoding="utf-8", errors="replace")
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".rtf": text = re.sub(r"\\[a-z]+\d* ?|[{}]", "", text)
    return text


def markdown_to_html(text):
    lines = []
    for line in text.splitlines():
        escaped = html.escape(line)
        if escaped.startswith("### "): lines.append(f"<h3>{escaped[4:]}</h3>")
        elif escaped.startswith("## "): lines.append(f"<h2>{escaped[3:]}</h2>")
        elif escaped.startswith("# "): lines.append(f"<h1>{escaped[2:]}</h1>")
        elif escaped.startswith("- "): lines.append(f"<li>{escaped[2:]}</li>")
        elif escaped.strip(): lines.append(f"<p>{escaped}</p>")
    return "<!doctype html><html><body>" + "\n".join(lines) + "</body></html>"


class MarkdownEngine:
    def can_handle(self, category): return category == "Document"

    def supports(self, job):
        source = Path(job.source).suffix.lower()
        target = job.target_format.upper()
        text_sources = {".md", ".markdown", ".html", ".htm", ".xhtml", ".txt", ".rtf", ".log", ".ini", ".conf", ".sql", ".epub"}
        readable_office = {".docx", ".doc", ".odt", ".pdf", ".ppt", ".pptx", ".odp", ".otp", ".potx", ".ppsx"}
        if target == "DOCX":
            return source in text_sources
        if target == "PDF":
            return source in text_sources
        if target == "EPUB":
            return source in text_sources
        if source == ".pdf":
            return target in {"MARKDOWN", "HTML", "XHTML", "TXT"}
        if source in readable_office:
            return target in {"MARKDOWN", "TXT"}
        if target in {"DOC", "ODT", "RTF"}:
            return source in text_sources and bool(find_libreoffice())
        return source in text_sources and target in {"MARKDOWN", "HTML", "XHTML", "TXT"}

    def convert_job(self, job, cancel=None, progress=None):
        source_text = plain_text(job.source)
        target = job.target_format.upper()
        output_ext = "md" if target == "MARKDOWN" else target.lower()
        output = unique_path(Path(job.output_dir) / f"{Path(job.source).stem}_converted.{output_ext}")
        output.parent.mkdir(parents=True, exist_ok=True)
        if target == "MARKDOWN":
            output.write_text(source_text, encoding="utf-8")
        elif target in {"HTML", "XHTML"}:
            output.write_text(markdown_to_html(source_text) if Path(job.source).suffix.lower() in {".md", ".markdown"} else f"<!doctype html><html><body><pre>{html.escape(source_text)}</pre></body></html>", encoding="utf-8")
        elif target == "TXT":
            output.write_text(source_text, encoding="utf-8")
        elif target == "DOCX":
            self._text_to_docx(source_text, output)
        elif target in {"DOC", "ODT", "RTF"}:
            from app.engines.office_engine import OfficeEngine
            with tempfile.TemporaryDirectory(prefix=".text_document_") as temp:
                intermediate = Path(temp) / f"{Path(job.source).stem}.docx"
                self._text_to_docx(source_text, intermediate)
                converted = Path(OfficeEngine().convert(intermediate, target, temp))
                shutil.copy2(converted, output)
        elif target == "PDF":
            self._text_to_pdf(source_text, output)
        elif target == "EPUB":
            self._text_to_epub(source_text, output, Path(job.source).stem)
        if progress:
            progress(100)
        return str(output)

    @staticmethod
    def _text_to_docx(text, output):
        from docx import Document
        document = Document()
        for line in text.splitlines() or [""]:
            document.add_paragraph(re.sub(r"^#{1,6}\s+", "", line))
        document.save(output)

    @staticmethod
    def _text_to_pdf(text, output):
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("Text-to-PDF conversion requires PyMuPDF. Install it with: pip install PyMuPDF") from exc
        document = fitz.open()
        page = None
        y = 48
        for raw_line in (text.splitlines() or [""]):
            for line in textwrap.wrap(raw_line, width=105) or [""]:
                if page is None or y > 760:
                    page = document.new_page()
                    y = 48
                page.insert_text((48, y), line, fontsize=11, color=(0.1, 0.1, 0.1))
                y += 16
        document.save(output)
        document.close()

    @staticmethod
    def _text_to_epub(text, output, title):
        chapter = "<!doctype html><html xmlns=\"http://www.w3.org/1999/xhtml\"><head><title>" + html.escape(title) + "</title></head><body>"
        chapter += "".join(f"<p>{html.escape(line)}</p>" for line in (text.splitlines() or [""])) + "</body></html>"
        package = f'''<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">urn:uuid:universal-{html.escape(title)}</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine toc="ncx"><itemref idref="chapter"/></spine></package>'''
        container = '''<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
        ncx = f'''<?xml version="1.0" encoding="UTF-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head></head><docTitle><text>{html.escape(title)}</text></docTitle><navMap><navPoint id="chapter" playOrder="1"><navLabel><text>Chapter 1</text></navLabel><content src="chapter.xhtml"/></navPoint></navMap></ncx>'''
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            archive.writestr("META-INF/container.xml", container)
            archive.writestr("OEBPS/content.opf", package)
            archive.writestr("OEBPS/chapter.xhtml", chapter)
            archive.writestr("OEBPS/toc.ncx", ncx)
