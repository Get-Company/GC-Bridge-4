from __future__ import annotations

from django.db.models import Q
from django.http import HttpResponseForbidden

from microtech.models import (
    MicrotechDatasetField,
    MicrotechOrderRuleDjangoField,
    MicrotechOrderRuleOperator,
)
from microtech.rule_builder import sync_django_field_catalog
from unfold.views import BaseAutocompleteView


class MicrotechOrderRuleDjangoFieldAutocompleteView(BaseAutocompleteView):
    def dispatch(self, request, *args, **kwargs):
        model_admin = kwargs.get("model_admin")
        if model_admin and not model_admin.has_view_permission(request):
            return HttpResponseForbidden("Zugriff verweigert.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        sync_django_field_catalog()
        query = str(self.request.GET.get("term") or "").strip()
        queryset = (
            MicrotechOrderRuleDjangoField.objects
            .filter(is_active=True)
            .order_by("priority", "label", "id")
        )
        if not query:
            return queryset
        return queryset.filter(
            Q(field_path__icontains=query)
            | Q(label__icontains=query)
            | Q(hint__icontains=query)
            | Q(example__icontains=query)
        )


class MicrotechDatasetFieldAutocompleteView(BaseAutocompleteView):
    def dispatch(self, request, *args, **kwargs):
        model_admin = kwargs.get("model_admin")
        if model_admin and not model_admin.has_view_permission(request):
            return HttpResponseForbidden("Zugriff verweigert.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        query = str(self.request.GET.get("term") or "").strip()
        queryset = (
            MicrotechDatasetField.objects
            .filter(is_active=True, dataset__is_active=True)
            .select_related("dataset")
            .order_by("dataset__priority", "dataset__name", "priority", "field_name", "id")
        )
        if not query:
            return queryset
        return queryset.filter(
            Q(field_name__icontains=query)
            | Q(label__icontains=query)
            | Q(field_type__icontains=query)
            | Q(dataset__name__icontains=query)
            | Q(dataset__description__icontains=query)
        )


class MicrotechOrderRuleOperatorAutocompleteView(BaseAutocompleteView):
    def dispatch(self, request, *args, **kwargs):
        model_admin = kwargs.get("model_admin")
        if model_admin and not model_admin.has_view_permission(request):
            return HttpResponseForbidden("Zugriff verweigert.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        query = str(self.request.GET.get("term") or "").strip()
        django_field_id = str(self.request.GET.get("django_field_id") or "").strip()
        queryset = (
            MicrotechOrderRuleOperator.objects
            .filter(is_active=True)
            .order_by("priority", "id")
        )

        if not query:
            return queryset
        return queryset.filter(
            Q(code__icontains=query)
            | Q(name__icontains=query)
            | Q(hint__icontains=query)
        )
