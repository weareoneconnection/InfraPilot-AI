import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))
os.environ.setdefault("INFRAPILOT_DB", tempfile.mktemp(suffix=".db"))
for key in ("INFRAPILOT_MODEL_BASE_URL", "INFRAPILOT_MODEL"):
    os.environ.pop(key, None)
