from __future__ import annotations

import json
from pathlib import Path

from idp.api.app import app


ROOT = Path(__file__).resolve().parents[1]
output = ROOT / "openapi.json"
output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True), encoding="utf-8")
print(output)
