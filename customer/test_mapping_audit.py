import json

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from customer.models import Address, Customer
from customer.views import customer_update_ids_api


class MicrotechMappingAuditTest(TestCase):
    def test_manual_mapping_records_actor_and_old_and_new_numbers(self):
        customer = Customer.objects.create(erp_nr="37527")
        address = Address.objects.create(customer=customer, erp_ans_nr=2, erp_asp_nr=1)
        operator = get_user_model().objects.create_user(username="mapping-operator")
        request = RequestFactory().post("/", data=json.dumps({
            "action": "update_microtech_address_mapping", "address_id": address.pk,
            "ans_nr": 1, "asp_nr": 2,
        }), content_type="application/json")
        request.user = operator

        self.assertEqual(customer_update_ids_api(request).status_code, 200)
        entry = LogEntry.objects.get(user=operator, object_id=str(address.pk))
        self.assertEqual(json.loads(entry.change_message)["microtech_mapping"], {
            "before": {"ans_nr": 2, "asp_nr": 1}, "after": {"ans_nr": 1, "asp_nr": 2},
        })
