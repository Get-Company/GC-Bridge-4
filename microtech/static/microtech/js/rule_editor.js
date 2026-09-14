(function () {
  "use strict";

  var VALUELESS = ["is_empty", "is_not_empty", "is_true", "is_false", "empty", "not_empty"];
  var TWO_VALUE = ["between"];
  var ACTION_TYPES = [
    ["set_field", "Dataset-Feld setzen"],
    ["create_extra_position", "Zusatzposition anlegen"],
    ["create_shipping_position", "Versandposition anlegen"],
  ];

  var root = document.getElementById("rule-editor");
  if (!root) return;

  var SAVE_URL = root.dataset.saveUrl;
  var META_URL = root.dataset.metaUrl;
  var OVERVIEW_URL = root.dataset.overviewUrl;
  var DSFIELD_URL = META_URL.replace("rule-builder-meta", "dataset-field-autocomplete");

  var META = { operators: [], django_fields: [], triggers: [] };
  var STATE = null; // the editable rule object

  // ---------- helpers ----------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function opt(value, label, selected) {
    var o = document.createElement("option");
    o.value = value; o.textContent = label;
    if (selected) o.selected = true;
    return o;
  }
  function getCookie(name) {
    var m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? m.pop() : "";
  }
  function operatorByCode(code) {
    for (var i = 0; i < META.operators.length; i++) if (META.operators[i].code === code) return META.operators[i];
    return null;
  }
  function fieldByPath(path) {
    for (var i = 0; i < META.django_fields.length; i++) if (META.django_fields[i].path === path) return META.django_fields[i];
    return null;
  }
  function newGroup(logic) { return { logic: logic || "all", children: [], conditions: [] }; }
  function newCondition() { return { field_path: "", operator_code: "", expected_value: "", expected_value_2: "" }; }
  function newAction() { return { action_type: "set_field", dataset_field_id: null, dataset_field_label: "", target_value: "" }; }

  // ---------- rendering ----------
  function render() {
    renderTrigger();
    renderConditions();
    renderActions();
    renderSummary();
  }

  function renderTrigger() {
    var box = document.getElementById("re-trigger");
    box.className = "re-block re-trigger";
    box.innerHTML = "";
    box.appendChild(el("div", "re-block-label", "Grundregel & Trigger"));

    var r1 = el("div", "re-row");
    r1.appendChild(el("label", null, "Name"));
    var name = el("input"); name.type = "text"; name.value = STATE.name || ""; name.style.minWidth = "220px";
    name.addEventListener("input", function () { STATE.name = name.value; renderSummary(); });
    r1.appendChild(name);
    r1.appendChild(el("label", null, "Priorität"));
    var prio = el("input"); prio.type = "number"; prio.value = STATE.priority != null ? STATE.priority : 100; prio.style.width = "80px";
    prio.addEventListener("input", function () { STATE.priority = parseInt(prio.value, 10) || 0; });
    r1.appendChild(prio);
    box.appendChild(r1);

    var r2 = el("div", "re-row");
    r2.appendChild(el("label", null, "Trigger"));
    var tsel = el("select");
    tsel.appendChild(opt("", "— kein Trigger —", !STATE.trigger_id));
    META.triggers.forEach(function (t) {
      tsel.appendChild(opt(String(t.id), t.label + " (" + t.task_name + ")", String(STATE.trigger_id) === String(t.id)));
    });
    tsel.addEventListener("change", function () { STATE.trigger_id = tsel.value ? parseInt(tsel.value, 10) : null; });
    r2.appendChild(tsel);

    r2.appendChild(el("label", null, "Phase"));
    var phase = el("select");
    phase.appendChild(opt("before", "Vor dem Task", STATE.execution_phase === "before"));
    phase.appendChild(opt("after", "Nach dem Task", STATE.execution_phase === "after"));
    phase.addEventListener("change", function () { STATE.execution_phase = phase.value; });
    r2.appendChild(phase);
    box.appendChild(r2);

    var r3 = el("div", "re-row");
    r3.appendChild(checkbox("Regel aktiv", STATE.is_active, function (v) { STATE.is_active = v; }));
    r3.appendChild(checkbox("Neue Engine aktiv", STATE.engine_enabled, function (v) { STATE.engine_enabled = v; }));
    r3.appendChild(checkbox("Schatten-Modus", STATE.shadow_mode, function (v) { STATE.shadow_mode = v; }));
    box.appendChild(r3);
  }

  function checkbox(label, checked, onchange) {
    var wrap = el("label"); wrap.style.display = "inline-flex"; wrap.style.alignItems = "center"; wrap.style.gap = "5px";
    var cb = el("input"); cb.type = "checkbox"; cb.checked = !!checked;
    cb.addEventListener("change", function () { onchange(cb.checked); });
    wrap.appendChild(cb); wrap.appendChild(document.createTextNode(label));
    return wrap;
  }

  function renderConditions() {
    var box = document.getElementById("re-conditions");
    box.className = "re-block re-when";
    box.innerHTML = "";
    box.appendChild(el("div", "re-block-label", "Wenn (Bedingungen)"));
    if (!STATE.root_group) STATE.root_group = newGroup("all");
    box.appendChild(renderGroup(STATE.root_group, true));
  }

  function renderGroup(group, isRoot) {
    var g = el("div", "re-group" + (isRoot ? " re-root" : ""));
    var head = el("div", "re-group-head");
    var toggle = el("button", "re-logic-toggle");
    toggle.type = "button";
    function paintToggle() {
      toggle.dataset.logic = group.logic;
      toggle.textContent = group.logic === "any" ? "ODER (mind. eine)" : "UND (alle)";
    }
    paintToggle();
    toggle.addEventListener("click", function () {
      group.logic = group.logic === "any" ? "all" : "any";
      paintToggle(); renderSummary();
    });
    head.appendChild(toggle);
    if (!isRoot) {
      var delg = el("button", "re-btn re-btn-del", "Gruppe entfernen");
      delg.type = "button";
      delg.addEventListener("click", function () { group.__remove(); render(); });
      head.appendChild(delg);
    }
    g.appendChild(head);

    group.conditions.forEach(function (cond, idx) {
      g.appendChild(renderCondition(group, cond, idx));
    });
    group.children.forEach(function (child) {
      child.__remove = function () { group.children.splice(group.children.indexOf(child), 1); };
      g.appendChild(renderGroup(child, false));
    });

    var bar = el("div", "re-actionsbar");
    var addC = el("button", "re-btn re-btn-add", "+ Bedingung"); addC.type = "button";
    addC.addEventListener("click", function () { group.conditions.push(newCondition()); render(); });
    var addG = el("button", "re-btn re-btn-add", "+ Untergruppe"); addG.type = "button";
    addG.addEventListener("click", function () { group.children.push(newGroup("all")); render(); });
    bar.appendChild(addC); bar.appendChild(addG);
    g.appendChild(bar);
    return g;
  }

  function renderCondition(group, cond) {
    var row = el("div", "re-cond");
    // field
    var fsel = el("select");
    fsel.appendChild(opt("", "— Feld —", !cond.field_path));
    META.django_fields.forEach(function (f) {
      fsel.appendChild(opt(f.path, f.label || f.path, cond.field_path === f.path));
    });
    fsel.addEventListener("change", function () {
      cond.field_path = fsel.value;
      // reset operator if not allowed for the new field
      var f = fieldByPath(cond.field_path);
      if (f && f.allowed_operator_codes && f.allowed_operator_codes.indexOf(cond.operator_code) < 0) cond.operator_code = "";
      render();
    });
    row.appendChild(fsel);

    // operator (filtered by field)
    var osel = el("select");
    osel.appendChild(opt("", "— Operator —", !cond.operator_code));
    var f = fieldByPath(cond.field_path);
    var allowed = f && f.allowed_operator_codes && f.allowed_operator_codes.length ? f.allowed_operator_codes : null;
    META.operators.forEach(function (o) {
      if (allowed && allowed.indexOf(o.code) < 0) return;
      osel.appendChild(opt(o.code, o.name || o.code, cond.operator_code === o.code));
    });
    osel.addEventListener("change", function () { cond.operator_code = osel.value; render(); });
    row.appendChild(osel);

    // value(s)
    var valueless = VALUELESS.indexOf(cond.operator_code) >= 0;
    if (!valueless) {
      var v1 = el("input"); v1.type = "text"; v1.placeholder = (f && f.example) || "Wert"; v1.value = cond.expected_value || "";
      v1.addEventListener("input", function () { cond.expected_value = v1.value; renderSummary(); });
      row.appendChild(v1);
      if (TWO_VALUE.indexOf(cond.operator_code) >= 0) {
        row.appendChild(el("span", "re-hint", "…"));
        var v2 = el("input"); v2.type = "text"; v2.placeholder = "bis"; v2.value = cond.expected_value_2 || "";
        v2.addEventListener("input", function () { cond.expected_value_2 = v2.value; renderSummary(); });
        row.appendChild(v2);
      }
    }

    var del = el("button", "re-btn re-btn-del", "×"); del.type = "button";
    del.addEventListener("click", function () {
      group.conditions.splice(group.conditions.indexOf(cond), 1); render();
    });
    row.appendChild(del);
    return row;
  }

  function renderActions() {
    var box = document.getElementById("re-actions");
    box.className = "re-block re-then";
    box.innerHTML = "";
    box.appendChild(el("div", "re-block-label", "Dann (Aktionen)"));
    STATE.actions.forEach(function (a) { box.appendChild(renderAction(a)); });
    var addA = el("button", "re-btn re-btn-add", "+ Aktion"); addA.type = "button";
    addA.addEventListener("click", function () { STATE.actions.push(newAction()); render(); });
    box.appendChild(addA);
  }

  function renderAction(a) {
    var row = el("div", "re-action");
    var tsel = el("select");
    ACTION_TYPES.forEach(function (pair) { tsel.appendChild(opt(pair[0], pair[1], a.action_type === pair[0])); });
    tsel.addEventListener("change", function () { a.action_type = tsel.value; render(); });
    row.appendChild(tsel);

    if (a.action_type === "set_field") {
      row.appendChild(datasetFieldPicker(a));
      row.appendChild(el("span", "re-hint", "="));
      row.appendChild(valueEditor(a));
    } else {
      row.appendChild(el("span", "re-hint", a.action_type === "create_shipping_position" ? "Artikel (V/F)" : "ERP-Nr"));
      row.appendChild(valueEditor(a));
    }

    var del = el("button", "re-btn re-btn-del", "×"); del.type = "button";
    del.addEventListener("click", function () { STATE.actions.splice(STATE.actions.indexOf(a), 1); render(); });
    row.appendChild(del);
    return row;
  }

  function valueEditor(a) {
    var wrap = el("span"); wrap.style.display = "inline-flex"; wrap.style.gap = "6px"; wrap.style.alignItems = "center";
    var isVar = /\{\{.*\}\}/.test(a.target_value || "");
    var mode = el("button", "re-valmode"); mode.type = "button";
    mode.dataset.mode = isVar ? "var" : "static";
    mode.textContent = isVar ? "Variable" : "fester Wert";
    mode.addEventListener("click", function () {
      mode.dataset.mode = mode.dataset.mode === "var" ? "static" : "var";
      mode.textContent = mode.dataset.mode === "var" ? "Variable" : "fester Wert";
      pick.style.display = mode.dataset.mode === "var" ? "" : "none";
    });
    wrap.appendChild(mode);

    var input = el("input"); input.type = "text"; input.value = a.target_value || ""; input.placeholder = "Wert oder {{ Feld }}";
    input.addEventListener("input", function () { a.target_value = input.value; renderSummary(); });
    wrap.appendChild(input);

    var pick = el("select", "re-varpick");
    pick.appendChild(opt("", "Variable einfügen…", true));
    META.django_fields.forEach(function (f) { pick.appendChild(opt(f.path, f.label || f.path)); });
    pick.style.display = isVar ? "" : "none";
    pick.addEventListener("change", function () {
      if (!pick.value) return;
      input.value = "{{ " + pick.value + " }}";
      a.target_value = input.value; pick.value = ""; renderSummary();
    });
    wrap.appendChild(pick);
    return wrap;
  }

  // async dataset-field autocomplete for set_field target
  function datasetFieldPicker(a) {
    var wrap = el("span", "re-ac-wrap");
    var input = el("input"); input.type = "text"; input.placeholder = "Dataset-Feld suchen…";
    input.value = a.dataset_field_label || (a.dataset_field_id ? "#" + a.dataset_field_id : "");
    var results = el("div", "re-ac-results"); results.style.display = "none";
    var timer = null;
    function search() {
      var term = input.value.trim();
      fetch(DSFIELD_URL + "?term=" + encodeURIComponent(term), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          results.innerHTML = "";
          (data.results || []).forEach(function (item) {
            var it = el("div", "re-ac-item", item.text);
            it.addEventListener("mousedown", function (ev) {
              ev.preventDefault();
              a.dataset_field_id = parseInt(item.id, 10);
              a.dataset_field_label = item.text;
              input.value = item.text;
              results.style.display = "none";
              renderSummary();
            });
            results.appendChild(it);
          });
          results.style.display = data.results && data.results.length ? "" : "none";
        })
        .catch(function () { results.style.display = "none"; });
    }
    input.addEventListener("input", function () {
      a.dataset_field_id = null; a.dataset_field_label = "";
      renderSummary();
      clearTimeout(timer); timer = setTimeout(search, 200);
    });
    input.addEventListener("focus", search);
    input.addEventListener("blur", function () { setTimeout(function () { results.style.display = "none"; }, 150); });
    wrap.appendChild(input); wrap.appendChild(results);
    return wrap;
  }

  // ---------- summary ----------
  function summarizeGroup(group) {
    var parts = group.conditions.map(function (c) {
      if (!c.field_path || !c.operator_code) return null;
      var f = fieldByPath(c.field_path); var o = operatorByCode(c.operator_code);
      var flabel = f ? (f.label || f.path) : c.field_path;
      var olabel = o ? (o.name || o.code) : c.operator_code;
      if (VALUELESS.indexOf(c.operator_code) >= 0) return flabel + " " + olabel;
      if (TWO_VALUE.indexOf(c.operator_code) >= 0) return flabel + " " + olabel + " " + c.expected_value + "…" + c.expected_value_2;
      return c.expected_value ? flabel + " " + olabel + " " + c.expected_value : null;
    }).filter(Boolean);
    group.children.forEach(function (ch) { var s = summarizeGroup(ch); if (s) parts.push("(" + s + ")"); });
    if (!parts.length) return "";
    return parts.join(group.logic === "any" ? " ODER " : " UND ");
  }

  function renderSummary() {
    var box = document.getElementById("re-summary");
    box.className = "re-block";
    box.innerHTML = "";
    box.appendChild(el("div", "re-block-label", "Klartext-Vorschau"));
    var when = STATE.root_group ? summarizeGroup(STATE.root_group) : "";
    var actions = STATE.actions.map(function (a) {
      if (a.action_type === "set_field") return "setze " + (a.dataset_field_label || "Feld") + " = " + (a.target_value || "?");
      if (a.action_type === "create_shipping_position") return "Versandposition " + (a.target_value || "?");
      return "Zusatzposition " + (a.target_value || "?");
    });
    var text = (when ? "Wenn " + when : "Immer") + (actions.length ? ", dann " + actions.join(", ") : ", dann (keine Aktion)");
    box.appendChild(el("div", "re-summary", text));
  }

  // ---------- save ----------
  function collectPayload() {
    function grp(g) {
      return {
        logic: g.logic,
        conditions: g.conditions.filter(function (c) { return c.field_path && c.operator_code; })
          .map(function (c) {
            return { field_path: c.field_path, operator_code: c.operator_code,
                     expected_value: c.expected_value || "", expected_value_2: c.expected_value_2 || "" };
          }),
        children: g.children.map(grp),
      };
    }
    return {
      id: STATE.id,
      name: STATE.name, priority: STATE.priority, is_active: STATE.is_active,
      execution_phase: STATE.execution_phase, engine_enabled: STATE.engine_enabled, shadow_mode: STATE.shadow_mode,
      trigger_id: STATE.trigger_id,
      root_group: STATE.root_group ? grp(STATE.root_group) : null,
      actions: STATE.actions.map(function (a) {
        return { action_type: a.action_type, dataset_field_id: a.action_type === "set_field" ? a.dataset_field_id : null,
                 target_value: a.target_value || "" };
      }),
    };
  }

  function showErrors(errs) {
    var old = document.getElementById("re-errbox");
    if (old) old.remove();
    var box = el("div", "re-errors"); box.id = "re-errbox";
    box.appendChild(document.createTextNode("Speichern fehlgeschlagen:"));
    var ul = el("ul");
    (errs || ["Unbekannter Fehler"]).forEach(function (e) { ul.appendChild(el("li", null, e)); });
    box.appendChild(ul);
    root.insertBefore(box, document.getElementById("re-save").parentNode || document.getElementById("re-save"));
  }

  function save() {
    var btn = document.getElementById("re-save");
    btn.disabled = true;
    fetch(SAVE_URL, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      body: JSON.stringify(collectPayload()),
    }).then(function (r) { return r.json().then(function (d) { return { status: r.status, data: d }; }); })
      .then(function (res) {
        if (res.status === 200 && res.data.ok) { window.location.href = res.data.redirect || OVERVIEW_URL; return; }
        btn.disabled = false;
        showErrors(res.data.errors);
      })
      .catch(function () { btn.disabled = false; showErrors(["Netzwerk-/Serverfehler"]); });
  }

  // ---------- init ----------
  function init() {
    try {
      STATE = JSON.parse(document.getElementById("rule-data").textContent);
    } catch (e) { STATE = null; }
    if (!STATE) return;
    if (!STATE.actions) STATE.actions = [];
    var savebar = el("div", "re-savebar");
    var saveBtn = document.getElementById("re-save");
    saveBtn.className = "re-btn re-btn-primary";
    saveBtn.parentNode.insertBefore(savebar, saveBtn);
    savebar.appendChild(saveBtn);
    var cancel = el("a", "re-btn", "Abbrechen"); cancel.href = OVERVIEW_URL;
    savebar.appendChild(cancel);
    saveBtn.addEventListener("click", save);

    fetch(META_URL, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok) {
          META.operators = data.operators || [];
          META.django_fields = data.django_fields || [];
          META.triggers = data.triggers || [];
        }
        render();
      })
      .catch(function () { render(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
