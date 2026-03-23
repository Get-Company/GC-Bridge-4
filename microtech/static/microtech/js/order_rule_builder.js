(function () {
  "use strict";

  let RULE_META = null;

  const VALUELESS_OPERATORS = ["is_empty", "is_not_empty"];
  const ACTION_TARGET_CREATE_POSITION = "create_extra_position";
  const ACTION_TARGET_VORGANG = "set_vorgang_field";
  const ACTION_TARGET_POSITION = "set_vorgang_position_field";

  function getJQuery() {
    return window.django && window.django.jQuery ? window.django.jQuery : null;
  }

  function buildRuleUrl(endpoint) {
    const path = window.location.pathname;
    const marker = "/microtechorderrule/";
    const idx = path.indexOf(marker);
    if (idx < 0) return "";
    const base = path.slice(0, idx + marker.length);
    return `${base}${endpoint}/`;
  }

  function buildMetaUrl() {
    return buildRuleUrl("rule-builder-meta");
  }

  function buildOperatorAutocompleteUrl() {
    return buildRuleUrl("operator-autocomplete");
  }

  function buildDatasetFieldAutocompleteUrl() {
    return buildRuleUrl("dataset-field-autocomplete");
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

  function getDatasetFieldDisplay(datasetFieldDef) {
    if (!datasetFieldDef) return "";
    const datasetDef = datasetById(datasetFieldDef.dataset_id);
    const datasetName = datasetDef ? datasetDef.name : "Microtech";
    const base = `${datasetName}.${datasetFieldDef.field_name || ""}`;
    const label = String(datasetFieldDef.label || "").trim();
    return label ? `${base} - ${label}` : base;
  }

  function datasetById(idValue) {
    if (!RULE_META || !Array.isArray(RULE_META.datasets)) return null;
    const id = String(idValue || "");
    return RULE_META.datasets.find((item) => String(item.id) === id) || null;
  }

  function isRulebuilderOperator(element) {
    return !!(element && (element.classList.contains("rulebuilder-operator-autocomplete") || /-operator$/.test(element.name || "")));
  }

  function isRulebuilderDatasetField(element) {
    return !!(element && (element.classList.contains("rulebuilder-dataset-field-autocomplete") || /-dataset_field$/.test(element.name || "")));
  }

  function getConditionFieldIdForOperator(element) {
    const row = element.closest("tr.form-row, .inline-related");
    if (!row) return "";
    const fieldInput = row.querySelector("select[name$='-django_field'], input[name$='-django_field']");
    return fieldInput ? String(fieldInput.value || "") : "";
  }

  function normalizeActionTarget(value) {
    const text = String(value || "").trim().toLowerCase();
    if (!text) return "";
    if (text === ACTION_TARGET_CREATE_POSITION) return ACTION_TARGET_CREATE_POSITION;
    if (text === ACTION_TARGET_POSITION || text.includes("position")) return ACTION_TARGET_POSITION;
    if (text === ACTION_TARGET_VORGANG || text.includes("vorgang")) return ACTION_TARGET_VORGANG;
    if (text === "set_field") return ACTION_TARGET_VORGANG;
    return text;
  }

  function getActionTargetValue(row) {
    if (!row) return "";
    const uiActionInput = row.querySelector("select[name$='-ui_action'], input[name$='-ui_action']");
    if (uiActionInput) return normalizeActionTarget(uiActionInput.value);

    const actionTypeInput = row.querySelector("select[name$='-action_type'], input[name$='-action_type']");
    if (actionTypeInput) return normalizeActionTarget(actionTypeInput.value);

    return "";
  }

  function getActionLabel(actionTarget) {
    if (actionTarget === ACTION_TARGET_CREATE_POSITION) return "Zusatzposition anlegen";
    if (actionTarget === ACTION_TARGET_POSITION) return "Feld der Zusatzposition setzen";
    if (actionTarget === ACTION_TARGET_VORGANG) return "Vorgangsfeld setzen";
    return "Aktion";
  }

  function getConditionOperatorLabel(value) {
    const operator = operatorsByValue()[String(value || "")] || null;
    if (!operator) return "";
    return operator.name || operator.code || "";
  }

  function isRowDeleted(row) {
    if (!row) return false;
    const deleteInput = row.querySelector("input[name$='-DELETE']");
    return !!(deleteInput && deleteInput.checked);
  }

  function isRowActive(row) {
    if (!row || isRowDeleted(row)) return false;
    const activeInput = row.querySelector("input[name$='-is_active']");
    return !activeInput || !!activeInput.checked;
  }

  function collectInlineRows(selector) {
    return Array.from(document.querySelectorAll(".inline-related")).filter((row) => {
      return row.querySelector(selector) && isRowActive(row);
    });
  }

  function initRulebuilderAutocomplete(element, options) {
    const $ = getJQuery();
    if (!$ || !element) return;

    const $element = $(element);
    if ($element.hasClass("select2-hidden-accessible")) {
      $element.select2("destroy");
    }

    $element.select2({
      width: "style",
      ajax: {
        url: options.url,
        data: options.data,
      },
    });
  }

  function initOperatorAutocomplete(operatorSelect) {
    if (!operatorSelect) return;
    initRulebuilderAutocomplete(operatorSelect, {
      url: operatorSelect.dataset.operatorAutocompleteUrl || buildOperatorAutocompleteUrl(),
      data: (params) => {
        return {
          term: params.term,
          page: params.page,
          app_label: operatorSelect.dataset.appLabel,
          model_name: operatorSelect.dataset.modelName,
          field_name: operatorSelect.dataset.fieldName,
          django_field_id: getConditionFieldIdForOperator(operatorSelect),
        };
      },
    });
  }

  function initDatasetFieldAutocomplete(datasetFieldSelect) {
    if (!datasetFieldSelect) return;
    initRulebuilderAutocomplete(datasetFieldSelect, {
      url: datasetFieldSelect.dataset.datasetFieldAutocompleteUrl || buildDatasetFieldAutocompleteUrl(),
      data: (params) => {
        const row = datasetFieldSelect.closest("tr.form-row, .inline-related");
        return {
          term: params.term,
          page: params.page,
          app_label: datasetFieldSelect.dataset.appLabel,
          model_name: datasetFieldSelect.dataset.modelName,
          field_name: datasetFieldSelect.dataset.fieldName,
          action_target: getActionTargetValue(row),
        };
      },
    });
  }

  function patchAdminAutocomplete() {
    const $ = getJQuery();
    if (!$ || typeof $.fn.djangoAdminSelect2 !== "function" || $.fn.djangoAdminSelect2.__ruleBuilderPatched) return;

    const original = $.fn.djangoAdminSelect2;

    $.fn.djangoAdminSelect2 = function () {
      const $elements = $(this);
      const $customElements = $elements.filter(function () {
        return isRulebuilderOperator(this) || isRulebuilderDatasetField(this);
      });
      const $defaultElements = $elements.not($customElements);

      if ($defaultElements.length) {
        original.call($defaultElements);
      }

      $customElements.each(function (_index, element) {
        if (element.id && element.id.indexOf("__prefix__") >= 0) return;
        if (isRulebuilderOperator(element)) {
          initOperatorAutocomplete(element);
          return;
        }
        if (isRulebuilderDatasetField(element)) {
          initDatasetFieldAutocomplete(element);
        }
      });

      return this;
    };

    $.fn.djangoAdminSelect2.__ruleBuilderPatched = true;
  }

  function ensureBoolSelect(expectedInput) {
    if (!expectedInput) return null;
    const container = expectedInput.parentElement;
    if (!container) return null;

    let select = container.querySelector(".rulebuilder-bool-select");
    if (select) return select;

    select = document.createElement("select");
    select.className = "rulebuilder-bool-select";
    select.innerHTML = [
      '<option value="">Bitte waehlen...</option>',
      '<option value="true">Ja</option>',
      '<option value="false">Nein</option>',
    ].join("");
    select.style.display = "none";
    expectedInput.insertAdjacentElement("afterend", select);
    select.addEventListener("change", () => {
      expectedInput.value = select.value;
      expectedInput.dispatchEvent(new Event("input", { bubbles: true }));
      refreshRuleSummary();
    });
    return select;
  }

  function applyConditionInputType(row, fieldDef) {
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (!expectedInput) return;

    const valueKind = fieldDef ? String(fieldDef.value_kind || "string") : "string";
    const inputType = fieldDef ? String(fieldDef.input_type || "") : "";
    const boolSelect = ensureBoolSelect(expectedInput);
    expectedInput.dataset.valueKind = valueKind;
    expectedInput.dataset.inputType = inputType;

    expectedInput.classList.remove("rulebuilder-hidden-input");
    expectedInput.type = "text";
    expectedInput.step = "";
    expectedInput.inputMode = "";

    if (boolSelect) {
      boolSelect.style.display = "none";
    }

    if (valueKind === "bool") {
      expectedInput.classList.add("rulebuilder-hidden-input");
      if (boolSelect) {
        boolSelect.style.display = "";
        boolSelect.value = expectedInput.value || "";
      }
      return;
    }

    let resolvedInputType = inputType || valueKind;
    if (
      fieldDef
      && fieldDef.accepts_date_only
      && resolvedInputType === "date"
      && expectedInput.value
      && (expectedInput.value.includes("T") || expectedInput.value.includes(" "))
    ) {
      resolvedInputType = "datetime";
    }

    if (resolvedInputType === "int") {
      expectedInput.type = "number";
      expectedInput.step = "1";
      expectedInput.inputMode = "numeric";
      return;
    }

    if (resolvedInputType === "decimal") {
      expectedInput.type = "number";
      expectedInput.step = "0.01";
      expectedInput.inputMode = "decimal";
      return;
    }

    if (resolvedInputType === "date") {
      expectedInput.type = "date";
      return;
    }

    if (resolvedInputType === "datetime") {
      expectedInput.type = "datetime-local";
    }
  }

  function updateExpectedValueVisibility(operatorSelect, expectedInput) {
    if (!operatorSelect || !expectedInput) return;
    const operator = operatorsByValue()[String(operatorSelect.value || "")] || null;
    const boolSelect = ensureBoolSelect(expectedInput);
    const hide = operator ? VALUELESS_OPERATORS.includes(operator.code) : false;

    expectedInput.style.display = hide ? "none" : "";
    if (boolSelect) {
      boolSelect.style.display = hide ? "none" : (expectedInput.classList.contains("rulebuilder-hidden-input") ? "" : "none");
    }

    if (hide) {
      expectedInput.value = "";
      if (boolSelect) {
        boolSelect.value = "";
      }
    }
  }

  function updateConditionRow(row) {
    const pathInput = row.querySelector("select[name$='-django_field'], input[name$='-django_field']");
    const operatorSelect = row.querySelector("select[name$='-operator']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (!pathInput || !operatorSelect || !expectedInput || !RULE_META) return;

    const fieldDef = djangoFieldByValue(pathInput.value);
    const currentFieldId = String(pathInput.value || "");

    if (row.dataset.ruleBuilderFieldId !== currentFieldId) {
      row.dataset.ruleBuilderFieldId = currentFieldId;
      operatorSelect.value = "";
      const $ = getJQuery();
      if ($) {
        $(operatorSelect).find("option").not('[value=""]').remove();
      }
    }

    initOperatorAutocomplete(operatorSelect);
    applyConditionInputType(row, fieldDef);

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

  function updateActionContextPreview(row, actionTarget, datasetFieldDef) {
    const previewNode = row.querySelector(".field-action_context_preview .readonly");
    if (!previewNode) return;

    if (actionTarget === ACTION_TARGET_CREATE_POSITION) {
      previewNode.textContent = "Legt eine Zusatzposition an. Zielwert = ERP-Nr.";
      return;
    }

    if (!datasetFieldDef) {
      previewNode.textContent = actionTarget === ACTION_TARGET_POSITION
        ? "Ziel: Zusatzposition. Waehle ein passendes Feld."
        : "Ziel: Vorgang. Waehle ein passendes Feld.";
      return;
    }

    previewNode.textContent = getDatasetFieldDisplay(datasetFieldDef);
  }

  function updateActionRow(row) {
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    const targetInput = row.querySelector("input[name$='-target_value']");
    if (!datasetFieldSelect || !targetInput) return;

    const actionTarget = getActionTargetValue(row);
    const datasetFieldDef = datasetFieldById(datasetFieldSelect.value);

    if (row.dataset.lastActionTarget !== actionTarget) {
      const hadPreviousTarget = Object.prototype.hasOwnProperty.call(row.dataset, "lastActionTarget");
      row.dataset.lastActionTarget = actionTarget;
      if (hadPreviousTarget && datasetFieldSelect.value) {
        datasetFieldSelect.value = "";
        const $ = getJQuery();
        if ($) {
          $(datasetFieldSelect).find("option").not('[value=""]').remove();
        }
      }
    }

    if (actionTarget === ACTION_TARGET_CREATE_POSITION) {
      datasetFieldSelect.disabled = true;
      targetInput.placeholder = "ERP-Nr fuer Zusatzposition, z. B. P";
      targetInput.title = "Legt eine neue Zusatzposition in Microtech an.";
      updateActionContextPreview(row, actionTarget, null);
      return;
    }

    datasetFieldSelect.disabled = false;
    initDatasetFieldAutocomplete(datasetFieldSelect);
    updateActionContextPreview(row, actionTarget, datasetFieldDef);

    if (datasetFieldDef) {
      const datasetLabel = getDatasetFieldDisplay(datasetFieldDef);
      targetInput.placeholder = datasetFieldDef.field_type || "Zielwert";
      targetInput.title = datasetLabel;
      return;
    }

    targetInput.placeholder = actionTarget === ACTION_TARGET_POSITION
      ? "Wert fuer Zusatzpositionsfeld"
      : "Wert fuer Vorgangsfeld";
    targetInput.title = "";
  }

  function getConditionSummary(row) {
    const fieldInput = row.querySelector("select[name$='-django_field'], input[name$='-django_field']");
    const operatorInput = row.querySelector("select[name$='-operator']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (!fieldInput || !operatorInput || !expectedInput) return "";
    if (!fieldInput.value || !operatorInput.value) return "";

    const fieldDef = djangoFieldByValue(fieldInput.value);
    const fieldLabel = fieldDef ? (fieldDef.label || fieldDef.path) : "Feld";
    const operatorLabel = getConditionOperatorLabel(operatorInput.value);
    const operator = operatorsByValue()[String(operatorInput.value || "")] || null;
    const expectedValue = String(expectedInput.value || "").trim();

    if (operator && VALUELESS_OPERATORS.includes(operator.code)) {
      return `${fieldLabel} ${operatorLabel}`;
    }

    if (!expectedValue) return "";
    return `${fieldLabel} ${operatorLabel} ${expectedValue}`;
  }

  function getActionSummary(row) {
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    const targetInput = row.querySelector("input[name$='-target_value']");
    if (!datasetFieldSelect || !targetInput) return "";

    const actionTarget = getActionTargetValue(row);
    const actionLabel = getActionLabel(actionTarget);
    const targetValue = String(targetInput.value || "").trim();

    if (actionTarget === ACTION_TARGET_CREATE_POSITION) {
      if (!targetValue) return "";
      return `${actionLabel}: ${targetValue}`;
    }

    const datasetFieldDef = datasetFieldById(datasetFieldSelect.value);
    if (!datasetFieldDef || !targetValue) return "";
    return `${actionLabel}: ${getDatasetFieldDisplay(datasetFieldDef)} = ${targetValue}`;
  }

  function collectSummaryWarnings() {
    const warnings = [];
    const actionRows = collectInlineRows("select[name$='-dataset_field'], input[name$='-dataset_field']");
    const hasCreatePosition = actionRows.some((row) => getActionTargetValue(row) === ACTION_TARGET_CREATE_POSITION);
    const needsPosition = actionRows.some((row) => getActionTargetValue(row) === ACTION_TARGET_POSITION);

    if (needsPosition && !hasCreatePosition) {
      warnings.push("Es wird ein Feld der Zusatzposition gesetzt, aber keine Zusatzposition angelegt.");
    }

    return warnings;
  }

  function refreshRuleSummary() {
    const summaryRoot = document.getElementById("rulebuilder-live-summary");
    if (!summaryRoot) return;

    const summaryText = summaryRoot.querySelector(".rulebuilder-summary-text");
    const summaryWarnings = summaryRoot.querySelector(".rulebuilder-summary-warnings");
    if (!summaryText || !summaryWarnings) return;

    const conditionRows = collectInlineRows("select[name$='-django_field'], input[name$='-django_field']");
    const actionRows = collectInlineRows("select[name$='-dataset_field'], input[name$='-dataset_field']");
    const logicInput = document.querySelector("#id_condition_logic");

    const conditions = conditionRows
      .map(getConditionSummary)
      .filter(Boolean);
    const actions = actionRows
      .map(getActionSummary)
      .filter(Boolean);

    let text = "Noch keine vollstaendige Regel.";
    if (conditions.length || actions.length) {
      const logicText = logicInput && logicInput.value === "any" ? " oder " : " und ";
      const whenText = conditions.length ? `Wenn ${conditions.join(logicText)}` : "Wenn die Regel aktiv ist";
      const thenText = actions.length ? `, dann ${actions.join(", ")}` : ", dann noch keine Aktion.";
      text = `${whenText}${thenText}`;
    }

    summaryText.textContent = text;

    const warnings = collectSummaryWarnings();
    summaryWarnings.innerHTML = "";
    warnings.forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning;
      summaryWarnings.appendChild(item);
    });
  }

  function bindSummaryRefresh(row) {
    row.querySelectorAll("input, select, textarea").forEach((element) => {
      element.addEventListener("change", refreshRuleSummary);
      element.addEventListener("input", refreshRuleSummary);
    });
  }

  function bindRow(row) {
    if (!row || row.dataset.ruleBuilderBound === "1") {
      return;
    }
    row.dataset.ruleBuilderBound = "1";
    initEnhancedSelects(row);
    bindSummaryRefresh(row);

    const pathInput = row.querySelector("select[name$='-django_field'], input[name$='-django_field']");
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    const uiActionSelect = row.querySelector("select[name$='-ui_action'], input[name$='-ui_action']");
    const actionTypeSelect = row.querySelector("select[name$='-action_type'], input[name$='-action_type']");

    if (pathInput) {
      pathInput.addEventListener("change", () => {
        updateConditionRow(row);
        refreshRuleSummary();
      });
      if (pathInput.tagName === "INPUT") {
        pathInput.addEventListener("input", () => {
          updateConditionRow(row);
          refreshRuleSummary();
        });
      }
      updateConditionRow(row);
    }

    const operatorSelect = row.querySelector("select[name$='-operator']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (operatorSelect && expectedInput) {
      operatorSelect.addEventListener("change", () => {
        updateExpectedValueVisibility(operatorSelect, expectedInput);
        refreshRuleSummary();
      });
    }

    if (datasetFieldSelect) {
      datasetFieldSelect.addEventListener("change", () => {
        updateActionRow(row);
        refreshRuleSummary();
      });
      updateActionRow(row);
    }

    if (uiActionSelect) {
      uiActionSelect.addEventListener("change", () => {
        updateActionRow(row);
        refreshRuleSummary();
      });
    }

    if (actionTypeSelect) {
      actionTypeSelect.addEventListener("change", () => {
        updateActionRow(row);
        refreshRuleSummary();
      });
    }
  }

  function bindAllRows() {
    document.querySelectorAll("tr.form-row, .inline-related").forEach(bindRow);
    refreshRuleSummary();
  }

  function bindFormsetAddedEvents() {
    document.addEventListener("formset:added", (event) => {
      const target = event && event.target;
      if (target) {
        bindRow(target);
        refreshRuleSummary();
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
      refreshRuleSummary();
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
    patchAdminAutocomplete();
    initEnhancedSelects(document.body);
    bindAllRows();
    bindFormsetAddedEvents();
    observeInlineRows();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
