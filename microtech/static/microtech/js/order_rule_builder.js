(function () {
  "use strict";

  const CONDITION_META = {
    customer_type: {
      operators: ["eq"],
      placeholder: "private | company | any",
      hint: "Erlaubt: private/company/any",
    },
    billing_country_code: {
      operators: ["eq", "contains"],
      placeholder: "DE",
      hint: "ISO2-Code, z. B. DE/AT/CH",
    },
    shipping_country_code: {
      operators: ["eq", "contains"],
      placeholder: "DE",
      hint: "ISO2-Code, z. B. DE/AT/CH",
    },
    payment_method: {
      operators: ["eq", "contains"],
      placeholder: "paypal",
      hint: "String, case-insensitive bei contains",
    },
    shipping_method: {
      operators: ["eq", "contains"],
      placeholder: "dhl",
      hint: "String, z. B. dhl/spedition",
    },
    order_total: {
      operators: ["eq", "gt", "lt"],
      placeholder: "100.50",
      hint: "Dezimalzahl",
    },
    order_total_tax: {
      operators: ["eq", "gt", "lt"],
      placeholder: "19.00",
      hint: "Dezimalzahl",
    },
    shipping_costs: {
      operators: ["eq", "gt", "lt"],
      placeholder: "4.90",
      hint: "Dezimalzahl",
    },
    order_number: {
      operators: ["eq", "contains"],
      placeholder: "SW100045",
      hint: "String",
    },
  };

  const ACTION_META = {
    na1_mode: {
      placeholder: "auto | firma_or_salutation | salutation_only | static",
      hint: "Enum",
    },
    na1_static_value: { placeholder: "Firma", hint: "String" },
    vorgangsart_id: { placeholder: "111", hint: "Integer > 0" },
    zahlungsart_id: { placeholder: "22", hint: "Integer > 0" },
    versandart_id: { placeholder: "10", hint: "Integer > 0" },
    zahlungsbedingung: { placeholder: "Sofort ohne Abzug", hint: "String" },
    add_payment_position: { placeholder: "true", hint: "Bool: true/false, ja/nein, 1/0" },
    payment_position_erp_nr: { placeholder: "P", hint: "String" },
    payment_position_name: { placeholder: "PayPal", hint: "String" },
    payment_position_mode: { placeholder: "fixed | percent_total", hint: "Enum" },
    payment_position_value: { placeholder: "2.50", hint: "Dezimalzahl" },
  };

  function updateConditionRow(row) {
    const sourceSelect = row.querySelector("select[name$='-source_field']");
    const operatorSelect = row.querySelector("select[name$='-operator']");
    const expectedInput = row.querySelector("input[name$='-expected_value']");
    if (!sourceSelect || !operatorSelect || !expectedInput) return;

    const meta = CONDITION_META[sourceSelect.value];
    if (!meta) {
      expectedInput.placeholder = "";
      expectedInput.title = "";
      return;
    }

    const currentOperator = operatorSelect.value;
    let hasCurrent = false;
    Array.from(operatorSelect.options).forEach((option) => {
      if (!option.value) {
        option.hidden = false;
        return;
      }
      const allowed = meta.operators.includes(option.value);
      option.hidden = !allowed;
      if (allowed && option.value === currentOperator) {
        hasCurrent = true;
      }
    });
    if (!hasCurrent && meta.operators.length > 0) {
      operatorSelect.value = meta.operators[0];
    }

    expectedInput.placeholder = meta.placeholder || "";
    expectedInput.title = meta.hint || "";
  }

  function updateActionRow(row) {
    const targetSelect = row.querySelector("select[name$='-target_field']");
    const targetInput = row.querySelector("input[name$='-target_value']");
    if (!targetSelect || !targetInput) return;

    const meta = ACTION_META[targetSelect.value];
    targetInput.placeholder = (meta && meta.placeholder) || "";
    targetInput.title = (meta && meta.hint) || "";
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

  function init() {
    document.querySelectorAll("tr.form-row, .inline-related").forEach(bindRow);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
