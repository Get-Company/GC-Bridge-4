import os
from pathlib import Path

from lib_shopware6_api_base import ConfShopware6ApiBase as LibConfShopware6ApiBase


def _load_env_file() -> None:
    base_dir = Path(__file__).resolve().parents[2]
    env_file = base_dir / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


_load_env_file()


def _sync_shopware_env() -> None:
    mapping = {
        "SHOPWARE_ADMIN_API_URL": "SHOPWARE6_ADMIN_API_URL",
        "SHOPWARE_CLIENT_ID": "SHOPWARE6_ID",
        "SHOPWARE_CLIENT_SECRET": "SHOPWARE6_SECRET",
        "SHOPWARE_GRANT_TYPE": "SHOPWARE6_GRANT_TYPE",
        "SHOPWARE_USERNAME": "SHOPWARE6_USER",
        "SHOPWARE_PASSWORD": "SHOPWARE6_PASSWORD",
    }
    for target, source in mapping.items():
        if not os.getenv(target) and os.getenv(source):
            os.environ[target] = os.getenv(source)


_sync_shopware_env()


ConfShopware6ApiBase = LibConfShopware6ApiBase
