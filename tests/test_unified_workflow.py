import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.formats import capabilities_for, category_for
from app.engines.registry import EngineRegistry


class UnifiedWorkflowTests(unittest.TestCase):
    def test_common_target_is_intersection_of_real_capabilities(self):
        image_targets = set(capabilities_for("photo.png"))
        document_targets = set(capabilities_for("report.docx"))
        self.assertEqual(image_targets & document_targets, {"PDF"})
        self.assertEqual(category_for("report.pdf"), "Document")

    def test_structured_json_routes_to_native_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "records.json"
            source.write_text(json.dumps({"name": "Ada", "active": True}), encoding="utf-8")
            job = SimpleNamespace(
                source=str(source), target_format="CSV", output_dir=folder,
                category="Document", operation="convert",
                conversion_mode="Smart Hybrid Conversion", options={},
            )
            output = Path(EngineRegistry().convert(job))
            self.assertEqual(output.suffix, ".csv")
            self.assertIn("name", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
