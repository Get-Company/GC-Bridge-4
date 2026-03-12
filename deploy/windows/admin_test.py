"""Test Django admin page with a logged-in superuser."""
import os
import sys
import traceback

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

try:
    response = client.get("/admin/")
    print(f"Status: {response.status_code}")
    if response.status_code >= 400:
        print()
        content = response.content.decode("utf-8", "replace")
        # Show relevant error lines from Django debug page
        for line in content.splitlines():
            stripped = line.strip()
            if any(kw in stripped for kw in [
                "Exception", "Error", "Traceback", "raise ",
            ]):
                print(stripped)
        sys.exit(1)
except Exception:
    print("[FEHLER] Exception beim Admin-Aufruf:")
    traceback.print_exc()
    sys.exit(1)
