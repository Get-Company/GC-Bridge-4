from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from django.test import SimpleTestCase

from customer.models import Address, Customer
from customer.services.customer_mapping import CustomerMappingService
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService


class ManualCustomerMappingTests(SimpleTestCase):
    def test_microtech_job_must_contain_the_selected_customer(self):
        with patch(
            "customer.services.customer_mapping.CustomerMergeSearchService.get_microtech_search_job_status",
            return_value={"state": "succeeded", "data": {"erp_nr": "999"}},
        ):
            with self.assertRaisesRegex(ValueError, "stimmt nicht"):
                CustomerMappingService._microtech_customer(7, "123")

    def test_explicit_address_numbers_override_identical_postal_text(self):
        service = CustomerUpsertMicrotechService()
        a = Address(erp_ans_nr=1, street="Hauptstr. 1", city="Berlin")
        b = Address(erp_ans_nr=2, street="Hauptstr. 1", city="Berlin")
        self.assertFalse(service._same_address(a, b))

    def test_mapped_address_without_contact_does_not_create_a_person(self):
        service = CustomerUpsertMicrotechService()
        client = MagicMock()
        service._upsert_contact_person_graphql(
            client=client, address_number=123, address_sub_number=4,
            address=Address(erp_ans_nr=4, erp_asp_nr=None, first_name="Max"),
        )
        client.create_contact_person.assert_not_called()
        client.update_contact_person.assert_not_called()

    def test_new_postal_address_can_still_create_its_contact(self):
        service = CustomerUpsertMicrotechService()
        client = MagicMock()
        client.create_contact_person.return_value = {"contactPerson": {"contactNumber": 7}}
        with patch.object(service, "_build_contact_person_input", return_value={"firstName": "Max"}), \
             patch.object(service, "_persist_ansprechpartner_identity"):
            service._upsert_contact_person_graphql(
                client=client, address_number=123, address_sub_number=4,
                address=Address(erp_ans_nr=4, first_name="Max"), create_if_unmapped=True,
            )
        client.create_contact_person.assert_called_once_with(
            123, 4, {"firstName": "Max", "isDefault": True},
        )

    def test_no_selected_contact_clears_old_remote_default(self):
        client = MagicMock()
        CustomerUpsertMicrotechService._clear_existing_default_contact_flags(
            client=client, address_number=123, address_sub_number=4,
            selected_contact_number=None,
            customer={"addresses": [{"addressSubNumber": 4, "contacts": [
                {"contactNumber": 2, "isDefault": True},
                {"contactNumber": 3, "isDefault": False},
            ]}]},
        )
        client.update_contact_person.assert_called_once_with(123, 4, 2, {"isDefault": False})

    def test_selected_contact_replaces_old_default_on_its_address(self):
        client = MagicMock()
        CustomerUpsertMicrotechService._clear_existing_default_contact_flags(
            client=client, address_number=123, address_sub_number=4,
            selected_contact_number=3,
            customer={"addresses": [{"addressSubNumber": 4, "contacts": [
                {"contactNumber": 2, "isDefault": True},
                {"contactNumber": 3, "isDefault": False},
            ]}]},
        )
        client.update_contact_person.assert_called_once_with(123, 4, 2, {"isDefault": False})

    def test_transfer_rejects_two_contacts_for_one_postal_address(self):
        customer = SimpleNamespace(pk=1, erp_nr="123", api_id="a" * 32, addresses=MagicMock())
        a = Address(id=11, api_id="b" * 32, erp_ans_nr=4,
                    erp_asp_nr=2, street="Hauptstr. 1", postal_code="12345", city="Berlin")
        b = Address(id=12, api_id="c" * 32, erp_ans_nr=4,
                    erp_asp_nr=3, street="Hauptstr. 1", postal_code="12345", city="Berlin")
        customer.addresses.exclude.return_value.filter.return_value = [a, b]
        with patch("customer.services.customer_mapping.Customer.objects.prefetch_related") as lookup:
            lookup.return_value.filter.return_value.first.return_value = customer
            with patch.object(CustomerMappingService, "_shopware_customer", return_value={
                "defaultShippingAddressId": a.api_id,
                "defaultBillingAddressId": b.api_id,
                "addresses": [{"id": a.api_id}, {"id": b.api_id}],
            }):
                with self.assertRaisesRegex(ValueError, "verschiedenen Ansprechpartnern"):
                    CustomerMappingService().sync_customer(customer_id=1, user_id=1)

    def test_transfer_checks_the_selected_contact_after_microtech_write(self):
        sw_id = "a" * 32
        address_id = "b" * 32
        customer = SimpleNamespace(pk=1, erp_nr="123", api_id=sw_id, addresses=MagicMock())
        address = Address(id=11, api_id=address_id, erp_ans_nr=4, erp_asp_nr=2,
                          street="Hauptstr. 1", postal_code="12345", city="Berlin",
                          first_name="Max", last_name="Muster")
        customer.addresses.exclude.return_value.filter.return_value = [address]
        remote = {"customerNumber": "123", "defaultShippingAddressNumber": 4,
                  "defaultBillingAddressNumber": 4, "addresses": [{
                      "addressSubNumber": 4, "isDefaultShipping": True,
                      "isDefaultBilling": True, "street": "Hauptstr. 1",
                      "zipCode": "12345", "city": "Berlin",
                      "contacts": [{"contactNumber": 2, "isDefault": True,
                                    "firstName": "Max", "lastName": "Muster"}],
                  }]}
        client = MagicMock()
        client.request_customer.side_effect = [{"customer": remote}, {"customer": remote}]
        connection = MagicMock()
        connection.__enter__.return_value = client
        with patch("customer.services.customer_mapping.Customer.objects.prefetch_related") as lookup, \
             patch("customer.services.customer_mapping.Customer.objects.filter"), \
             patch("customer.services.customer_mapping.LogEntry.objects.log_actions"), \
             patch("microtech.services.microtech_connection", return_value=connection), \
             patch.object(CustomerMappingService, "_shopware_customer", return_value={
                 "defaultShippingAddressId": address_id,
                 "defaultBillingAddressId": address_id,
                 "addresses": [{"id": address_id}],
             }), \
             patch("customer.services.customer_mapping.CustomerUpsertMicrotechService.upsert_customer") as upsert:
            lookup.return_value.filter.return_value.first.return_value = customer
            result = CustomerMappingService().sync_customer(customer_id=1, user_id=1)
        self.assertEqual(result["addresses_checked"], 1)
        self.assertEqual(client.request_customer.call_count, 2)
        upsert.assert_called_once()

    def test_conflicting_contact_defaults_fail_before_remote_write(self):
        customer = Customer(erp_nr="123", name="Firma")
        shipping = Address(customer=customer, erp_ans_nr=4, erp_asp_nr=2, is_shipping=True)
        billing = Address(customer=customer, erp_ans_nr=4, erp_asp_nr=3, is_invoice=True)
        client = MagicMock()
        with patch("microtech.rule_engine.dispatch.ensure_customer_scope_email_targets_are_distinct_with_mode"):
            with self.assertRaisesRegex(ValueError, "unterschiedliche Ansprechpartner"):
                CustomerUpsertMicrotechService()._upsert_customer_graphql(
                    customer=customer, shipping=shipping, billing=billing,
                    na1_mode="auto", na1_static_value="", input_overrides=None, client=client,
                )
        client.update_customer.assert_not_called()
        client.create_customer.assert_not_called()
