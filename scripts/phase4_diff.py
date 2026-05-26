import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from boexio.phase4_diff import main


if __name__ == "__main__":
    raise SystemExit(main())
