import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_version() -> str:
    version_file = BASE_DIR / "VERSION"
    if version_file.exists():
        v = version_file.read_text().strip()
        if v:
            return v
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            cwd=BASE_DIR,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "dev"


def site_subheader_callback(request):
    return f"Shopware \u2194 Microtech \u00b7 {get_version()}"
