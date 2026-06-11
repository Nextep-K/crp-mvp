import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for rel in ["engines/phase_b_engine", "engines", "storage", "workers", "."]:
    p = str(ROOT / rel)
    if p not in sys.path:
        sys.path.insert(0, p)
