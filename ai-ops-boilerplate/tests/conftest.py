import sys
from pathlib import Path

# Put the repo root on sys.path so `core` and `automation` import the same way
# they do when the tool is run for real.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
