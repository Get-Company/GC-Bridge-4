from __future__ import annotations

import json
import os

from core.management.base import MonitoredBaseCommand

from core.services.nfon_client import NfonClient


CHECK_ENDPOINTS = [
    "/api/version",
    "/api/customers/{customer_id}/basic-data",
    "/api/customers/{customer_id}/targets/time-control-services",
]


class Command(MonitoredBaseCommand):
    help = "Testet die NFON Service Portal API mit HMAC-SHA1-Auth."

    def add_arguments(self, parser):
        parser.add_argument("--endpoint", default=None, help="Einzelnen Pfad testen (z.B. /api/version)")
        parser.add_argument("--full", action="store_true", help="Vollständige Response-Bodies ausgeben")

    def handle(self, *args, **options):
        api_key_id = os.environ.get("NFON_API_KEY_ID", "")
        api_key_secret = os.environ.get("NFON_API_KEY_SECRET", "")
        customer_id = os.environ.get("NFON_CUSTOMER_ID", "")

        missing = [n for n, v in [("NFON_API_KEY_ID", api_key_id), ("NFON_API_KEY_SECRET", api_key_secret), ("NFON_CUSTOMER_ID", customer_id)] if not v]
        if missing:
            for m in missing:
                self.stderr.write(self.style.ERROR(f"{m} fehlt in der .env"))
            return

        client = NfonClient(api_key_id, api_key_secret, customer_id)

        self.stdout.write(self.style.HTTP_INFO("\n=== NFON Service Portal API Test ==="))
        self.stdout.write(f"Customer : {customer_id}")
        self.stdout.write(f"Key ID   : {api_key_id[:8]}***")
        self.stdout.write(f"Base URL : https://portal-api.nfon.net:8090\n")

        endpoints = [options["endpoint"]] if options["endpoint"] else [
            p.format(customer_id=customer_id) for p in CHECK_ENDPOINTS
        ]

        results = []
        for path in endpoints:
            try:
                r = client.get(path)
                status = r.status_code
                try:
                    body = json.dumps(r.json(), ensure_ascii=False, indent=2)
                except Exception:
                    body = r.text

                if not options["full"] and len(body) > 400:
                    body = body[:400] + "\n  ... (--full für alles)"

                results.append((status, path))

                if status < 300:
                    self.stdout.write(self.style.SUCCESS(f"[{status}] {path}"))
                elif status == 401:
                    self.stdout.write(self.style.ERROR(f"[{status}] {path}  ← Auth-Fehler"))
                elif status == 403:
                    self.stdout.write(self.style.ERROR(f"[{status}] {path}  ← Keine Berechtigung"))
                elif status == 404:
                    self.stdout.write(f"[{status}] {path}")
                else:
                    self.stdout.write(self.style.WARNING(f"[{status}] {path}"))

                if status != 404 and (options["full"] or status not in (404,)):
                    self.stdout.write(f"  {body}\n")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[ERR] {path}: {e}"))
                results.append((0, path))

        ok = [p for s, p in results if s < 300]
        err = [p for s, p in results if s >= 400]

        self.stdout.write(self.style.HTTP_INFO("\n=== Zusammenfassung ==="))
        self.stdout.write(self.style.SUCCESS(f"  OK (2xx)   : {len(ok)}"))
        self.stdout.write(self.style.ERROR(f"  Fehler     : {len(err)}"))
