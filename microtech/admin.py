import json

from django.contrib import admin, messages
from django.db import models, transaction
from django.http import HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import reverse

from core.admin import BaseAdmin, BaseStackedInline
from microtech.forms import (
    MicrotechOrderRuleActionForm,
    MicrotechOrderRuleConditionForm,
    condition_example_for_field,
)
from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechGraphQLJob,
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCategory,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleDjangoField,
    MicrotechOrderRuleDjangoFieldPolicy,
    MicrotechOrderRuleOperator,
    MicrotechSettings,
    MicrotechSwissCustomsFieldMapping,
    RuleEngineExecutionLog,
    RuleConstant,
    RuleTrigger,
)
from microtech.services import MicrotechJobSentinelService
from microtech.graphql_schema import (
    get_rule_action_excluded_fields,
    get_rule_action_scopes,
    get_rule_trigger_input_types,
)
from microtech.rule_builder import (
    get_address_field_defs,
    get_allowed_operator_codes,
    get_customer_field_defs,
    get_django_field_defs,
    get_operator_defs,
    get_rule_action_target_defs,
)
from microtech.rule_engine.editor import (
    EditorValidationError,
    save_rule_from_payload,
    serialize_rule_for_edit,
)
from microtech.rule_engine.overview import serialize_rules_for_overview
from microtech.rule_mapping import (
    build_mapping_checklist,
    effective_target_assignments,
    ensure_default_rule_categories,
    friendly_trigger_label,
    mapping_conflicts,
    next_category_code,
    next_rule_priority,
)
from microtech.views.autocomplete import (
    MicrotechDatasetFieldAutocompleteView,
    MicrotechOrderRuleOperatorAutocompleteView,
)


class SingletonAdmin(BaseAdmin):
    """Admin base for singleton models: the changelist redirects straight to the single edit form."""

    def changelist_view(self, request, extra_context=None):
        obj = self.model.load()
        url = reverse(
            f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
            args=(obj.pk,),
        )
        return HttpResponseRedirect(url)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MicrotechGraphQLJob)
class MicrotechGraphQLJobAdmin(BaseAdmin):
    list_display = (
        "id",
        "kind",
        "status_badge",
        "operation",
        "external_job_id",
        "next_submit_at",
        "submission_attempt",
        "running_since",
        "next_step_short",
        "continuation_status",
        "continuation_attempt",
        "next_poll_at",
        "updated_at",
    )
    search_fields = ("external_job_id", "operation", "continuation", "next_step", "error_message")
    list_filter = (
        "status",
        "continuation_status",
        "kind",
        "operation",
        "abort_strategy",
        "delete_after_completion",
    )
    actions = ("cancel_selected_jobs", "delete_selected_jobs_remote")
    readonly_fields = BaseAdmin.readonly_fields + (
        "kind",
        "operation",
        "status",
        "external_job_id",
        "external_job_history",
        "submission_task_id",
        "submission_lease_expires_at",
        "next_submit_at",
        "submission_attempt",
        "submission_max_attempts",
        "continuation",
        "continuation_status",
        "continuation_task_id",
        "continuation_dispatched_at",
        "continuation_started_at",
        "continuation_heartbeat_at",
        "continuation_lease_expires_at",
        "continuation_completed_at",
        "continuation_attempt",
        "continuation_max_attempts",
        "next_step",
        "request_payload",
        "context",
        "result_payload",
        "error_message",
        "abort_strategy",
        "delete_after_completion",
        "submitted_at",
        "started_at",
        "completed_at",
        "webhook_received_at",
        "last_polled_at",
        "next_poll_at",
        "remote_deleted_at",
        "attempt",
        "max_attempts",
    )
    fieldsets = (
        (
            "Status",
            {
                "fields": (
                    "kind",
                    "operation",
                    "status",
                    "external_job_id",
                    "next_step",
                    "submission_task_id",
                    "continuation",
                    "continuation_status",
                    "continuation_task_id",
                    "abort_strategy",
                    "delete_after_completion",
                ),
            },
        ),
        (
            "Zeitpunkte",
            {
                "fields": (
                    "submitted_at",
                    "next_submit_at",
                    "submission_lease_expires_at",
                    "submission_attempt",
                    "submission_max_attempts",
                    "started_at",
                    "completed_at",
                    "webhook_received_at",
                    "last_polled_at",
                    "next_poll_at",
                    "remote_deleted_at",
                    "attempt",
                    "max_attempts",
                    "continuation_dispatched_at",
                    "continuation_started_at",
                    "continuation_heartbeat_at",
                    "continuation_lease_expires_at",
                    "continuation_completed_at",
                    "continuation_attempt",
                    "continuation_max_attempts",
                ),
            },
        ),
        (
            "Payloads",
            {
                "fields": (
                    "request_payload",
                    "context",
                    "result_payload",
                    "external_job_history",
                    "error_message",
                ),
            },
        ),
        (
            "System",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="Status")
    def status_badge(self, obj):
        return obj.get_status_display()

    @admin.display(description="Laeuft seit")
    def running_since(self, obj):
        started = obj.started_at or obj.submitted_at or obj.created_at
        if not started:
            return "-"
        end = obj.completed_at or obj.updated_at if obj.is_terminal else None
        if end is None:
            from django.utils import timezone

            end = timezone.now()
        seconds = max(0, int((end - started).total_seconds()))
        minutes, remainder = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {remainder}s"
        return f"{remainder}s"

    @admin.display(description="Naechster Schritt")
    def next_step_short(self, obj):
        value = (obj.next_step or "").strip()
        if len(value) > 90:
            return f"{value[:87]}..."
        return value or "-"

    @admin.action(description="Ausgewaehlte Jobs abbrechen")
    def cancel_selected_jobs(self, request, queryset):
        service = MicrotechJobSentinelService()
        cancelled = 0
        failed = 0
        for job in queryset:
            try:
                service.cancel_job(job_id=job.pk)
                cancelled += 1
            except Exception as exc:
                failed += 1
                self.message_user(request, f"Job {job.pk} konnte nicht abgebrochen werden: {exc}", level=messages.ERROR)
        if cancelled:
            self.message_user(request, f"{cancelled} Microtech Job(s) abgebrochen.")
        if failed:
            self.message_user(request, f"{failed} Microtech Job(s) mit Fehlern.", level=messages.ERROR)

    @admin.action(description="Ausgewaehlte Jobs remote und lokal loeschen")
    def delete_selected_jobs_remote(self, request, queryset):
        service = MicrotechJobSentinelService()
        deleted = 0
        failed = 0
        for job in queryset:
            try:
                service.delete_job(job_id=job.pk, delete_remote=True)
                deleted += 1
            except Exception as exc:
                failed += 1
                self.message_user(request, f"Job {job.pk} konnte nicht geloescht werden: {exc}", level=messages.ERROR)
        if deleted:
            self.message_user(request, f"{deleted} Microtech Job(s) geloescht.")
        if failed:
            self.message_user(request, f"{failed} Microtech Job(s) mit Fehlern.", level=messages.ERROR)

    def delete_model(self, request, obj):
        MicrotechJobSentinelService().delete_job(job_id=obj.pk, delete_remote=True)

    def delete_queryset(self, request, queryset):
        service = MicrotechJobSentinelService()
        for job in queryset:
            service.delete_job(job_id=job.pk, delete_remote=True)


@admin.register(RuleEngineExecutionLog)
class RuleEngineExecutionLogAdmin(BaseAdmin):
    """Read-only audit trail for every evaluated rule."""

    list_display = (
        "created_at",
        "subject",
        "task_name",
        "engine_mode",
        "rule_name",
        "outcome",
        "reason",
    )
    list_filter = ("task_name", "engine_mode", "execution_phase", "outcome")
    search_fields = ("subject", "rule_name", "task_name", "run_id")
    readonly_fields = BaseAdmin.readonly_fields + (
        "run_id",
        "task_name",
        "execution_phase",
        "engine_mode",
        "subject",
        "rule",
        "rule_name",
        "outcome",
        "reason",
        "conditions_json",
        "actions_json",
    )
    fieldsets = (
        (
            "Regel-Auswertung",
            {
                "fields": (
                    "run_id",
                    "subject",
                    "task_name",
                    "execution_phase",
                    "engine_mode",
                    "rule",
                    "rule_name",
                    "outcome",
                    "reason",
                ),
            },
        ),
        ("Bedingungen", {"fields": ("conditions_json",)}),
        ("Aktionen", {"fields": ("actions_json",)}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj=obj)


@admin.register(MicrotechSettings)
class MicrotechSettingsAdmin(SingletonAdmin):
    readonly_fields = BaseAdmin.readonly_fields + (
        "graphql_circuit_open_until",
        "graphql_consecutive_failures",
        "graphql_last_failure_at",
        "graphql_last_error",
    )
    fieldsets = (
        (
            "Vorgang-Standardwerte",
            {
                "fields": ("default_vorgangsart_id", "default_zahlungsart_id", "default_versandart_id"),
                "description": "Standard-IDs fuer neue Microtech-Bestellungen (Vorgaenge).",
            },
        ),
        (
            "GraphQL-Verfügbarkeit",
            {
                "fields": (
                    "graphql_circuit_open_until",
                    "graphql_consecutive_failures",
                    "graphql_last_failure_at",
                    "graphql_last_error",
                ),
                "description": "Automatisch verwalteter Circuit Breaker für die Verbindung zum Microtech-Wrapper.",
            },
        ),
    )


@admin.register(MicrotechSwissCustomsFieldMapping)
class MicrotechSwissCustomsFieldMappingAdmin(BaseAdmin):
    list_display = (
        "priority",
        "portal_field",
        "section",
        "source_type",
        "source_preview_short",
        "is_required",
        "is_active",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("portal_field", "source_path", "static_value", "help_text")
    list_filter = ("is_active", "section", "source_type", "is_required", "value_kind")
    ordering = ("priority", "portal_field", "id")
    fieldsets = (
        (
            "Zollportal Feldmapping",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "portal_field",
                    "section",
                    "source_type",
                    "source_path",
                    "static_value",
                    "value_kind",
                    "is_required",
                    "help_text",
                ),
                "description": (
                    "Mapping der GLS-/Schweiz-Zollfelder auf statische Werte oder Quellen aus dem neuen Django-Projekt. "
                    "Bei 'computed' steht im Quellpfad ein Resolver-Key fuer spaetere Aufloesung."
                ),
            },
        ),
    )

    @admin.display(description="Quelle / Wert")
    def source_preview_short(self, obj):
        value = (obj.source_preview or "").strip()
        if len(value) > 80:
            return f"{value[:77]}..."
        return value


@admin.register(MicrotechOrderRule)
class MicrotechOrderRuleAdmin(BaseAdmin):
    class ConditionInline(BaseStackedInline):
        model = MicrotechOrderRuleCondition
        form = MicrotechOrderRuleConditionForm
        fields = (
            "is_active",
            "priority",
            "django_field",
            "operator",
            "expected_value",
            "value_example",
        )
        autocomplete_fields = ("django_field", "operator")
        readonly_fields = BaseStackedInline.readonly_fields + ("value_example",)
        extra = 0
        verbose_name = "Bedingung"
        verbose_name_plural = "Wann greift die Regel?"

        @admin.display(description="Beispiel")
        def value_example(self, obj):
            if not obj:
                return "Waehle zuerst ein Feld. Der Beispielwert folgt automatisch."
            return condition_example_for_field(obj.django_field_path)

    class ActionInline(BaseStackedInline):
        model = MicrotechOrderRuleAction
        form = MicrotechOrderRuleActionForm
        fields = (
            "is_active",
            "priority",
            "ui_action",
            # Verstecktes Feld: die Form erwartet action_type und clean()
            # schreibt es; ohne das Feld wirft __init__ einen KeyError.
            "action_type",
            "dataset_field",
            "target_value",
            "action_context_preview",
        )
        autocomplete_fields = ("dataset_field",)
        readonly_fields = BaseStackedInline.readonly_fields + ("action_context_preview",)
        extra = 0
        verbose_name = "Aktion"
        verbose_name_plural = "Was soll in Microtech passieren?"

        @admin.display(description="Zielkontext")
        def action_context_preview(self, obj):
            if not obj:
                return "Waehle zuerst eine fachliche Aktion."
            if obj.action_type == MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION:
                return "Legt eine Zusatzposition an. Zielwert = ERP-Nr der Position."
            if obj.action_type == MicrotechOrderRuleAction.ActionType.CREATE_TEXT_POSITION:
                return "Legt eine reine Textposition an. Zielwert = Bezeichnung der Position."
            if obj.action_type == MicrotechOrderRuleAction.ActionType.CREATE_SHIPPING_POSITION:
                return "Legt eine Versandposition an. Artikel V oder F, Preis = Versandkosten."
            if obj.dataset_field_id and obj.dataset_id:
                try:
                    dataset_field = obj.dataset_field
                except Exception:
                    return "Gespeichertes Zielfeld konnte nicht mehr aufgeloest werden."
                if dataset_field is None:
                    return "Gespeichertes Zielfeld konnte nicht mehr aufgeloest werden."
                return dataset_field.display_label
            return "Waehle ein passendes Microtech-Zielfeld."

    list_display = (
        "priority",
        "name",
        "category",
        "is_active",
        "condition_logic",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("name",)
    list_filter = (
        "is_active",
        "condition_logic",
    )
    ordering = ("priority", "id")
    inlines = (ConditionInline, ActionInline)
    readonly_fields = BaseAdmin.readonly_fields + ("live_rule_summary",)

    class Media:
        js = ("microtech/js/order_rule_builder.js",)
        css = {
            "all": ("microtech/css/order_rule_builder.css",),
        }

    def get_custom_urls(self):
        urls = super().get_custom_urls()
        return (
            *urls,
            (
                "builder/",
                "microtech_orderrule_builder",
                self.rule_builder_view,
            ),
            (
                "rule-builder-meta/",
                "microtech_orderrule_builder_meta",
                self.rule_builder_meta_view,
            ),
            (
                "operator-autocomplete/",
                "microtech_orderrule_operator_autocomplete",
                MicrotechOrderRuleOperatorAutocompleteView.as_view(),
            ),
            (
                "dataset-field-autocomplete/",
                "microtech_orderrule_dataset_field_autocomplete",
                MicrotechDatasetFieldAutocompleteView.as_view(),
            ),
            (
                "builder/new/",
                "microtech_orderrule_editor_new",
                self.rule_editor_view,
            ),
            (
                "builder/<path:object_id>/edit/",
                "microtech_orderrule_editor",
                self.rule_editor_view,
            ),
            (
                "builder/save/",
                "microtech_orderrule_editor_save",
                self.rule_editor_save_view,
            ),
            (
                "builder/organize/",
                "microtech_orderrule_organize",
                self.rule_organize_view,
            ),
            (
                "rule-engine/verify/",
                "microtech_orderrule_engine_verify",
                self.rule_engine_verify_view,
            ),
            (
                "dataset-fields-grouped/",
                "microtech_orderrule_dataset_fields_grouped",
                self.rule_dataset_fields_grouped_view,
            ),
            (
                "graphql-fields-grouped/",
                "microtech_orderrule_graphql_fields_grouped",
                self.rule_graphql_fields_grouped_view,
            ),
        )

    def rule_graphql_fields_grouped_view(self, request, **kwargs):
        """GraphQL input fields grouped by input type, for the target dropdown."""
        if not self.has_view_permission(request):
            return JsonResponse({"ok": False, "error": "Zugriff verweigert."}, status=403)
        from microtech.graphql_schema import get_graphql_input_catalog

        refresh = request.GET.get("refresh") in ("1", "true", "yes")
        return JsonResponse(get_graphql_input_catalog(refresh=refresh))

    def rule_dataset_fields_grouped_view(self, request, **kwargs):
        """All active dataset fields grouped by dataset, for the target dropdown."""
        if not self.has_view_permission(request):
            return JsonResponse({"ok": False, "error": "Zugriff verweigert."}, status=403)
        from microtech.models import MicrotechDatasetCatalog

        datasets = []
        for cat in (
            MicrotechDatasetCatalog.objects
            .filter(is_active=True)
            .order_by("priority", "name", "id")
            .prefetch_related("fields")
        ):
            fields = [
                {
                    "id": f.id,
                    "field_name": f.field_name,
                    "label": (f.label or f.field_name),
                    "field_type": f.field_type or "",
                }
                for f in sorted(
                    (
                        x for x in cat.fields.all()
                        if x.is_active and x.can_access and not x.is_calc_field
                    ),
                    key=lambda x: (x.priority, x.field_name, x.id),
                )
            ]
            if fields:
                datasets.append({
                    "source_identifier": cat.source_identifier,
                    "name": cat.name,
                    "fields": fields,
                })
        return JsonResponse({"ok": True, "datasets": datasets})

    def rule_builder_view(self, request, **kwargs):
        if not self.has_view_permission(request):
            return HttpResponseRedirect(reverse("admin:index"))
        categories = ensure_default_rule_categories()
        rules = serialize_rules_for_overview()
        rules_by_category: dict[int | None, list[dict]] = {}
        for rule in rules:
            rules_by_category.setdefault(rule.get("category_id"), []).append(rule)
        category_panels = [
            {
                "id": category.id,
                "code": category.code,
                "name": category.name,
                "is_system": category.is_system,
                "rules": rules_by_category.pop(category.id, []),
            }
            for category in categories
        ]
        uncategorized_rules = [
            rule
            for grouped_rules in rules_by_category.values()
            for rule in grouped_rules
        ]
        if uncategorized_rules:
            category_panels.append({
                "id": None,
                "code": "ohne-kategorie",
                "name": "Ohne Kategorie",
                "is_system": True,
                "rules": uncategorized_rules,
            })
        context = {
            **self.admin_site.each_context(request),
            "title": "Regel-Mappings",
            "category_panels": category_panels,
            "mapping_checklist": build_mapping_checklist(),
            "mapping_conflicts": mapping_conflicts(),
            "opts": self.model._meta,
            "organize_url": reverse("admin:microtech_orderrule_organize"),
        }
        return TemplateResponse(request, "admin/microtech/rule_builder.html", context)

    def rule_organize_view(self, request, **kwargs):
        if request.method != "POST":
            return JsonResponse({"ok": False, "errors": ["Nur POST erlaubt."]}, status=405)
        if not self.has_change_permission(request):
            return JsonResponse({"ok": False, "errors": ["Zugriff verweigert."]}, status=403)

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "errors": ["Ungültiges JSON."]}, status=400)

        action = str(payload.get("action") or "").strip()
        try:
            with transaction.atomic():
                if action == "category_create":
                    name = str(payload.get("name") or "").strip()
                    if not name:
                        raise ValueError("Der Kategoriename darf nicht leer sein.")
                    if len(name) > 120:
                        raise ValueError("Der Kategoriename darf höchstens 120 Zeichen enthalten.")
                    if MicrotechOrderRuleCategory.objects.filter(name__iexact=name).exists():
                        raise ValueError("Eine Kategorie mit diesem Namen existiert bereits.")
                    last_priority = (
                        MicrotechOrderRuleCategory.objects
                        .aggregate(value=models.Max("priority"))["value"]
                        or 0
                    )
                    category = MicrotechOrderRuleCategory.objects.create(
                        code=next_category_code(name),
                        name=name,
                        priority=int(last_priority) + 10,
                    )
                    return JsonResponse({"ok": True, "category_id": category.id})

                category_id = payload.get("category_id")
                category = MicrotechOrderRuleCategory.objects.filter(
                    pk=category_id,
                    is_active=True,
                ).first()

                if action in {"category_rename", "category_delete"}:
                    if category is None:
                        raise ValueError("Kategorie wurde nicht gefunden.")
                    if category.is_system:
                        raise ValueError("Die Standardkategorien können nicht umbenannt oder gelöscht werden.")

                if action == "category_rename":
                    name = str(payload.get("name") or "").strip()
                    if not name:
                        raise ValueError("Der Kategoriename darf nicht leer sein.")
                    if len(name) > 120:
                        raise ValueError("Der Kategoriename darf höchstens 120 Zeichen enthalten.")
                    if MicrotechOrderRuleCategory.objects.filter(name__iexact=name).exclude(pk=category.pk).exists():
                        raise ValueError("Eine Kategorie mit diesem Namen existiert bereits.")
                    category.name = name
                    category.save(update_fields=("name", "updated_at"))
                    return JsonResponse({"ok": True})

                if action == "category_delete":
                    if category.rules.exists():
                        raise ValueError("Die Kategorie enthält noch Regeln. Bitte diese zuerst verschieben.")
                    category.delete()
                    return JsonResponse({"ok": True})

                if action in {"rule_copy", "rule_move", "rule_reorder"} and category is None:
                    raise ValueError("Zielkategorie wurde nicht gefunden.")

                if action == "rule_copy":
                    source = self.get_object(request, payload.get("rule_id"))
                    if source is None:
                        raise ValueError("Regel wurde nicht gefunden.")
                    rule_payload = serialize_rule_for_edit(source)
                    rule_payload.update({
                        "id": None,
                        "name": f"{source.name} (Kopie)",
                        "category_id": category.id,
                        "priority": next_rule_priority(category),
                        # A copy may initially share its targets.  Keeping it
                        # inactive makes that a safe draft until edited.
                        "is_active": False,
                    })
                    copied = save_rule_from_payload(rule_payload)
                    return JsonResponse({"ok": True, "rule_id": copied.id})

                if action == "rule_move":
                    rule = self.get_object(request, payload.get("rule_id"))
                    if rule is None:
                        raise ValueError("Regel wurde nicht gefunden.")
                    rule.category = category
                    rule.priority = next_rule_priority(category)
                    rule.save(update_fields=("category", "priority", "updated_at"))
                    return JsonResponse({"ok": True})

                if action == "rule_reorder":
                    try:
                        rule_ids = [int(value) for value in payload.get("rule_ids", [])]
                    except (TypeError, ValueError):
                        raise ValueError("Ungültige Reihenfolge.") from None
                    category_rule_ids = set(category.rules.values_list("id", flat=True))
                    if len(rule_ids) != len(set(rule_ids)) or set(rule_ids) != category_rule_ids:
                        raise ValueError("Die übermittelte Reihenfolge ist unvollständig.")
                    rules_by_id = {
                        rule.id: rule
                        for rule in category.rules.filter(id__in=rule_ids)
                    }
                    for priority, rule_id in enumerate(rule_ids, start=1):
                        rule = rules_by_id[rule_id]
                        rule.priority = priority * 10
                        rule.save(update_fields=("priority", "updated_at"))
                    return JsonResponse({"ok": True})

                raise ValueError("Unbekannte Verwaltungsaktion.")
        except EditorValidationError as exc:
            return JsonResponse({"ok": False, "errors": exc.messages}, status=400)
        except ValueError as exc:
            return JsonResponse({"ok": False, "errors": [str(exc)]}, status=400)

    def rule_engine_verify_view(self, request, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from microtech.models import MicrotechSettings

        if not self.has_change_permission(request):
            return HttpResponseForbidden("Keine Berechtigung.")

        settings_obj = MicrotechSettings.load()
        if request.method == "POST":
            mode = request.POST.get("mode", "")
            valid = {
                MicrotechSettings.EngineMode.OFF,
                MicrotechSettings.EngineMode.LIVE,
            }
            if mode in valid:
                settings_obj.rule_engine_order_mode = mode
                settings_obj.rule_engine_address_mode = mode
                settings_obj.rule_engine_customer_mode = mode
                settings_obj.save(update_fields=[
                    "rule_engine_order_mode",
                    "rule_engine_address_mode",
                    "rule_engine_customer_mode",
                ])
                messages.success(
                    request,
                    f"Regel-Engine für Bestellungen, Kunden und Anschriften auf '{mode}' gesetzt.",
                )
            else:
                messages.error(request, "Ungültiger Modus. Erlaubt sind nur 'off' und 'live'.")
            return redirect("admin:microtech_orderrule_engine_verify")

        configured_modes = {
            settings_obj.rule_engine_order_mode,
            settings_obj.rule_engine_address_mode,
            settings_obj.rule_engine_customer_mode,
        }
        context = {
            **self.admin_site.each_context(request),
            "title": "Regel-Engine ein-/ausschalten",
            "opts": self.model._meta,
            "mode": configured_modes.pop() if len(configured_modes) == 1 else "mixed",
            "overview_url": reverse("admin:microtech_orderrule_builder"),
        }
        return TemplateResponse(request, "admin/microtech/rule_engine_verify.html", context)

    def rule_builder_meta_view(self, request, **kwargs):
        if not self.has_view_permission(request):
            return JsonResponse({"ok": False, "error": "Zugriff verweigert."}, status=403)

        django_fields = get_django_field_defs()
        django_field_map = {item.path: item for item in django_fields}
        operator_defs = get_operator_defs()
        context_fields = (
            get_address_field_defs("customer.Address")
            + get_customer_field_defs()
        )
        context_field_maps = {
            context_root: {
                item.path: item
                for item in context_fields
                if item.context_root == context_root
            }
            for context_root in {item.context_root for item in context_fields}
        }
        policies_by_field = {
            item.field_path: item
            for item in (
                MicrotechOrderRuleDjangoFieldPolicy.objects
                .filter(is_active=True)
                .prefetch_related("allowed_operators")
                .order_by("priority", "id")
            )
        }
        # Dataset fields remain available through their filtered autocomplete
        # endpoint. Sending the complete Microtech catalog here makes opening
        # a rule form scale with the catalog size.
        payload = {
            "ok": True,
            "categories": [
                {
                    "id": category.id,
                    "name": category.name,
                    "is_system": category.is_system,
                }
                for category in ensure_default_rule_categories()
            ],
            "operators": [
                {
                    # Operator definitions can fall back to the built-in
                    # catalog before an older installation has seeded its DB
                    # rows.  The editor only needs the stable code here.
                    "id": None,
                    "code": item.code,
                    "name": item.name,
                    "engine_operator": item.engine_operator,
                    "hint": item.hint,
                }
                for item in operator_defs
            ],
            "django_fields": [
                {
                    "id": item.catalog_id,
                    "path": item.path,
                    "label": item.label,
                    "value_kind": item.value_kind,
                    "hint": item.hint,
                    "example": item.example,
                    "input_type": item.input_type,
                    "accepts_date_only": item.accepts_date_only,
                    "allowed_operator_codes": sorted(
                        get_allowed_operator_codes(
                            field_path=item.path,
                            django_field_id=item.catalog_id,
                            django_field_map=django_field_map,
                            operator_defs=operator_defs,
                            policies_by_field=policies_by_field,
                        )
                    ),
                    "context_root": item.context_root,
                }
                for item in django_fields
            ] + [
                {
                    "id": None,
                    "path": item.path,
                    "label": item.label,
                    "value_kind": item.value_kind,
                    "hint": item.hint,
                    "example": item.example,
                    "input_type": item.input_type,
                    "accepts_date_only": item.accepts_date_only,
                    "allowed_operator_codes": sorted(
                        get_allowed_operator_codes(
                            field_path=item.path,
                            django_field_map=context_field_maps[item.context_root],
                            operator_defs=operator_defs,
                            # Field policies are intentionally order-context
                            # specific.  Bare address paths must not inherit
                            # an unrelated order policy with the same name.
                            policies_by_field={},
                        )
                    ),
                    "context_root": item.context_root,
                }
                for item in context_fields
            ],
            "action_targets": [
                {
                    "code": item.code,
                    "label": item.label,
                    "action_type": item.action_type,
                    "dataset_source_identifiers": list(item.dataset_source_identifiers),
                    "dataset_names": list(item.dataset_names),
                    "target_value_label": item.target_value_label,
                    "target_value_help": item.target_value_help,
                }
                for item in get_rule_action_target_defs()
            ],
            "triggers": [
                {
                    "id": item.id,
                    "code": item.code,
                    "label": friendly_trigger_label(item),
                    "task_name": item.task_name,
                    "context_root": item.context_root,
                    "graphql_input_types": list(get_rule_trigger_input_types(item.task_name)),
                    "graphql_scopes": [
                        {
                            "code": scope["code"],
                            "label": scope["label"],
                            "graphql_input_types": list(scope["graphql_input_types"]),
                            "excluded_fields": list(
                                get_rule_action_excluded_fields(item.task_name, scope["code"])
                            ),
                        }
                        for scope in get_rule_action_scopes(item.task_name)
                    ],
                }
                for item in RuleTrigger.objects.filter(is_active=True).order_by("priority", "id")
            ],
            "occupied_targets": [
                {
                    "trigger_id": trigger_id,
                    "target_key": target_key,
                    **assignment,
                }
                for (trigger_id, target_key), assignments
                in effective_target_assignments().items()
                for assignment in assignments
            ],
        }
        return JsonResponse(payload)

    def rule_editor_view(self, request, object_id=None, **kwargs):
        if not self.has_view_permission(request):
            return HttpResponseRedirect(reverse("admin:index"))

        categories = ensure_default_rule_categories()
        rule = self.get_object(request, object_id) if object_id else None
        if rule is not None:
            rule_json = serialize_rule_for_edit(rule)
        else:
            requested_category = next(
                (
                    category
                    for category in categories
                    if str(category.id) == str(request.GET.get("category") or "")
                ),
                categories[0] if categories else None,
            )
            rule_json = {
                "id": None,
                "name": "",
                "priority": (
                    next_rule_priority(requested_category)
                    if requested_category is not None
                    else 100
                ),
                "is_active": True,
                "execution_phase": "before",
                "engine_enabled": True,
                "shadow_mode": False,
                "trigger_id": None,
                "category_id": requested_category.id if requested_category else None,
                "root_group": None,
                "actions": [],
            }

        context = {
            **self.admin_site.each_context(request),
            "title": "Regel bearbeiten" if rule is not None else "Neue Regel",
            "rule_json": rule_json,
            "save_url": reverse("admin:microtech_orderrule_editor_save"),
            "meta_url": reverse("admin:microtech_orderrule_builder_meta"),
            "overview_url": reverse("admin:microtech_orderrule_builder"),
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/microtech/rule_editor.html", context)

    def rule_editor_save_view(self, request, **kwargs):
        if request.method != "POST":
            return JsonResponse({"ok": False, "errors": ["Nur POST erlaubt"]}, status=405)

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "errors": ["Ungültiges JSON"]}, status=400)

        object_id = payload.get("id")
        rule = self.get_object(request, object_id) if object_id else None

        if object_id and rule is None:
            return JsonResponse({"ok": False, "errors": ["Regel nicht gefunden."]}, status=404)

        if rule is not None:
            if not self.has_change_permission(request, rule):
                return JsonResponse({"ok": False, "error": "Zugriff verweigert."}, status=403)
        else:
            if not self.has_add_permission(request):
                return JsonResponse({"ok": False, "error": "Zugriff verweigert."}, status=403)

        try:
            rule = save_rule_from_payload(payload, rule=rule)
        except EditorValidationError as exc:
            return JsonResponse({"ok": False, "errors": exc.messages}, status=400)

        return JsonResponse({
            "ok": True,
            "id": rule.id,
            "redirect": reverse("admin:microtech_orderrule_builder"),
        })

    @admin.display(description="Live-Zusammenfassung")
    def live_rule_summary(self, obj):
        # Statisches Markup ohne Interpolation; format_html ohne Argumente
        # ist seit Django 5 ein TypeError.
        return mark_safe(
            """
            <section class="rulebuilder-summary-card" id="rulebuilder-live-summary" aria-live="polite">
              <h3 class="rulebuilder-summary-title">Regel-Zusammenfassung</h3>
              <p class="rulebuilder-summary-text">
                Noch keine vollstaendige Regel. Waehle Bedingungen und Aktionen, dann erscheint hier die Klartext-Zusammenfassung.
              </p>
              <ul class="rulebuilder-summary-warnings" id="rulebuilder-summary-warnings"></ul>
            </section>
            """
        )

    fieldsets = (
        (
            "Grundregel",
            {
                "fields": (
                    "name",
                    "category",
                    "is_active",
                    "priority",
                    "condition_logic",
                    "trigger",
                    "execution_phase",
                    "engine_enabled",
                ),
                "description": (
                    "Prioritaet steuert die Reihenfolge. Alle passenden aktiven Regeln werden nacheinander ausgeführt."
                ),
            },
        ),
        (
            "Wann greift die Regel?",
            {
                "fields": (),
                "description": (
                    "Definiere die Ausloeser in Fachsprache. "
                    "Ohne aktive Bedingungen gilt die Regel als globaler Fallback."
                ),
            },
        ),
        (
            "Was soll in Microtech passieren?",
            {
                "fields": (),
                "description": (
                    "Waehle fachliche Aktionen. Das technische Ziel-Dataset wird im Hintergrund gefuehrt."
                ),
            },
        ),
        (
            "Klartext-Vorschau",
            {
                "fields": ("live_rule_summary",),
                "description": "Die Vorschau aktualisiert sich waehrend der Bearbeitung.",
            },
        ),
    )


@admin.register(MicrotechOrderRuleDjangoField)
class MicrotechOrderRuleDjangoFieldAdmin(BaseAdmin):
    list_display = ("priority", "label", "field_path", "value_kind", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("field_path", "label", "hint", "example")
    list_filter = ("is_active", "value_kind")
    ordering = ("priority", "field_path", "id")
    fieldsets = (
        (
            "Django Feldkatalog",
            {
                "fields": ("is_active", "priority", "field_path", "label", "value_kind", "hint", "example"),
            },
        ),
    )


@admin.register(MicrotechOrderRuleOperator)
class MicrotechOrderRuleOperatorAdmin(BaseAdmin):
    list_display = ("priority", "name", "code", "engine_operator", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("code", "name", "hint")
    list_filter = ("is_active", "engine_operator")
    ordering = ("priority", "id")
    fieldsets = (
        (
            "Operator",
            {
                "fields": ("is_active", "priority", "code", "name", "engine_operator", "hint"),
            },
        ),
    )



@admin.register(MicrotechOrderRuleDjangoFieldPolicy)
class MicrotechOrderRuleDjangoFieldPolicyAdmin(BaseAdmin):
    list_display = ("priority", "field_path", "label_override", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("field_path", "label_override", "hint")
    list_filter = ("is_active",)
    ordering = ("priority", "field_path", "id")
    filter_horizontal = ("allowed_operators",)
    fieldsets = (
        (
            "Django Bedingungsfeld Policy",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "field_path",
                    "label_override",
                    "hint",
                    "allowed_operators",
                ),
            },
        ),
    )


@admin.register(MicrotechDatasetCatalog)
class MicrotechDatasetCatalogAdmin(BaseAdmin):
    list_display = ("priority", "name", "description", "code", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("code", "name", "description", "source_identifier")
    list_filter = ("is_active",)
    ordering = ("priority", "name", "id")
    fieldsets = (
        (
            "Dataset",
            {
                "fields": ("is_active", "priority", "code", "name", "description", "source_identifier"),
            },
        ),
    )


@admin.register(MicrotechDatasetField)
class MicrotechDatasetFieldAdmin(BaseAdmin):
    list_display = (
        "priority",
        "dataset",
        "field_name",
        "field_type",
        "is_calc_field",
        "can_access",
        "is_active",
        "updated_at",
    )
    list_editable = ("is_active",)
    search_fields = ("field_name", "label", "field_type", "dataset__name", "dataset__description")
    list_filter = ("is_active", "is_calc_field", "can_access", "field_type", "dataset")

    def get_search_results(self, request, queryset, search_term):
        # Support "Dataset.Field" search (e.g. "Vorgang.Such")
        if "." in search_term:
            parts = search_term.split(".", 1)
            dataset_term = parts[0].strip()
            field_term = parts[1].strip()
            qs = queryset.filter(dataset__name__icontains=dataset_term)
            if field_term:
                qs = qs.filter(
                    models.Q(field_name__icontains=field_term)
                    | models.Q(label__icontains=field_term)
                )
            return qs, False
        return super().get_search_results(request, queryset, search_term)
    ordering = ("dataset__priority", "dataset__name", "priority", "field_name", "id")
    autocomplete_fields = ("dataset",)
    fieldsets = (
        (
            "Dataset Feld",
            {
                "fields": (
                    "is_active",
                    "priority",
                    "dataset",
                    "field_name",
                    "label",
                    "field_type",
                    "is_calc_field",
                    "can_access",
                ),
            },
        ),
    )


@admin.register(MicrotechOrderRuleConditionGroup)
class MicrotechOrderRuleConditionGroupAdmin(BaseAdmin):
    class GroupConditionInline(BaseStackedInline):
        model = MicrotechOrderRuleCondition
        fields = (
            "is_active",
            "priority",
            "django_field_path",
            "operator_code",
            "expected_value",
            "expected_value_2",
        )
        extra = 0
        verbose_name = "Bedingung"
        verbose_name_plural = "Bedingungen dieser Gruppe"

    list_display = ("id", "rule", "logic", "parent", "is_active", "priority", "updated_at")
    list_filter = ("logic", "is_active", "rule")
    search_fields = ("rule__name",)
    ordering = ("rule", "priority", "id")
    autocomplete_fields = ("rule", "parent")
    inlines = (GroupConditionInline,)
    fieldsets = (
        (
            "Bedingungsgruppe",
            {
                "fields": ("rule", "parent", "logic", "is_active", "priority"),
                "description": (
                    "Verschachtelbare UND/ODER-Gruppe. 'parent' leer = Wurzelgruppe der Regel. "
                    "Bedingungen dieser Gruppe unten. django_field_path/operator_code als Klartext "
                    "(z. B. 'billing_address__country_code', Operator 'eq'/'between'/'before')."
                ),
            },
        ),
    )


@admin.register(RuleTrigger)
class RuleTriggerAdmin(BaseAdmin):
    list_display = ("priority", "code", "label", "task_name", "context_root", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("code", "label", "task_name", "context_root")
    list_filter = ("is_active", "task_name")
    ordering = ("priority", "id")
    fieldsets = (
        (
            "Trigger",
            {
                "fields": ("is_active", "priority", "code", "label", "task_name", "context_root"),
                "description": (
                    "Ein Geschaefts-Event, das an einen Celery-Task gebunden ist. "
                    "context_root (app_label.Model) definiert den Variablen-Namensraum der Regeln."
                ),
            },
        ),
    )


@admin.register(RuleConstant)
class RuleConstantAdmin(BaseAdmin):
    list_display = ("key", "kind", "value_short", "updated_at")
    search_fields = ("key", "value")
    list_filter = ("kind",)
    ordering = ("key",)
    fieldsets = (
        (
            "Konstante",
            {
                "fields": ("key", "kind", "value"),
                "description": "Benannte Konstante fuer Resolver und Bedingungen (z. B. EU-Laenderliste).",
            },
        ),
    )

    @admin.display(description="Wert")
    def value_short(self, obj):
        value = (obj.value or "").strip()
        return f"{value[:80]}..." if len(value) > 80 else value
