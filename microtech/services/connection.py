from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from typing import Any

from loguru import logger

from core.services import BaseService

try:
    import pythoncom
    import win32com.client as win32
    import pywintypes
except ImportError:  # pragma: no cover - only relevant on non-Windows machines
    pythoncom = None
    win32 = None
    pywintypes = None


@dataclass(frozen=True)
class MicrotechConnectionConfig:
    mandant: str
    firma: str
    user: str
    manual_user: str

    @classmethod
    def from_env(cls) -> "MicrotechConnectionConfig":
        return cls(
            mandant=os.getenv("MICROTECH_MANDANT", ""),
            firma=os.getenv("MICROTECH_FIRMA", ""),
            user=os.getenv("MICROTECH_BENUTZER", ""),
            manual_user=os.getenv("MICROTECH_MANUAL_BENUTZER", ""),
        )

    def select_user(self, manual: bool) -> str:
        if manual and self.manual_user:
            return self.manual_user
        return self.user


class MicrotechConnectionService(BaseService):
    def __init__(self, *, config: MicrotechConnectionConfig | None = None, manual: bool = False) -> None:
        self.config = config or MicrotechConnectionConfig.from_env()
        self.manual = manual
        self.erp: Any | None = None
        self._connection_initialized = False

    def connect(self, *, manual: bool | None = None) -> Any:
        if self.erp is not None:
            logger.info("Reusing existing Microtech ERP connection.")
            return self.erp

        if win32 is None or pythoncom is None:
            raise RuntimeError("pywin32 is required to use the Microtech COM connection.")

        manual = self.manual if manual is None else manual
        user = self.config.select_user(manual)
        if not all([self.config.mandant, self.config.firma, user]):
            raise ValueError("Missing Microtech connection environment variables.")

        logger.info("Connecting to Microtech ERP (mandant='{}', user='{}').", self.config.mandant, user)
        try:
            pythoncom.CoInitialize()
            self._connection_initialized = True
            self.erp = win32.Dispatch("BpNT.Application")
            self.erp.Init(self.config.firma, "", user, "")
            self.erp.SelectMand(self.config.mandant)
            logger.success("Microtech ERP connection established.")
            return self.erp
        except Exception as exc:  # pywintypes.com_error on Windows
            logger.error("Failed to connect to Microtech ERP: {}", exc)
            self.close()
            raise

    def close(self) -> None:
        if self.erp is None:
            return
        try:
            logger.info("Closing Microtech ERP connection.")
            self.erp.DeInit()
        except Exception as exc:  # pywintypes.com_error on Windows
            logger.warning("Error while closing Microtech ERP connection: {}", exc)
        finally:
            self.erp = None
            if self._connection_initialized and pythoncom is not None:
                pythoncom.CoUninitialize()
            self._connection_initialized = False
            logger.info("Microtech ERP connection closed.")

    def __enter__(self) -> Any:
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


@contextmanager
def microtech_connection(*, manual: bool = False, config: MicrotechConnectionConfig | None = None):
    service = MicrotechConnectionService(config=config, manual=manual)
    try:
        yield service.connect()
    finally:
        service.close()
