import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from jinja2 import TemplateSyntaxError


logger = logging.getLogger(__name__)


@receiver(post_save, sender="emails.MjmlComponent")
def update_detected_variables(sender, instance, **kwargs):
    from emails_v2.variable_parser import extract_variables

    if getattr(instance, "rendering_mode", "jinja") == "shopware":
        new_vars = []
    else:
        try:
            new_vars = extract_variables(instance.mjml_markup)
        except TemplateSyntaxError as error:
            logger.warning(
                "Detected variables were not updated for MJML component %s because its "
                "Jinja syntax is invalid on line %s: %s",
                instance.pk,
                error.lineno,
                error.message,
            )
            return

    if new_vars != instance.detected_variables:
        sender.objects.filter(pk=instance.pk).update(detected_variables=new_vars)
