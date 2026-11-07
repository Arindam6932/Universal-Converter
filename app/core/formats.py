from pathlib import Path

IMAGE_FORMATS = {
    "PNG": ["png"], "JPEG": ["jpg", "jpeg"], "WEBP": ["webp"],
    "BMP": ["bmp"], "TIFF": ["tif", "tiff"], "GIF": ["gif"],
    "ICO": ["ico"], "AVIF": ["avif"], "SVG": ["svg"], "PDF": ["pdf"]
}
AUDIO_FORMATS = {
    "MP3": ["mp3"], "WAV": ["wav"], "FLAC": ["flac"], "AAC": ["aac"],
    "M4A": ["m4a"], "OGG": ["ogg"], "OPUS": ["opus"], "WMA": ["wma"],
    "AIFF": ["aiff", "aif"], "AC3": ["ac3"], "AMR": ["amr"],
    "MKA": ["mka"], "APE": ["ape"]
}
VIDEO_FORMATS = {
    "MP4": ["mp4"], "MKV": ["mkv"], "MOV": ["mov"], "AVI": ["avi"],
    "WEBM": ["webm"], "WMV": ["wmv"], "FLV": ["flv"], "MPEG": ["mpeg", "mpg"],
    "3GP": ["3gp"], "M4V": ["m4v"], "TS": ["ts"], "M2TS": ["m2ts"],
    "MTS": ["mts"], "OGV": ["ogv"], "VOB": ["vob"], "M2V": ["m2v"], "GIF": ["gif"]
}
ARCHIVE_FORMATS = {
    "ZIP": ["zip"], "7Z": ["7z"], "TAR": ["tar"], "GZ": ["gz"],
    "BZ2": ["bz2"], "XZ": ["xz"], "TAR.GZ": ["tar.gz"], "TAR.BZ2": ["tar.bz2"], "TAR.XZ": ["tar.xz"],
}
DOCUMENT_FORMATS = {
    # Word processing, web, ebook and plain-text formats.
    "PDF": ["pdf"], "DOCX": ["docx"], "DOC": ["doc"], "ODT": ["odt"],
    "RTF": ["rtf"], "TXT": ["txt"], "HTML": ["html", "htm"], "XHTML": ["xhtml"],
    "EPUB": ["epub"], "MARKDOWN": ["md", "markdown"],
    "LOG": ["log"], "INI": ["ini"], "CONF": ["conf"], "SQL": ["sql"],
    # Spreadsheets and delimited data.
    "XLSX": ["xlsx"], "XLS": ["xls"], "XLSM": ["xlsm"], "XLSB": ["xlsb"],
    "ODS": ["ods"], "FODS": ["fods"], "CSV": ["csv"], "TSV": ["tsv"],
    # Presentations.
    "PPTX": ["pptx"], "PPT": ["ppt"], "ODP": ["odp"], "OTP": ["otp"],
    "POTX": ["potx"], "PPSX": ["ppsx"],
    # Structured data.
    "JSON": ["json"], "XML": ["xml"], "YAML": ["yaml", "yml"], "TOML": ["toml"],
}

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".html", ".htm", ".xhtml", ".rtf", ".log", ".ini", ".conf", ".sql"}
STRUCTURED_EXTENSIONS = {".json", ".xml", ".yaml", ".yml", ".toml", ".csv", ".tsv"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".fods", ".csv", ".tsv"}
PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".odp", ".otp", ".potx", ".ppsx"}
WORD_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf"}
OFFICE_EXTENSIONS = WORD_EXTENSIONS | SPREADSHEET_EXTENSIONS | PRESENTATION_EXTENSIONS | {".epub", ".pdf"}


def extension_for_path(path):
    """Return a normalized extension, including the compound archive suffix."""
    path = Path(path)
    name = path.name.lower()
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.endswith(compound):
            return compound[1:]
    return path.suffix.lower().lstrip(".")

def category_for(path):
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")
    compound = path.name.lower()
    for archive_ext in ("tar.gz", "tar.bz2", "tar.xz"):
        if compound.endswith("." + archive_ext):
            return "Archive"
    for category, groups in (
        ("Document", DOCUMENT_FORMATS), ("Image", IMAGE_FORMATS), ("Audio", AUDIO_FORMATS),
        ("Video", VIDEO_FORMATS), ("Archive", ARCHIVE_FORMATS)
    ):
        if any(ext in exts for exts in groups.values()):
            return category
    return "Other"

def formats_for(category):
    mapping = {"Image": IMAGE_FORMATS, "Audio": AUDIO_FORMATS,
               "Video": VIDEO_FORMATS, "Document": DOCUMENT_FORMATS, "Archive": ARCHIVE_FORMATS}
    return list(mapping.get(category, {}).keys())

def extension_for(category, label):
    mapping = {"Image": IMAGE_FORMATS, "Audio": AUDIO_FORMATS,
               "Video": VIDEO_FORMATS, "Document": DOCUMENT_FORMATS, "Archive": ARCHIVE_FORMATS}
    values = mapping.get(category, {}).get(label, [])
    return values[0] if values else label.lower()


def source_extensions(category, label):
    """Return the source extensions represented by a public format label."""
    mapping = {"Image": IMAGE_FORMATS, "Audio": AUDIO_FORMATS, "Video": VIDEO_FORMATS,
               "Document": DOCUMENT_FORMATS, "Archive": ARCHIVE_FORMATS}
    return mapping.get(category, {}).get(label, [label.lower()])


def _office_available():
    # Keep discovery optional so format inspection remains usable when LibreOffice
    # is not installed; native text and structured conversions still work.
    try:
        from app.core.engines import find_libreoffice
        return bool(find_libreoffice())
    except Exception:
        return False


def capabilities_for(path, category=None):
    """Return genuinely routable output labels for one uploaded file.

    The result is intentionally conservative.  The UI intersects this set for
    every queued file, so a target is offered only when the complete queue can
    use the same conversion route.
    """
    path = Path(path)
    ext = path.suffix.lower()
    category = category or category_for(path)
    if category == "Image":
        # SVG is detected for a clear error message but is not advertised as a
        # route because Pillow does not rasterize it by itself.
        if ext == ".svg":
            return []
        return [label for label in formats_for("Image") if label != "SVG"]
    if category == "Audio":
        return formats_for("Audio")
    if category == "Video":
        return formats_for("Video")
    if category == "Archive":
        return formats_for("Archive")
    if category != "Document":
        return []

    native = []
    office = _office_available()
    if ext in {".json", ".xml", ".yaml", ".yml", ".toml"}:
        native = {
            ".json": ["JSON", "YAML", "XML", "CSV", "TSV"],
            ".xml": ["XML", "JSON", "YAML"],
            ".yaml": ["YAML", "JSON", "XML"],
            ".yml": ["YAML", "JSON", "XML"],
            ".toml": ["TOML", "JSON"],
        }[ext]
        return [label for label in formats_for("Document") if label in native]
    if ext in {".csv", ".tsv"}:
        native = ["JSON", "CSV", "TSV", "YAML", "XML"]
        office_targets = ["XLSX", "ODS", "PDF", "HTML"] if office else []
        return [label for label in formats_for("Document") if label in native + office_targets]
    if ext == ".pdf":
        native = ["PDF", "TXT", "HTML", "XHTML", "MARKDOWN"]
        office_targets = ["DOCX", "DOC", "ODT", "RTF"] if office else []
        return [label for label in formats_for("Document") if label in native + office_targets]
    if ext in PRESENTATION_EXTENSIONS:
        if not office:
            return []
        return [label for label in formats_for("Document") if label in {"PDF", "DOCX", "DOC", "ODT", "RTF", "TXT", "HTML", "MARKDOWN"}]
    if ext in SPREADSHEET_EXTENSIONS:
        if not office:
            return [label for label in formats_for("Document") if label in {"JSON", "CSV", "TSV"} and ext in {".csv", ".tsv"}]
        return [label for label in formats_for("Document") if label in {"PDF", "HTML", "CSV", "TSV", "XLSX", "XLS", "ODS", "FODS"}]
    if ext == ".epub":
        return [label for label in formats_for("Document") if label in {"PDF", "DOCX", "DOC", "ODT", "RTF", "TXT", "HTML", "MARKDOWN"} and (office or label in {"TXT", "HTML", "MARKDOWN"})]
    if ext in TEXT_EXTENSIONS or ext in WORD_EXTENSIONS:
        native = ["TXT", "HTML", "XHTML", "MARKDOWN", "EPUB", "DOCX", "PDF"]
        office_targets = ["DOC", "ODT", "RTF", "EPUB"] if office else []
        return [label for label in formats_for("Document") if label in native + office_targets]
    return []
