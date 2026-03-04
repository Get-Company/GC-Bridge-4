from __future__ import annotations

import os
import socket
import threading
from time import sleep
from typing import Any
from pathlib import Path

_COM_CONNECT_TIMEOUT_SECONDS = 60

from django.utils import timezone
from loguru import logger

from core.services import BaseService
from customer.models import Customer
from customer.services import CustomerSyncService, CustomerUpsertMicrotechService
from microtech.management.commands.microtech_artikel_lookup import Command as ArticleLookupCommand
from microtech.management.commands.microtech_sync_products import Command as SyncProductsCommand
from microtech.models import MicrotechJob
from microtech.services.connection import MicrotechConnectionService
from microtech.services.expired_specials import MicrotechExpiredSpecialSyncService
from microtech.services.queue import MicrotechQueueService
from orders.models import Order
from orders.services import OrderUpsertMicrotechService


class MicrotechWorkerService(BaseService):
    def __init__(self) -> None:
        self.queue = MicrotechQueueService()
        self.connection_service = MicrotechConnectionService()
        self.worker_id = f"{socket.gethostname()}:{self._pid_str()}"
        self._stop_requested = False

    @staticmethod
    def _pid_str() -> str:
        import os

        return str(os.getpid())

    def stop(self) -> None:
        self._stop_requested = True

    def _start_connect_watchdog(self) -> None:
        """Daemon thread: force-kill the process if connect() never returns.

        BpNT.Application can hang indefinitely when called from Session 0
        (SYSTEM account) because it tries to display a GUI dialog that has
        no desktop to render on.  Without this watchdog the worker occupies
        a runtime slot forever while no jobs are processed.
        """
        def _watchdog() -> None:
            sleep(_COM_CONNECT_TIMEOUT_SECONDS)
            logger.error(
                "Microtech COM connect() did not complete within {}s. "
                "Likely causes:\n"
                "  1. Scheduled task runs as SYSTEM (Session 0 isolation) — "
                "change /RU to a normal user account that has desktop access.\n"
                "  2. Wrong mandant/credentials in MicrotechSettings.\n"
                "Forcing process exit so the worker does not occupy a runtime slot.",
                _COM_CONNECT_TIMEOUT_SECONDS,
            )
            os._exit(1)

        t = threading.Thread(target=_watchdog, daemon=True, name="com-connect-watchdog")
        t.start()

    def run_forever(
        self,
        *,
        idle_sleep_seconds: float = 2.0,
        runtime_handle=None,
    ) -> None:
        logger.info("Starting Microtech worker loop as {}", self.worker_id)
        logger.info("Connecting to Microtech ERP (timeout {}s)...", _COM_CONNECT_TIMEOUT_SECONDS)
        self._start_connect_watchdog()
        try:
            self.connection_service.connect()
            logger.info("Microtech ERP connected. Entering job loop.")
            idle_ticks = 0
            while not self._stop_requested:
                job = self.queue.claim_next_job(worker_id=self.worker_id)
                if not job:
                    idle_ticks += 1
                    if idle_ticks == 1 or idle_ticks % 30 == 0:
                        # Log every 60 s (30 ticks × 2 s) so log isn't flooded
                        logger.debug("Worker idle (tick {}), queue empty or run_after in future.", idle_ticks)
                    if runtime_handle:
                        runtime_handle.update(stage="idle", queue=self.queue.summarize())
                    sleep(max(0.2, idle_sleep_seconds))
                    continue
                idle_ticks = 0

                if runtime_handle:
                    runtime_handle.update(
                        stage="processing",
                        current_job_id=job.id,
                        current_job_type=job.job_type,
                        attempt=job.attempt,
                    )
                self._process_job(job)
        finally:
            self.connection_service.close()
            logger.info("Microtech worker loop stopped.")

    def _process_job(self, job: MicrotechJob) -> None:
        try:
            erp = self.connection_service.connect()
            result = self._dispatch_job(job=job, erp=erp)
            self.queue.mark_succeeded(job, result=result)
            logger.success("MicrotechJob #{} ({}) succeeded.", job.id, job.job_type)
        except Exception as exc:
            logger.exception("MicrotechJob #{} ({}) failed: {}", job.id, job.job_type, exc)
            self.queue.mark_failed(job, error=str(exc))
            # Be conservative: reopen COM connection after a failed job.
            self.connection_service.close()
            sleep(0.2)
            try:
                self.connection_service.connect()
            except Exception:
                logger.error("Reconnect to Microtech ERP failed after job error; worker will exit.")
                raise

    def _dispatch_job(self, *, job: MicrotechJob, erp: Any) -> dict[str, Any]:
        payload = job.payload or {}
        if job.job_type == MicrotechJob.JobType.SYNC_PRODUCTS:
            return SyncProductsCommand().run_direct(
                erp=erp,
                erp_nrs=[str(item).strip() for item in payload.get("erp_nrs", []) if str(item).strip()],
                sync_all=bool(payload.get("all")),
                include_inactive=bool(payload.get("include_inactive")),
                limit=payload.get("limit"),
                preserve_is_active=bool(payload.get("preserve_is_active")),
            )

        if job.job_type == MicrotechJob.JobType.LOOKUP_ARTICLE:
            artikel_nr = str(payload.get("artikel_nr") or "").strip()
            if not artikel_nr:
                raise ValueError("artikel_nr is required for lookup_article jobs.")
            return ArticleLookupCommand.lookup_with_erp(artikel_nr=artikel_nr, erp=erp)

        if job.job_type == MicrotechJob.JobType.SYNC_CUSTOMER:
            erp_nr = str(payload.get("erp_nr") or "").strip()
            if not erp_nr:
                raise ValueError("erp_nr is required for sync_customer jobs.")
            customer = CustomerSyncService().sync_from_microtech(erp_nr=erp_nr, erp=erp)
            return {
                "customer_id": customer.id,
                "erp_nr": customer.erp_nr,
                "name": customer.name,
                "email": customer.email,
                "addresses_count": customer.addresses.count(),
            }

        if job.job_type == MicrotechJob.JobType.UPSERT_CUSTOMER:
            customer_id = int(payload.get("customer_id") or 0)
            if customer_id <= 0:
                raise ValueError("customer_id is required for upsert_customer jobs.")
            customer = Customer.objects.filter(pk=customer_id).first()
            if not customer:
                raise ValueError(f"Customer #{customer_id} not found.")
            result = CustomerUpsertMicrotechService().upsert_customer(customer, erp=erp)
            return {
                "customer_id": customer.id,
                "erp_nr": result.erp_nr,
                "shipping_ans_nr": result.shipping_ans_nr,
                "billing_ans_nr": result.billing_ans_nr,
                "is_new_customer": result.is_new_customer,
                "shopware_updated": result.shopware_updated,
            }

        if job.job_type == MicrotechJob.JobType.UPSERT_ORDER:
            order_id = int(payload.get("order_id") or 0)
            if order_id <= 0:
                raise ValueError("order_id is required for upsert_order jobs.")
            order = Order.objects.filter(pk=order_id).first()
            if not order:
                raise ValueError(f"Order #{order_id} not found.")
            log_file = str(payload.get("log_file") or "").strip()
            sink_id = None
            if log_file:
                path = Path(log_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                sink_id = logger.add(
                    str(path),
                    level="DEBUG",
                    enqueue=False,
                    backtrace=True,
                    diagnose=True,
                    rotation="10 MB",
                    retention="14 days",
                    encoding="utf-8",
                )
                logger.info("Starting worker order upsert for order_id={} log_file={}", order_id, path)
            try:
                result = OrderUpsertMicrotechService().upsert_order(order, erp=erp)
                return {
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "erp_order_id": result.erp_order_id,
                    "is_new": result.is_new,
                }
            finally:
                if sink_id is not None:
                    logger.info("Finished worker order upsert for order_id={}", order_id)
                    logger.remove(sink_id)

        if job.job_type == MicrotechJob.JobType.SYNC_EXPIRED_SPECIALS:
            affected = {int(item) for item in payload.get("affected_product_ids", [])}
            write_back = bool(payload.get("write_base_price_back"))
            updated_microtech, skipped = MicrotechExpiredSpecialSyncService().sync_expired_specials_to_microtech(
                erp=erp,
                affected_product_ids=affected,
                write_base_price_back=write_back,
            )
            return {
                "updated_microtech": updated_microtech,
                "skipped_price_writes": skipped,
                "write_base_price_back": write_back,
                "processed_at": timezone.now().isoformat(),
            }

        raise ValueError(f"Unsupported Microtech job type: {job.job_type}")
