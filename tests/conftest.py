import sys
from pathlib import Path

# Let tests import the `src` package from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
