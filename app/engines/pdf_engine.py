from pathlib import Path

from pypdf import PdfReader, PdfWriter


def parse_pages(value, total=None):
    pages = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(item.strip()) for item in part.split("-", 1))
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    if total is not None:
        pages = [page for page in pages if 1 <= page <= total]
    return list(dict.fromkeys(pages))


class PdfEngine:
    def merge(self, files, output):
        writer = PdfWriter()
        for file in files:
            reader = PdfReader(file)
            for page in reader.pages:
                writer.add_page(page)
        self._write(writer, output)
        return output

    def split(self, source, output_dir):
        reader = PdfReader(source); outputs = []; stem = Path(source).stem
        for index, page in enumerate(reader.pages, 1):
            writer = PdfWriter(); writer.add_page(page)
            out = Path(output_dir) / f"{stem}_page_{index}.pdf"; self._write(writer, out); outputs.append(str(out))
        return outputs

    def extract_pages(self, source, pages, output):
        reader = PdfReader(source); writer = PdfWriter()
        for page in parse_pages(pages, len(reader.pages)):
            writer.add_page(reader.pages[page - 1])
        self._write(writer, output); return output

    def reorder_pages(self, source, pages, output):
        reader = PdfReader(source); writer = PdfWriter()
        order = parse_pages(pages, len(reader.pages)) or list(range(1, len(reader.pages) + 1))
        for page in order: writer.add_page(reader.pages[page - 1])
        self._write(writer, output); return output

    def delete_pages(self, source, pages, output):
        reader = PdfReader(source); writer = PdfWriter(); remove = set(parse_pages(pages, len(reader.pages)))
        for index, page in enumerate(reader.pages, 1):
            if index not in remove: writer.add_page(page)
        self._write(writer, output); return output

    def rotate(self, source, output, degrees=90):
        reader, writer = PdfReader(source), PdfWriter()
        for page in reader.pages:
            page.rotate(degrees); writer.add_page(page)
        self._write(writer, output); return output

    def add_page_numbers(self, source, output):
        import fitz
        document = fitz.open(source)
        for index, page in enumerate(document, 1):
            rect = page.rect; page.insert_text((rect.width - 55, rect.height - 22), str(index), fontsize=9, color=(0.25, 0.25, 0.25))
        document.save(output); document.close(); return output

    def watermark(self, source, output, text):
        import fitz
        document = fitz.open(source)
        for page in document:
            rect = page.rect
            page.insert_text((rect.width * 0.25, rect.height * 0.55), text or "Watermark", fontsize=28, rotate=0, color=(0.45, 0.45, 0.45), overlay=True)
        document.save(output); document.close(); return output

    def protect(self, source, output, password):
        reader = PdfReader(source); writer = PdfWriter()
        for page in reader.pages: writer.add_page(page)
        writer.encrypt(password); self._write(writer, output); return output

    def remove_password(self, source, output, password):
        reader = PdfReader(source, password=password); writer = PdfWriter()
        for page in reader.pages: writer.add_page(page)
        self._write(writer, output); return output

    def edit_metadata(self, source, output, title="", author=""):
        reader = PdfReader(source); writer = PdfWriter()
        for page in reader.pages: writer.add_page(page)
        metadata = dict(reader.metadata or {})
        if title: metadata["/Title"] = title
        if author: metadata["/Author"] = author
        writer.add_metadata(metadata); self._write(writer, output); return output

    def optimize(self, source, output):
        import fitz
        document = fitz.open(source); document.save(output, garbage=4, deflate=True, clean=True); document.close(); return output

    def to_images(self, source, output_dir, dpi=150):
        import fitz
        output_dir = Path(output_dir); document = fitz.open(source); outputs = []
        scale = dpi / 72
        for index, page in enumerate(document, 1):
            output = output_dir / f"{Path(source).stem}_page_{index}.png"
            page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(output); outputs.append(str(output))
        document.close(); return outputs

    def images_to_pdf(self, files, output):
        import fitz
        document = fitz.open()
        for file in files:
            image = fitz.Pixmap(file)
            page = document.new_page(width=image.width, height=image.height)
            page.insert_image(page.rect, filename=file)
        document.save(output); document.close(); return output

    def inspect_layout(self, source, output=None):
        import fitz
        report = {"pages": 0, "warnings": [], "fonts": [], "text_blocks": 0}
        source_doc = fitz.open(source); report["pages"] = source_doc.page_count
        for page in source_doc:
            page_rect = page.rect; blocks = page.get_text("dict").get("blocks", [])
            seen = []
            for block in blocks:
                if block.get("type") != 0: continue
                report["text_blocks"] += 1; rect = fitz.Rect(block["bbox"])
                if not page_rect.contains(rect): report["warnings"].append("Text extends outside a page boundary")
                for old in seen:
                    if rect.intersects(old) and rect.get_area() > 0: report["warnings"].append("Overlapping text regions detected")
                seen.append(rect)
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("font") and span["font"] not in report["fonts"]: report["fonts"].append(span["font"])
        source_doc.close()
        if output:
            output_doc = fitz.open(output)
            if output_doc.page_count != report["pages"]: report["warnings"].append("Page count changed")
            output_text = "".join(page.get_text() for page in output_doc)
            source_doc = fitz.open(source); source_text = "".join(page.get_text() for page in source_doc)
            if source_text and len(output_text) < len(source_text) * 0.75: report["warnings"].append("Significant text loss detected")
            output_doc.close(); source_doc.close()
        report["warnings"] = list(dict.fromkeys(report["warnings"]))
        return report

    @staticmethod
    def _write(writer, output):
        with open(output, "wb") as file:
            writer.write(file)
