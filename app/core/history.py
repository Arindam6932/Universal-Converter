import json
from pathlib import Path
from platformdirs import user_data_dir

class HistoryStore:
    def __init__(self):
        folder = Path(user_data_dir("UniversalFileConverter", "Universal Tools"))
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "history.json"

    def load(self):
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception: return []

    def add(self, record):
        data = self.load()
        data.insert(0, record)
        self.path.write_text(json.dumps(data[:500], indent=2), encoding="utf-8")
