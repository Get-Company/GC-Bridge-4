(function () {
  "use strict";

  let RULE_META = null;

  function getJQuery() {
    return window.django && window.django.jQuery ? window.django.jQuery : null;
  }

  function initEnhancedSelects(root) {
    const $ = getJQuery();
    if (!$ || !root) return;

    const $root = $(root);
    const customAutocomplete = $root.is(".unfold-admin-autocomplete") && !$root.is(".admin-autocomplete")
      ? $root
      : $root.find(".unfold-admin-autocomplete").not(".admin-autocomplete");
    const modelAutocomplete = $root.is(".admin-autocomplete")
      ? $root
      : $root.find(".admin-autocomplete");

    if (typeof $.fn.djangoCustomSelect2 === "function") {
      customAutocomplete.djangoCustomSelect2();
    }

    if (typeof $.fn.djangoAdminSelect2 === "function") {
      modelAutocomplete
        .not("[name*=__prefix__]")
        .filter(function () {
          return !$(this).hasClass("select2-hidden-accessible");
        })
        .djangoAdminSelect2();
    }
  }

  function buildMetaUrl() {
    const path = window.location.pathname;
    const marker = "/microtechorderrule/";
    const idx = path.indexOf(marker);
    if (idx < 0) return "";
    const base = path.slice(0, idx + marker.length);
    return `${base}rule-builder-meta/`;
  }

  function operatorsByValue() {
    const map = {};
    if (!RULE_META || !Array.isArray(RULE_META.operators)) return map;
    RULE_META.operators.forEach((op) => {
      if (!op) return;
      if (op.code) map[op.code] = op;
      if (op.id) map[String(op.id)] = op;
    });
    return map;
  }

  function djangoFieldByValue(value) {
    if (!RULE_META || !Array.isArray(RULE_META.django_fields)) return null;
    const needle = String(value || "");
    return RULE_META.django_fields.find((item) => String(item.id || item.path) === needle || item.path === needle) || null;
  }

  function datasetFieldById(idValue) {
    if (!RULE_META || !Array.isArray(RULE_META.dataset_fields)) return null;
    const id = String(idValue || "");
    return RULE_META.dataset_fields.find((item) => String(item.id) === id) || null;
  }

  const VALUELESS_OPERATORS = ["is_empty", "is_not_empty"];

  function operatorMatchesField(operatorValue, fieldDef) {
    const operator = operatorsByValue()[String(operatorValue || "")] || null;
    return !!(operator && fieldDef);
  }

  function initOperatorAutocomplete(operatorSelect, djangoFieldId, fieldDef) {
    const $ = getJQuery();
    if (!$ || !operatorSelect) return;

    const $select = $(operatorSelect);
    const baseUrl = operatorSelect.dataset.operatorAutocompleteUrl || "";
    if (!baseUrl) return;
    const url = baseUrl;

    if (operatorSelect.dataset.operatorAutocompleteUrlActive === url && $select.hasClass("select2-hidden-accessible")) {
      return;
    }

    operatorSelect.dataset.operatorAutocompleteUrlActive = url;

    if (!operatorMatchesField(operatorSelect.value, fieldDef)) {
      operatorSelect.value = "";
      $select.find("option").not('[value=""]').remove();
    }

    if ($select.hasClass("select2-hidden-accessible")) {
      $select.select2("destroy");
    }

    $select.select2({
      theme: "admin-autocomplete",
      width: "100%",
      allowClear: true,
      placeholder: operatorSelect.dataset.placeholder || "",
      ajax: {
        url,
        dataType: "json",
        delay: 250,
        cache: true,
        data: function (params) {
          return {
            term: params.term,
            page: params.page,
            django_field_id: djangoFieldId || "",
          };
        },
        processResults: function (data) {
          return data || { results: [], pagination: { more: false } };
        },
      },
    });
  }

  function updateExpectedValueVisibility(operatorSelect, expectedInput) {
    if (!operatorSelect || !expectedInput) return;
    const operator = operatorsByValue()[String(operatorSelect.value || "")] || null;
    const hide = operator ? VALUELESS_OPERATORS.includes(operator.code) : false;
    expectedInput.style.display = hide ? "none" : "";
    if (hide) expectedInput.value = "";
  }

  function updateConditionRow(row) {
    const pathInput = row.querySelector("select[name$='-django_field'], input[name$='-django_field']");
    const operatorSelect = row.querySelector("select[name$='-operator']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (!pathInput || !operatorSelect || !expectedInput || !RULE_META) return;

    const fieldDef = djangoFieldByValue(pathInput.value);
    initOperatorAutocomplete(operatorSelect, pathInput.value, fieldDef);

    if (!fieldDef) {
      expectedInput.placeholder = "";
      expectedInput.title = "";
      updateExpectedValueVisibility(operatorSelect, expectedInput);
      return;
    }

    expectedInput.placeholder = fieldDef.example || "";
    expectedInput.title = fieldDef.hint || "";
    updateExpectedValueVisibility(operatorSelect, expectedInput);
  }

  function toggleActionTypeFields(row) {
    const actionTypeSelect = row.querySelector("select[name$='-action_type']");
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    const targetInput = row.querySelector("input[name$='-target_value']");
    if (!actionTypeSelect || !datasetFieldSelect || !targetInput) return;

    const isCreatePosition = actionTypeSelect.value === "create_extra_position";

    datasetFieldSelect.disabled = isCreatePosition;

    if (isCreatePosition) {
      targetInput.placeholder = "ERP-Nr fuer Zusatzposition, z. B. P";
      targetInput.title = "Wird fuer Positionen.Add(1, Einheit, ERP-Nr) verwendet.";
      return;
    }

    const fieldDef = datasetFieldById(datasetFieldSelect.value);
    if (fieldDef) {
      targetInput.placeholder = fieldDef.field_type || "";
      targetInput.title = fieldDef.label || "";
    } else {
      targetInput.placeholder = "";
      targetInput.title = "";
    }
  }

  function updateActionRow(row) {
    const actionTypeSelect = row.querySelector("select[name$='-action_type']");
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    if (!actionTypeSelect || !datasetFieldSelect || !RULE_META) return;
    toggleActionTypeFields(row);
  }

  function bindRow(row) {
    if (!row || row.dataset.ruleBuilderBound === "1") {
      return;
    }
    row.dataset.ruleBuilderBound = "1";
    initEnhancedSelects(row);

    const pathInput = row.querySelector("select[name$='-django_field'], input[name$='-django_field']");
    const datasetSelect = row.querySelector("select[name$='-dataset']");
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    const actionTypeSelect = row.querySelector("select[name$='-action_type']");

    if (pathInput) {
      pathInput.addEventListener("change", () => updateConditionRow(row));
      if (pathInput.tagName === "INPUT") {
        pathInput.addEventListener("input", () => updateConditionRow(row));
      }
      updateConditionRow(row);
    }

    const operatorSelect = row.querySelector("select[name$='-operator']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (operatorSelect && expectedInput) {
      operatorSelect.addEventListener("change", () => updateExpectedValueVisibility(operatorSelect, expectedInput));
    }

    if (datasetSelect) {
      datasetSelect.addEventListener("change", () => updateActionRow(row));
      updateActionRow(row);
    }

    if (datasetFieldSelect) {
      datasetFieldSelect.addEventListener("change", () => updateActionRow(row));
      updateActionRow(row);
    }

    if (actionTypeSelect) {
      actionTypeSelect.addEventListener("change", () => updateActionRow(row));
      updateActionRow(row);
    }
  }

  function bindAllRows() {
    document.querySelectorAll("tr.form-row, .inline-related").forEach(bindRow);
  }

  function bindFormsetAddedEvents() {
    document.addEventListener("formset:added", (event) => {
      const target = event && event.target;
      if (target) {
        bindRow(target);
      }
    });
  }

  function observeInlineRows() {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
          if (!(node instanceof HTMLElement)) return;

          if (node.matches("tr.form-row, .inline-related")) {
            bindRow(node);
          }
          node.querySelectorAll("tr.form-row, .inline-related").forEach(bindRow);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  async function loadMeta() {
    const url = buildMetaUrl();
    if (!url) return;
    try {
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) return;
      const payload = await response.json();
      if (!payload || payload.ok !== true) return;
      RULE_META = payload;
    } catch (_error) {
      // Keep UI usable without metadata endpoint.
    }
  }

  async function init() {
    await loadMeta();
    initEnhancedSelects(document.body);
    bindAllRows();
    bindFormsetAddedEvents();
    observeInlineRows();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
