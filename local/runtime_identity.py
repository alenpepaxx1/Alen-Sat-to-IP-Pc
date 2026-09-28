# Copyright © 2026 Alen Pepa.
"""Shared identity prevents the launcher from reusing an outdated installation."""
from hashlib import sha256
from pathlib import Path

VERSION = '0.8.3'
ROOT = Path(__file__).resolve().parent.parent
INSTALLATION_ID = sha256(str(ROOT).encode('utf-8')).hexdigest()[:24]
