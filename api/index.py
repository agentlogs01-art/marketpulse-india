import os
import sys

# Add root folder to sys.path so marketpulse modules import cleanly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import your Flask app instance from marketpulse/api/app.py
from marketpulse.api.app import app
