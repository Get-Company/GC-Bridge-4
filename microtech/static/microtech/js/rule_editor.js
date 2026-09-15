/* Interactive rule editor as a reusable component.
 *
 * Exposes window.RuleEditor.mount(container, opts) so the same UI works both on
 * the standalone editor page and inline inside an overview card. Each mount is
 * self-contained (own STATE, own DOM scoped to the container); META (operators,
 * fields, triggers) is fetched once and shared across mounts. Tracks unsaved
 * changes and warns before losing them.
 *
 * opts = {
 *   ruleData:    editable rule JSON (serialize_rule_for_edit shape),
 *   saveUrl, metaUrl, overviewUrl,
 *   inline:      boolean (true when mounted in an overview card),
 *   onSaved:     function() called after a successful save (inline),
 *   onCancel:    function() called when the user cancels (inline),
 * }
 */
(function () {
  "use strict";

  var VALUELESS = ["is_empty", "is_not_empty", "is_true", "is_false", "empty", "not_empty"];
  var TWO_VALUE = ["between"];
  var ACTION_TYPES = [
    ["set_field", "Dataset-Feld setzen"],
    ["create_extra_position", "Zusatzposition anlegen"],
    ["create_shipping_position", "Versandposition anlegen"],
  ];

  // ---------- shared helpers ----------
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

  // ---------- shared META cache ----------
  var META = null;              // {operators, django_fields, triggers}
  var META_PROMISE = null;
  function loadMeta(metaUrl) {
    if (META) return Promise.resolve(META);
    if (META_PROMISE) return META_PROMISE;
    META_PROMISE = fetch(metaUrl, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        META = (data && data.ok)
          ? { operators: data.operators || [], django_fields: data.django_fields || [], triggers: data.triggers || [] }
          : { operators: [], django_fields: [], triggers: [] };
        return META;
      })
      .catch(function () { META = { operators: [], django_fields: [], triggers: [] }; return META; });
    return META_PROMISE;
  }

  // ---------- one editor instance ----------
  function mount(container, opts) {
    opts = opts || {};
    var SAVE_URL = opts.saveUrl;
    var OVERVIEW_URL = opts.overviewUrl;
    var DSFIELD_URL = (opts.metaUrl || "").replace("rule-builder-meta", "dataset-field-autocomplete");
    var inline = !!opts.inline;

    var STATE = normalizeState(opts.ruleData);
    var dirty = false;

    // scoped DOM skeleton
    container.classList.add("re-editor");
    container.innerHTML = "";
    var elTrigger = el("div"); elTrigger.className = "re-trigger-box";
    var elConditions = el("div"); elConditions.className = "re-conditions-box";
    var elActions = el("div"); elActions.className = "re-actions-box";
    var elSummary = el("div"); elSummary.className = "re-summary-box";
    var savebar = el("div", "re-savebar");
    var dirtyFlag = el("span", "re-dirty", "● Nicht gespeichert"); dirtyFlag.hidden = true;
    var saveBtn = el("button", "re-btn re-btn-primary", "Speichern"); saveBtn.type = "button";
    var cancelBtn = el("a", "re-btn", "Abbrechen");
    savebar.appendChild(saveBtn);
    savebar.appendChild(cancelBtn);
    savebar.appendChild(dirtyFlag);
    container.appendChild(elTrigger);
    container.appendChild(elConditions);
    container.appendChild(elActions);
    container.appendChild(elSummary);
    container.appendChild(savebar);

    function markDirty() {
      if (!dirty) { dirty = true; dirtyFlag.hidden = false; }
    }
    function clearDirty() { dirty = false; dirtyFlag.hidden = true; }
    // Any text/select/checkbox change inside the editor marks it dirty.
    container.addEventListener("input", markDirty, true);
    container.addEventListener("change", markDirty, true);

    function operatorByCode(code) {
      for (var i = 0; i < META.operators.length; i++) if (META.operators[i].code === code) return META.operators[i];
      return null;
    }
    function fieldByPath(path) {
      for (var i = 0; i < META.django_fields.length; i++) if (META.django_fields[i].path === path) return META.django_fields[i];
      return null;
    }
    function currentContextRoot() {
      if (!STATE.trigger_id) return "orders.Order";
      for (var i = 0; i < META.triggers.length; i++) {
        if (String(META.triggers[i].id) === String(STATE.trigger_id)) return META.triggers[i].context_root || "orders.Order";
      }
      return "orders.Order";
    }
    function fieldsForContext() {
      var ctx = currentContextRoot();
      return META.django_fields.filter(function (f) { return (f.context_root || "orders.Order") === ctx; });
    }

    // ---------- rendering ----------
    function render() { renderTrigger(); renderConditions(); renderActions(); renderSummary(); }

    function renderTrigger() {
      var box = elTrigger;
      box.className = "re-block re-trigger re-trigger-box";
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
      tsel.addEventListener("change", function () {
        STATE.trigger_id = tsel.value ? parseInt(tsel.value, 10) : null;
        render();  // Feldlisten hängen vom Trigger-Kontext ab
      });
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
      var box = elConditions;
      box.className = "re-block re-when re-conditions-box";
      box.innerHTML = "";
      box.appendChild(el("div", "re-block-label", "Wenn (Bedingungen)"));
      if (!STATE.root_group) STATE.root_group = newGroup("all");
      box.appendChild(renderGroup(STATE.root_group, true));
    }

    function renderGroup(group, isRoot) {
      var g = el("div", "re-group" + (isRoot ? " re-root" : ""));
      var head = el("div", "re-group-head");
      var toggle = el("button", "re-logic-toggle"); toggle.type = "button";
      function paintToggle() {
        toggle.dataset.logic = group.logic;
        toggle.textContent = group.logic === "any" ? "ODER (mind. eine)" : "UND (alle)";
      }
      paintToggle();
      toggle.addEventListener("click", function () {
        group.logic = group.logic === "any" ? "all" : "any";
        markDirty(); paintToggle(); renderSummary();
      });
      head.appendChild(toggle);
      if (!isRoot) {
        var delg = el("button", "re-btn re-btn-del", "Gruppe entfernen"); delg.type = "button";
        delg.addEventListener("click", function () { markDirty(); group.__remove(); render(); });
        head.appendChild(delg);
      }
      g.appendChild(head);

      group.conditions.forEach(function (cond) { g.appendChild(renderCondition(group, cond)); });
      group.children.forEach(function (child) {
        child.__remove = function () { group.children.splice(group.children.indexOf(child), 1); };
        g.appendChild(renderGroup(child, false));
      });

      var bar = el("div", "re-actionsbar");
      var addC = el("button", "re-btn re-btn-add", "+ Bedingung"); addC.type = "button";
      addC.addEventListener("click", function () { markDirty(); group.conditions.push(newCondition()); render(); });
      var addG = el("button", "re-btn re-btn-add", "+ Untergruppe"); addG.type = "button";
      addG.addEventListener("click", function () { markDirty(); group.children.push(newGroup("all")); render(); });
      bar.appendChild(addC); bar.appendChild(addG);
      g.appendChild(bar);
      return g;
    }

    function renderCondition(group, cond) {
      var row = el("div", "re-cond");
      var fsel = el("select");
      fsel.appendChild(opt("", "— Feld —", !cond.field_path));
      fieldsForContext().forEach(function (f) { fsel.appendChild(opt(f.path, f.label || f.path, cond.field_path === f.path)); });
      fsel.addEventListener("change", function () {
        cond.field_path = fsel.value;
        var f = fieldByPath(cond.field_path);
        if (f && f.allowed_operator_codes && f.allowed_operator_codes.indexOf(cond.operator_code) < 0) cond.operator_code = "";
        render();
      });
      row.appendChild(fsel);

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
      del.addEventListener("click", function () { markDirty(); group.conditions.splice(group.conditions.indexOf(cond), 1); render(); });
      row.appendChild(del);
      return row;
    }

    function renderActions() {
      var box = elActions;
      box.className = "re-block re-then re-actions-box";
      box.innerHTML = "";
      box.appendChild(el("div", "re-block-label", "Dann (Aktionen)"));
      STATE.actions.forEach(function (a) { box.appendChild(renderAction(a)); });
      var addA = el("button", "re-btn re-btn-add", "+ Aktion"); addA.type = "button";
      addA.addEventListener("click", function () { markDirty(); STATE.actions.push(newAction()); render(); });
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
      del.addEventListener("click", function () { markDirty(); STATE.actions.splice(STATE.actions.indexOf(a), 1); render(); });
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
        markDirty();
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
      fieldsForContext().forEach(function (f) { pick.appendChild(opt(f.path, f.label || f.path)); });
      pick.style.display = isVar ? "" : "none";
      pick.addEventListener("change", function () {
        if (!pick.value) return;
        input.value = "{{ " + pick.value + " }}";
        a.target_value = input.value; pick.value = ""; renderSummary();
      });
      wrap.appendChild(pick);
      return wrap;
    }

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
                markDirty();
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
      var box = elSummary;
      box.className = "re-block re-summary-box";
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
      var old = container.querySelector(".re-errors");
      if (old) old.remove();
      var box = el("div", "re-errors");
      box.appendChild(document.createTextNode("Speichern fehlgeschlagen:"));
      var ul = el("ul");
      (errs || ["Unbekannter Fehler"]).forEach(function (e) { ul.appendChild(el("li", null, e)); });
      box.appendChild(ul);
      container.insertBefore(box, savebar);
    }

    function save() {
      saveBtn.disabled = true;
      fetch(SAVE_URL, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
        body: JSON.stringify(collectPayload()),
      }).then(function (r) { return r.json().then(function (d) { return { status: r.status, data: d }; }); })
        .then(function (res) {
          if (res.status === 200 && res.data.ok) {
            clearDirty();
            if (inline && typeof opts.onSaved === "function") { opts.onSaved(res.data); return; }
            window.location.href = res.data.redirect || OVERVIEW_URL;
            return;
          }
          saveBtn.disabled = false;
          showErrors(res.data.errors);
        })
        .catch(function () { saveBtn.disabled = false; showErrors(["Netzwerk-/Serverfehler"]); });
    }

    saveBtn.addEventListener("click", save);
    cancelBtn.addEventListener("click", function (ev) {
      if (dirty && !window.confirm("Ungespeicherte Änderungen verwerfen?")) { if (ev) ev.preventDefault(); return; }
      clearDirty();
      if (inline && typeof opts.onCancel === "function") { if (ev) ev.preventDefault(); opts.onCancel(); return; }
      window.location.href = OVERVIEW_URL;
    });
    if (!inline) cancelBtn.href = OVERVIEW_URL;
    else cancelBtn.href = "#";

    // beforeunload guard (once per page is enough, but harmless if repeated)
    window.addEventListener("beforeunload", function (e) {
      if (dirty) { e.preventDefault(); e.returnValue = ""; return ""; }
    });

    loadMeta(opts.metaUrl).then(function () { render(); });

    return {
      isDirty: function () { return dirty; },
      destroy: function () { container.innerHTML = ""; },
    };
  }

  // ---------- state helpers ----------
  function newGroup(logic) { return { logic: logic || "all", children: [], conditions: [] }; }
  function newCondition() { return { field_path: "", operator_code: "", expected_value: "", expected_value_2: "" }; }
  function newAction() { return { action_type: "set_field", dataset_field_id: null, dataset_field_label: "", target_value: "" }; }
  function normalizeState(data) {
    var s = data ? JSON.parse(JSON.stringify(data)) : {};
    if (!s.actions) s.actions = [];
    if (s.shadow_mode == null) s.shadow_mode = true;
    if (s.priority == null) s.priority = 100;
    if (!s.execution_phase) s.execution_phase = "before";
    return s;
  }

  window.RuleEditor = { mount: mount, loadMeta: loadMeta };

  // ---------- standalone-page auto-init ----------
  function initStandalone() {
    var root = document.getElementById("rule-editor");
    if (!root) return;
    var ruleData = null;
    try { ruleData = JSON.parse(document.getElementById("rule-data").textContent); } catch (e) { ruleData = null; }
    if (!ruleData) return;
    mount(root, {
      ruleData: ruleData,
      saveUrl: root.dataset.saveUrl,
      metaUrl: root.dataset.metaUrl,
      overviewUrl: root.dataset.overviewUrl,
      inline: false,
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initStandalone);
  else initStandalone();
})();
