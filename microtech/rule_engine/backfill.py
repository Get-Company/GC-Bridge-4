from __future__ import annotations


def backfill_condition_groups(RuleModel, GroupModel, TriggerModel):
    order_trigger = TriggerModel.objects.filter(code="order_create").first()
    for rule in RuleModel.objects.all():
        root = GroupModel.objects.filter(rule=rule, parent__isnull=True).first()
        if root is None:
            root = GroupModel.objects.create(
                rule=rule, parent=None, logic=rule.condition_logic, is_active=True, priority=100)
            rule.conditions.filter(group__isnull=True).update(group=root)
        if order_trigger is not None and rule.trigger_id is None:
            rule.trigger = order_trigger
            rule.save(update_fields=["trigger", "updated_at"])
