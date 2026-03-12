"""Test Django admin page with a logged-in superuser."""
import os
import sys
import traceback
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "GC_Bridge_4.settings")

import django
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
if not user:
    print("[FEHLER] Kein Superuser in der Datenbank gefunden.")
    sys.exit(1)

client = Client()
client.force_login(user)

PAGES = [
    "/admin/",
    "/admin/microtech/microtechorderrule/",
]

ok = True
for url in PAGES:
    try:
        response = client.get(url, SERVER_NAME="127.0.0.1")
        status = response.status_code
        print(f"{url} -> {status}")
        if status >= 400:
            ok = False
            content = response.content.decode("utf-8", "replace")
            # Truncate to first 3000 chars to keep output readable
            print(content[:3000])
            print()
    except Exception:
        ok = False
        print(f"{url} -> EXCEPTION:")
        traceback.print_exc()
        print()

sys.exit(0 if ok else 1)
