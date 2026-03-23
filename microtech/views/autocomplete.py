from __future__ import annotations

import re

from django.db.models import Q
from django.http import HttpResponseForbidden

from microtech.models import (
    MicrotechDatasetField,
    MicrotechOrderRuleDjangoField,
    MicrotechOrderRuleOperator,
)
from microtech.rule_builder import (
    filter_dataset_field_queryset_for_action_target,
    get_allowed_operator_codes,
    sync_django_field_catalog,
)
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
        action_target = str(self.request.GET.get("action_target") or "").strip()
        queryset = (
            MicrotechDatasetField.objects
            .filter(is_active=True, dataset__is_active=True)
            .select_related("dataset")
            .order_by("dataset__priority", "dataset__name", "priority", "field_name", "id")
        )
        queryset = filter_dataset_field_queryset_for_action_target(queryset, action_target=action_target)
        if not query:
            return queryset
        return self._apply_search(queryset, query=query)

    @staticmethod
    def _build_general_search_predicate(term: str) -> Q:
        return (
            Q(field_name__icontains=term)
            | Q(label__icontains=term)
            | Q(field_type__icontains=term)
            | Q(dataset__name__icontains=term)
            | Q(dataset__description__icontains=term)
            | Q(dataset__source_identifier__icontains=term)
        )

    @staticmethod
    def _build_dataset_predicate(term: str) -> Q:
        return (
            Q(dataset__name__icontains=term)
            | Q(dataset__description__icontains=term)
            | Q(dataset__source_identifier__icontains=term)
        )

    @staticmethod
    def _build_field_predicate(term: str) -> Q:
        return (
            Q(field_name__icontains=term)
            | Q(label__icontains=term)
            | Q(field_type__icontains=term)
        )

    def _apply_search(self, queryset, *, query: str):
        normalized_query = " ".join(query.split())
        if not normalized_query:
            return queryset

        combined_queryset = queryset.filter(self._build_general_search_predicate(normalized_query))

        token_terms = [
            token
            for token in re.split(r"[\s\-.]+", normalized_query)
            if token
        ]
        if len(token_terms) > 1:
            token_queryset = queryset
            for token in token_terms:
                token_queryset = token_queryset.filter(self._build_general_search_predicate(token))
            combined_queryset = combined_queryset | token_queryset

        if "." in normalized_query:
            dataset_term, field_term = normalized_query.split(".", 1)
            dataset_term = dataset_term.strip()
            field_term = field_term.strip()
            if dataset_term:
                dot_queryset = queryset.filter(self._build_dataset_predicate(dataset_term))
                for token in [token for token in re.split(r"[\s\-]+", field_term) if token]:
                    dot_queryset = dot_queryset.filter(self._build_field_predicate(token))
                combined_queryset = combined_queryset | dot_queryset

        return combined_queryset.distinct()


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
        if not django_field_id.isdigit():
            return queryset.none()
        allowed_codes = get_allowed_operator_codes(django_field_id=int(django_field_id))
        queryset = queryset.filter(code__in=allowed_codes)

        if not query:
            return queryset
        return queryset.filter(
            Q(code__icontains=query)
            | Q(name__icontains=query)
            | Q(hint__icontains=query)
        )
