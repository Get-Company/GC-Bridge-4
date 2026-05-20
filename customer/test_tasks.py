from unittest.mock import patch

from django.test import SimpleTestCase

from customer import tasks as customer_tasks


class CustomerCeleryTaskTest(SimpleTestCase):
    @patch("customer.tasks.call_command")
    def test_customer_lookup_delegates_to_management_command(self, mock_call_command):
        customer_tasks.microtech_customer_lookup.run(" 100012 ")

        mock_call_command.assert_called_once_with("microtech_customer_lookup", "100012")

    def test_customer_lookup_requires_erp_number(self):
        with self.assertRaises(ValueError):
            customer_tasks.microtech_customer_lookup.run("")
