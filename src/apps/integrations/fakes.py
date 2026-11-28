import json
from pathlib import Path


class FakeHrisClient:
    """Đọc dữ liệu HRIS giả từ file JSON (vd. sample-data/hris_fake.json)."""

    def __init__(self, path):
        self._data = json.loads(Path(path).read_text(encoding="utf-8"))

    def fetch_org_units(self) -> list[dict]:
        return list(self._data.get("org_units", []))

    def fetch_employees(self) -> list[dict]:
        return list(self._data.get("employees", []))
