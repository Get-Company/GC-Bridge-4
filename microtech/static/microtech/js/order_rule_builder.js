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

  function sourceByCode(code) {
    if (!RULE_META || !Array.isArray(RULE_META.condition_sources)) return null;
    return RULE_META.condition_sources.find((item) => item.code === code) || null;
  }

  function targetByCode(code) {
    if (!RULE_META || !Array.isArray(RULE_META.action_targets)) return null;
    return RULE_META.action_targets.find((item) => item.code === code) || null;
  }

  function updateConditionRow(row) {
    const sourceSelect = row.querySelector("select[name$='-source_field']");
    const operatorSelect = row.querySelector("select[name$='-operator']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (!sourceSelect || !operatorSelect || !expectedInput || !RULE_META) return;

    const source = sourceByCode(sourceSelect.value);
    if (!source) {
      expectedInput.placeholder = "";
      expectedInput.title = "";
      return;
    }

    const labels = operatorLabelMap();
    const current = operatorSelect.value;
    const allowed = Array.isArray(source.allowed_operator_codes) ? source.allowed_operator_codes : [];

    let hasCurrent = false;
    Array.from(operatorSelect.options).forEach((option) => {
      if (!option.value) {
        option.hidden = false;
        return;
      }
      option.text = labels[option.value] || option.text;
      const allowedForSource = allowed.length === 0 || allowed.includes(option.value);
      option.hidden = !allowedForSource;
      if (allowedForSource && option.value === current) {
        hasCurrent = true;
      }
    });

    if (!hasCurrent && allowed.length > 0) {
      operatorSelect.value = allowed[0];
    }

    expectedInput.placeholder = source.example || "";
    expectedInput.title = source.hint || "";
  }

  function updateActionRow(row) {
    const targetSelect = row.querySelector("select[name$='-target_field']");
    const targetInput = row.querySelector("input[name$='-target_value']");
    if (!targetSelect || !targetInput || !RULE_META) return;

    const target = targetByCode(targetSelect.value);
    if (!target) {
      targetInput.placeholder = "";
      targetInput.title = "";
      return;
    }
    targetInput.placeholder = target.example || "";
    targetInput.title = target.hint || "";
  }

  function bindRow(row) {
    const sourceSelect = row.querySelector("select[name$='-source_field']");
    const targetSelect = row.querySelector("select[name$='-target_field']");

    if (sourceSelect) {
      sourceSelect.addEventListener("change", () => updateConditionRow(row));
      updateConditionRow(row);
    }
    if (targetSelect) {
      targetSelect.addEventListener("change", () => updateActionRow(row));
      updateActionRow(row);
    }
  }

  function bindAllRows() {
    document.querySelectorAll("tr.form-row, .inline-related").forEach(bindRow);
  }

  async function loadMeta() {
    const url = buildMetaUrl();
    if (!url) {
      return;
    }
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
    bindAllRows();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
