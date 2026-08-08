"""Pytest path setup so `from app...` imports work regardless of cwd."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
