(function () {
  "use strict";

  let RULE_META = null;

  function buildMetaUrl() {
    const path = window.location.pathname;
    const marker = "/microtechorderrule/";
    const idx = path.indexOf(marker);
    if (idx < 0) return "";
    const base = path.slice(0, idx + marker.length);
    return `${base}rule-builder-meta/`;
  }

  function operatorLabelMap() {
    const map = {};
    if (!RULE_META || !Array.isArray(RULE_META.operators)) return map;
    RULE_META.operators.forEach((op) => {
      if (op && op.code) map[op.code] = op.name || op.code;
    });
    return map;
  }

  function operatorsByCode() {
    const map = {};
    if (!RULE_META || !Array.isArray(RULE_META.operators)) return map;
    RULE_META.operators.forEach((op) => {
      if (op && op.code) map[op.code] = op;
    });
    return map;
  }

  function djangoFieldByPath(path) {
    if (!RULE_META || !Array.isArray(RULE_META.django_fields)) return null;
    return RULE_META.django_fields.find((item) => item.path === path) || null;
  }

  function datasetFieldById(idValue) {
    if (!RULE_META || !Array.isArray(RULE_META.dataset_fields)) return null;
    const id = String(idValue || "");
    return RULE_META.dataset_fields.find((item) => String(item.id) === id) || null;
  }

  function datasetFieldsFor(datasetId) {
    if (!RULE_META || !Array.isArray(RULE_META.dataset_fields)) return [];
    const id = String(datasetId || "");
    if (!id) return [];
    return RULE_META.dataset_fields.filter((item) => String(item.dataset_id) === id);
  }

  function ensureDjangoFieldDatalist() {
    if (!RULE_META || !Array.isArray(RULE_META.django_fields)) return;
    let datalist = document.getElementById("microtech-django-field-paths");
    if (!datalist) {
      datalist = document.createElement("datalist");
      datalist.id = "microtech-django-field-paths";
      document.body.appendChild(datalist);
    }
    datalist.innerHTML = "";
    RULE_META.django_fields.forEach((item) => {
      if (!item || !item.path) return;
      const option = document.createElement("option");
      option.value = item.path;
      option.label = item.label || item.path;
      datalist.appendChild(option);
    });
  }

  function rebuildOperatorOptions(operatorSelect, allowedCodes, current) {
    const byCode = operatorsByCode();
    operatorSelect.innerHTML = "";

    const options = (allowedCodes && allowedCodes.length > 0)
      ? allowedCodes
      : Object.keys(byCode);

    options.forEach((code) => {
      const option = document.createElement("option");
      option.value = code;
      option.textContent = (byCode[code] && (byCode[code].name || byCode[code].code)) || code;
      operatorSelect.appendChild(option);
    });

    if (current && options.includes(current)) {
      operatorSelect.value = current;
    } else if (options.length > 0) {
      operatorSelect.value = options[0];
    }
  }

  function updateConditionRow(row) {
    const pathInput = row.querySelector("input[name$='-django_field_path']");
    const operatorSelect = row.querySelector("select[name$='-operator_code']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (!pathInput || !operatorSelect || !expectedInput || !RULE_META) return;

    pathInput.setAttribute("list", "microtech-django-field-paths");

    const fieldDef = djangoFieldByPath(pathInput.value);
    const currentOperator = operatorSelect.value;

    if (!fieldDef) {
      rebuildOperatorOptions(operatorSelect, [], currentOperator);
      expectedInput.placeholder = "";
      expectedInput.title = "";
      return;
    }

    rebuildOperatorOptions(operatorSelect, fieldDef.allowed_operator_codes || [], currentOperator);
    expectedInput.placeholder = fieldDef.example || "";
    expectedInput.title = fieldDef.hint || "";
  }

  function rebuildDatasetFieldOptions(datasetFieldSelect, datasetId, currentValue) {
    const fields = datasetFieldsFor(datasetId);
    datasetFieldSelect.innerHTML = "";

    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "---------";
    datasetFieldSelect.appendChild(empty);

    fields.forEach((item) => {
      const option = document.createElement("option");
      option.value = String(item.id);
      const label = item.label ? `${item.field_name} - ${item.label}` : item.field_name;
      option.textContent = label;
      datasetFieldSelect.appendChild(option);
    });

    if (currentValue && fields.some((item) => String(item.id) === String(currentValue))) {
      datasetFieldSelect.value = String(currentValue);
    }
  }

  function toggleActionTypeFields(row) {
    const actionTypeSelect = row.querySelector("select[name$='-action_type']");
    const datasetSelect = row.querySelector("select[name$='-dataset']");
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    const targetInput = row.querySelector("input[name$='-target_value']");
    if (!actionTypeSelect || !datasetSelect || !datasetFieldSelect || !targetInput) return;

    const isCreatePosition = actionTypeSelect.value === "create_extra_position";

    datasetSelect.disabled = isCreatePosition;
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
    const datasetSelect = row.querySelector("select[name$='-dataset']");
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    if (!actionTypeSelect || !datasetSelect || !datasetFieldSelect || !RULE_META) return;

    const currentField = datasetFieldSelect.value;
    rebuildDatasetFieldOptions(datasetFieldSelect, datasetSelect.value, currentField);
    toggleActionTypeFields(row);
  }

  function bindRow(row) {
    if (!row || row.dataset.ruleBuilderBound === "1") {
      return;
    }
    row.dataset.ruleBuilderBound = "1";

    const pathInput = row.querySelector("input[name$='-django_field_path']");
    const datasetSelect = row.querySelector("select[name$='-dataset']");
    const datasetFieldSelect = row.querySelector("select[name$='-dataset_field']");
    const actionTypeSelect = row.querySelector("select[name$='-action_type']");

    if (pathInput) {
      pathInput.addEventListener("change", () => updateConditionRow(row));
      pathInput.addEventListener("input", () => updateConditionRow(row));
      updateConditionRow(row);
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
    ensureDjangoFieldDatalist();
    bindAllRows();
    bindFormsetAddedEvents();
    observeInlineRows();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
