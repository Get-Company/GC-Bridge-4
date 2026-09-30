from unittest.mock import MagicMock

import pytest


def test_extracts_configured_adrnr_custom_field(settings):
    from newsletter.services.recipient_sync import _extract_recipient_erp_nr

    settings.NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD = "GecoAdrNr"

    assert _extract_recipient_erp_nr({"customFields": {"GecoAdrNr": " 10042 "}}) == "10042"


def test_extracts_adrnr_from_technical_custom_field_suffix(settings):
    from newsletter.services.recipient_sync import _extract_recipient_erp_nr

    settings.NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD = "AdrNr"

    assert (
        _extract_recipient_erp_nr(
            {"customFields": {"geco_newsletter_recipient_adr_nr": 10042.0}}
        )
        == "10042"
    )


@pytest.mark.django_db
def test_sync_links_recipient_by_adrnr_before_email_lookup(settings):
    from customer.models import Customer
    from newsletter.services import NewsletterRecipientSyncService

    settings.NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD = "AdrNr"
    customer = Customer.objects.create(erp_nr="10042", name="Muster GmbH")
    customer_service = MagicMock()

    recipient, created = NewsletterRecipientSyncService().upsert_from_shopware(
        {
            "id": "newsletter-recipient-id",
            "email": "kontakt@example.com",
            "status": "optIn",
            "customFields": {"AdrNr": "10042"},
        },
        customer_service=customer_service,
    )

    assert created is True
    assert recipient.erp_nr == "10042"
    assert recipient.customer == customer
    assert recipient.is_customer is True
    customer_service.get_by_email.assert_not_called()


@pytest.mark.django_db
def test_sync_uses_unique_shopware_email_lookup_customer_number_as_fallback(settings):
    from customer.models import Customer
    from newsletter.services import NewsletterRecipientSyncService

    settings.NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD = "AdrNr"
    customer = Customer.objects.create(erp_nr="10042", name="Muster GmbH")
    customer_service = MagicMock()
    customer_service.get_by_email.return_value = {
        "total": 1,
        "data": [
            {
                "id": "shopware-customer-id",
                "customerNumber": "10042",
            }
        ],
    }

    recipient, _ = NewsletterRecipientSyncService().upsert_from_shopware(
        {
            "id": "newsletter-recipient-id",
            "email": "kontakt@example.com",
            "status": "optIn",
            "customFields": {},
        },
        customer_service=customer_service,
    )

    assert recipient.erp_nr == "10042"
    assert recipient.customer_shopware_id == "shopware-customer-id"
    assert recipient.customer == customer
    customer_service.get_by_email.assert_called_once_with(
        email="kontakt@example.com",
        sales_channel_id="",
        limit=2,
    )


@pytest.mark.django_db
def test_sync_does_not_link_ambiguous_email_matches(settings):
    from newsletter.services import NewsletterRecipientSyncService

    settings.NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD = "AdrNr"
    customer_service = MagicMock()
    customer_service.get_by_email.return_value = {
        "total": 2,
        "data": [
            {"id": "customer-a", "customerNumber": "10001"},
            {"id": "customer-b", "customerNumber": "10002"},
        ],
    }

    recipient, _ = NewsletterRecipientSyncService().upsert_from_shopware(
        {
            "id": "newsletter-recipient-id",
            "email": "shared@example.com",
            "status": "optIn",
        },
        customer_service=customer_service,
    )

    assert recipient.erp_nr == ""
    assert recipient.customer_shopware_id == ""
    assert recipient.customer is None
    assert recipient.is_customer is False


@pytest.mark.django_db
def test_relink_existing_uses_stored_custom_fields(settings):
    from customer.models import Customer
    from newsletter.models import NewsletterRecipient
    from newsletter.services import NewsletterRecipientSyncService

    settings.NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD = "AdrNr"
    customer = Customer.objects.create(erp_nr="10042", name="Muster GmbH")
    recipient = NewsletterRecipient.objects.create(
        shopware_id="newsletter-recipient-id",
        email="kontakt@example.com",
        custom_fields={"AdrNr": "10042"},
    )

    summary = NewsletterRecipientSyncService().relink_existing()

    recipient.refresh_from_db()
    assert summary == {
        "seen": 1,
        "updated": 1,
        "linked": 1,
        "unlinked": 0,
    }
    assert recipient.erp_nr == "10042"
    assert recipient.customer == customer
    assert recipient.is_customer is True


@pytest.mark.django_db
def test_sync_leaves_conflicting_adrnr_and_shopware_customer_unlinked(settings):
    from customer.models import Customer
    from newsletter.services import NewsletterRecipientSyncService

    settings.NEWSLETTER_RECIPIENT_ERP_CUSTOM_FIELD = "AdrNr"
    Customer.objects.create(
        erp_nr="10001",
        api_id="shopware-customer-id",
        name="Anderer Kunde",
    )

    recipient, _ = NewsletterRecipientSyncService().upsert_from_shopware(
        {
            "id": "newsletter-recipient-id",
            "customerId": "shopware-customer-id",
            "email": "kontakt@example.com",
            "status": "optIn",
            "customFields": {"AdrNr": "10042"},
        },
        customer_service=MagicMock(),
    )

    assert recipient.erp_nr == "10042"
    assert recipient.customer_shopware_id == "shopware-customer-id"
    assert recipient.customer is None
    assert recipient.is_customer is False
