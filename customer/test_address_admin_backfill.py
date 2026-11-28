from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib import admin
from django.test import SimpleTestCase

from core.admin import BaseAdmin
from customer.admin import AddressAdmin
from customer.models import Address


class AddressAdminBackfillTest(SimpleTestCase):
    @patch("customer.views._backfill_orders_after_mapping")
    @patch("customer.admin.transaction.on_commit")
    @patch.object(BaseAdmin, "save_model")
    def test_mapping_change_reconciles_orders_after_commit(self, save, on_commit, backfill):
        address = SimpleNamespace(pk=1035, api_id="c" * 32, erp_ans_nr=1)
        form = SimpleNamespace(changed_data=["erp_ans_nr"])
        request = MagicMock()

        AddressAdmin(Address, admin.site).save_model(request, address, form, True)
        on_commit.assert_called_once()
        backfill.assert_not_called()

        on_commit.call_args.args[0]()
        backfill.assert_called_once_with(1035)
        save.assert_called_once_with(request, address, form, True)
