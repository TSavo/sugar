import sys
from pathlib import Path

_here = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_here / "src"))
sys.path.insert(0, str(_here.parent / "sugar-node-membrane" / "src"))
