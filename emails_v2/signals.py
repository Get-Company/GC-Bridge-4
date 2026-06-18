from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="emails.MjmlComponent")
def update_detected_variables(sender, instance, **kwargs):
    from emails_v2.variable_parser import extract_variables
    new_vars = extract_variables(instance.mjml_markup)
    if new_vars != instance.detected_variables:
        sender.objects.filter(pk=instance.pk).update(detected_variables=new_vars)

