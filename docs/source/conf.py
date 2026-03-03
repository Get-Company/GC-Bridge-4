from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DOCS_SOURCE_DIR = Path(__file__).resolve().parent
DOCS_DIR = DOCS_SOURCE_DIR.parent
PROJECT_ROOT = DOCS_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

project = "GC-Bridge-4"
author = "GC-Bridge Team"
release = "0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.duration",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
language = "de"

html_theme = "alabaster"
html_static_path = ["_static"]


def _generate_dynamic_reference(_app) -> None:
    script_path = DOCS_DIR / "scripts" / "generate_model_admin_inventory.py"
    subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(PROJECT_ROOT),
        check=True,
    )


def setup(app) -> None:
    app.connect("builder-inited", _generate_dynamic_reference)
