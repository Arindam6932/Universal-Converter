import csv
import json
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.processing import unique_path


STRUCTURED_SOURCES = {".json", ".xml", ".yaml", ".yml", ".toml", ".csv", ".tsv"}
STRUCTURED_TARGETS = {"JSON", "XML", "YAML", "TOML", "CSV", "TSV"}


def _xml_value(element):
    children = list(element)
    if not children:
        return element.text or ""
    value = {}
    if element.attrib:
        value["@attributes"] = dict(element.attrib)
    for child in children:
        child_value = _xml_value(child)
        if child.tag in value:
            if not isinstance(value[child.tag], list):
                value[child.tag] = [value[child.tag]]
            value[child.tag].append(child_value)
        else:
            value[child.tag] = child_value
    return value


def _xml_tree(value, tag="root"):
    element = ET.Element(str(tag))
    if isinstance(value, dict):
        attributes = value.get("@attributes", {})
        for key, item in attributes.items():
            element.set(str(key), str(item))
        for key, item in value.items():
            if key == "@attributes":
                continue
            values = item if isinstance(item, list) else [item]
            for child_value in values:
                element.append(_xml_tree(child_value, key))
    elif isinstance(value, list):
        for item in value:
            element.append(_xml_tree(item, "item"))
    elif value is not None:
        element.text = str(value)
    return element


def _yaml_load(text):
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("YAML conversion requires PyYAML. Install it with: pip install PyYAML") from exc
    return yaml.safe_load(text)


def _yaml_dump(value):
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("YAML conversion requires PyYAML. Install it with: pip install PyYAML") from exc
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


class StructuredDataEngine:
    """Native JSON/XML/YAML/TOML and delimited-data conversion routes."""

    def can_handle(self, category):
        return category == "Document"

    def supports(self, job):
        source = Path(job.source).suffix.lower()
        return source in STRUCTURED_SOURCES and job.target_format.upper() in STRUCTURED_TARGETS

    def convert_job(self, job, cancel=None, progress=None):
        source = Path(job.source)
        target = job.target_format.upper()
        value = self._load(source)
        if cancel and cancel():
            from app.core.processing import JobCancelled
            raise JobCancelled("Processing cancelled")
        output_ext = "yaml" if target == "YAML" else "tsv" if target == "TSV" else target.lower()
        output = unique_path(Path(job.output_dir) / f"{source.stem}_converted.{output_ext}")
        output.parent.mkdir(parents=True, exist_ok=True)
        self._write(output, target, value)
        if progress:
            progress(100)
        return str(output)

    def _load(self, source):
        suffix = source.suffix.lower()
        if suffix == ".json":
            return json.loads(source.read_text(encoding="utf-8"))
        if suffix == ".xml":
            root = ET.fromstring(source.read_text(encoding="utf-8"))
            return {root.tag: _xml_value(root)}
        if suffix in {".yaml", ".yml"}:
            return _yaml_load(source.read_text(encoding="utf-8"))
        if suffix == ".toml":
            with source.open("rb") as handle:
                return tomllib.load(handle)
        delimiter = "\t" if suffix == ".tsv" else ","
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=delimiter))

    def _write(self, output, target, value):
        if target == "JSON":
            output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return
        if target == "YAML":
            output.write_text(_yaml_dump(value), encoding="utf-8")
            return
        if target == "XML":
            if isinstance(value, dict) and len(value) == 1:
                root_tag, root_value = next(iter(value.items()))
                root = _xml_tree(root_value, root_tag)
            else:
                root = _xml_tree(value)
            ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
            return
        if target == "TOML":
            raise RuntimeError("TOML output is not advertised for this source unless a TOML writer is available.")
        rows = value if isinstance(value, list) else [value]
        if not rows:
            output.write_text("", encoding="utf-8")
            return
        if not all(isinstance(row, dict) for row in rows):
            rows = [{"value": row} for row in rows]
        keys = list(dict.fromkeys(key for row in rows for key in row))
        delimiter = "\t" if target == "TSV" else ","
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys, delimiter=delimiter)
            writer.writeheader()
            writer.writerows({key: self._cell(row.get(key, "")) for key in keys} for row in rows)

    @staticmethod
    def _cell(value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value
