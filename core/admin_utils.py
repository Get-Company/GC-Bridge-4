from django.contrib.admin.models import CHANGE, LogEntry


def log_admin_change(
    *,
    user_id: int,
    content_type_id: int,
    object_id: str | None,
    object_repr: str,
    message: str,
) -> None:
    if hasattr(LogEntry.objects, "log_action"):
        LogEntry.objects.log_action(
            user_id=user_id,
            content_type_id=content_type_id,
            object_id=object_id,
            object_repr=object_repr,
            action_flag=CHANGE,
            change_message=message,
        )
        return

    LogEntry.objects.log_actions(
        user_id,
        [
            {
                "content_type_id": content_type_id,
                "object_id": object_id,
                "object_repr": object_repr,
                "action_flag": CHANGE,
                "change_message": message,
            }
        ],
        single_object=True,
    )
