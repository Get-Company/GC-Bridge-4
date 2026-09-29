from __future__ import annotations

from django.core.mail import get_connection

from core.services.base import BaseService
from organization.models import OrganizationContact


class OrganizationContactSmtpError(RuntimeError):
    pass


class OrganizationContactSmtpService(BaseService):
    model = OrganizationContact

    @staticmethod
    def build_connection(contact: OrganizationContact):
        if not contact.smtp_is_configured:
            raise OrganizationContactSmtpError(
                "Die SMTP-Konfiguration des Ansprechpartners ist unvollständig."
            )
        return get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=contact.smtp_host,
            port=contact.smtp_port,
            username=contact.smtp_username or None,
            password=contact.smtp_password or None,
            use_tls=contact.smtp_security == OrganizationContact.SmtpSecurity.STARTTLS,
            use_ssl=contact.smtp_security == OrganizationContact.SmtpSecurity.SSL,
            timeout=contact.smtp_timeout,
        )

    def test_connection(self, contact: OrganizationContact) -> None:
        connection = self.build_connection(contact)
        try:
            connection.open()
        finally:
            connection.close()
