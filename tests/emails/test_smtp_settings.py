from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError


def test_smtp_settings_require_username_and_password_together():
    from emails.models import EmailSmtpSettings

    configuration = EmailSmtpSettings(
        host="smtp.example.com",
        sender_email="newsletter@example.com",
        username="newsletter@example.com",
        password="",
    )

    with pytest.raises(ValidationError) as exc_info:
        configuration.full_clean()

    assert "username" in exc_info.value.message_dict
    assert "password" in exc_info.value.message_dict


def test_smtp_settings_cannot_be_activated_incomplete():
    from emails.models import EmailSmtpSettings

    configuration = EmailSmtpSettings(is_active=True)

    with pytest.raises(ValidationError) as exc_info:
        configuration.full_clean()

    assert "is_active" in exc_info.value.message_dict


@patch("emails.services.get_connection")
def test_smtp_service_builds_and_tests_starttls_connection(get_connection):
    from emails.models import EmailSmtpSettings
    from emails.services import EmailSmtpSettingsService

    connection = MagicMock()
    get_connection.return_value = connection
    configuration = EmailSmtpSettings(
        host="smtp.example.com",
        port=587,
        security=EmailSmtpSettings.Security.STARTTLS,
        username="newsletter@example.com",
        password="secret",
        sender_email="newsletter@example.com",
        timeout=45,
    )

    EmailSmtpSettingsService().test_connection(configuration)

    get_connection.assert_called_once_with(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host="smtp.example.com",
        port=587,
        username="newsletter@example.com",
        password="secret",
        use_tls=True,
        use_ssl=False,
        timeout=45,
    )
    connection.open.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_smtp_settings_reply_to_falls_back_to_sender():
    from emails.models import EmailSmtpSettings

    configuration = EmailSmtpSettings(sender_email="newsletter@example.com")

    assert configuration.effective_reply_to_email == "newsletter@example.com"
