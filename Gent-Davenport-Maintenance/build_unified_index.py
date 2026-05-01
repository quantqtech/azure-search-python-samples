"""
CLI shim — runs the unified index rebuild from your local shell.

The real logic lives in func-api/rebuild_unified.py so the Function App's
timer trigger and "Rebuild Now" endpoint can import it directly. This file
exists so your existing workflow (`python build_unified_index.py`) keeps
working from the repo root.

Run: python build_unified_index.py

Local prereqs: pip install azure-identity azure-data-tables azure-storage-blob pyyaml
"""

import os
import sys

# Make func-api/ importable from the repo root
_FUNC_API_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "func-api")
if _FUNC_API_DIR not in sys.path:
    sys.path.insert(0, _FUNC_API_DIR)

from rebuild_unified import rebuild_unified_index  # noqa: E402


if __name__ == "__main__":
    rebuild_unified_index(verbose=True)
