from unfold.admin import ModelAdmin as UnfoldModelAdmin


class BaseAdmin(UnfoldModelAdmin):
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
