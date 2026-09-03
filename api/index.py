"""
Vercel serverless entrypoint.

Vercel's Python runtime only auto-detects Flask apps in default paths
(app.py, api/index.py, api/app.py, …). The real app lives in the
marketpulse package, so this file is a thin shim.
"""

import os
import sys

# Repo root on sys.path so `from marketpulse...` imports work on Vercel.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from marketpulse.api.app import app  # noqa: F401 — Vercel looks for this name
