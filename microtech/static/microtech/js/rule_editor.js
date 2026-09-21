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
    ["set_field", "Feld setzen"],
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
  function fieldDisplay(label, technicalName) {
    label = String(label || "").trim();
    technicalName = String(technicalName || "").trim();
    if (!label || label === technicalName) return technicalName || label;
    return label + " · " + technicalName;
  }
  function shopFieldDisplay(field) {
    return fieldDisplay(field.label || field.path, field.path);
  }
  function datasetFieldDisplay(field) {
    return fieldDisplay(field.label || field.fieldName, field.datasetName + "." + field.fieldName);
  }
  function datasetFieldTitle(field) {
    return [
      datasetFieldDisplay(field),
      field.sourceIdentifier,
      field.fieldType,
    ].filter(Boolean).join(" · ");
  }
  function graphqlFieldDisplay(field) {
    return fieldDisplay(field.name, field.value);
  }
  function graphqlFieldDisplayFromValue(value) {
    value = String(value || "").trim();
    return value ? fieldDisplay(value.split(".").pop(), value) : "";
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

  var DSFIELDS = null;          // [{source_identifier, name, fields:[{id,field_name,label}]}]
  var DSFIELDS_PROMISE = null;
  function loadDatasetFields(url) {
    if (DSFIELDS) return Promise.resolve(DSFIELDS);
    if (DSFIELDS_PROMISE) return DSFIELDS_PROMISE;
    DSFIELDS_PROMISE = fetch(url, { credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        DSFIELDS = (data && data.ok) ? (data.datasets || []) : [];
        return DSFIELDS;
      })
      .catch(function () { DSFIELDS = []; return DSFIELDS; });
    return DSFIELDS_PROMISE;
  }

  var GQLFIELDS = null;         // [{input_type, label, fields:[{name}]}]
  var GQLFIELDS_PROMISE = null;
  var GQLFIELD_SOURCE = "";
  function loadGraphqlFields(url, refresh) {
    if (refresh) {
      GQLFIELDS = null;
      GQLFIELDS_PROMISE = null;
      GQLFIELD_SOURCE = "";
      url += (url.indexOf("?") >= 0 ? "&" : "?") + "refresh=1";
    }
    if (GQLFIELDS) return Promise.resolve(GQLFIELDS);
    if (GQLFIELDS_PROMISE) return GQLFIELDS_PROMISE;
    GQLFIELDS_PROMISE = fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        GQLFIELD_SOURCE = (d && d.ok) ? (d.source || "") : "";
        GQLFIELDS = (d && d.ok) ? (d.groups || []) : [];
        return GQLFIELDS;
      })
      .catch(function () { GQLFIELD_SOURCE = "unavailable"; GQLFIELDS = []; return GQLFIELDS; });
    return GQLFIELDS_PROMISE;
  }

  // ---------- one editor instance ----------
  function mount(container, opts) {
    opts = opts || {};
    var SAVE_URL = opts.saveUrl;
    var OVERVIEW_URL = opts.overviewUrl;
    var DSGROUP_URL = (opts.metaUrl || "").replace("rule-builder-meta", "dataset-fields-grouped");
    var GQLGROUP_URL = (opts.metaUrl || "").replace("rule-builder-meta", "graphql-fields-grouped");
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
      var contextRoot = currentContextRoot();
      for (var i = 0; i < META.django_fields.length; i++) {
        if (META.django_fields[i].path === path && (META.django_fields[i].context_root || "orders.Order") === contextRoot) {
          return META.django_fields[i];
        }
      }
      for (var j = 0; j < META.django_fields.length; j++) if (META.django_fields[j].path === path) return META.django_fields[j];
      return null;
    }
    function currentTrigger() {
      for (var i = 0; i < META.triggers.length; i++) {
        if (String(META.triggers[i].id) === String(STATE.trigger_id)) return META.triggers[i];
      }
      return null;
    }
    function currentContextRoot() {
      var trigger = currentTrigger();
      return trigger ? (trigger.context_root || "orders.Order") : "orders.Order";
    }
    function fieldsForContext() {
      var ctx = currentContextRoot();
      return META.django_fields.filter(function (f) { return (f.context_root || "orders.Order") === ctx; });
    }
    function graphqlScopesForCurrentTrigger() {
      var trigger = currentTrigger();
      return trigger && Array.isArray(trigger.graphql_scopes) ? trigger.graphql_scopes : [];
    }
    function graphqlInputTypesForCurrentTrigger(action) {
      var trigger = currentTrigger();
      var scopes = graphqlScopesForCurrentTrigger();
      if (scopes.length) {
        var scopeCode = (action && action.target_scope) || "customer";
        for (var i = 0; i < scopes.length; i++) {
          if (scopes[i].code === scopeCode) return scopes[i].graphql_input_types || [];
        }
        return [];
      }
      return trigger && Array.isArray(trigger.graphql_input_types) ? trigger.graphql_input_types : [];
    }
    function actionTargetKind(action) {
      if (!currentTrigger()) return "";
      if (graphqlInputTypesForCurrentTrigger(action).length) return "graphql";
      return currentContextRoot() === "orders.Order" ? "dataset" : "";
    }
    function reconcileActionTargets() {
      STATE.actions.forEach(function (action) {
        if (action.action_type !== "set_field") return;
        var kind = actionTargetKind(action);
        var allowedTypes = graphqlInputTypesForCurrentTrigger(action);
        if (kind === "graphql") {
          action.dataset_field_id = null;
          action.dataset_field_label = "";
          var inputType = String(action.graphql_field || "").split(".")[0];
          if (action.graphql_field && allowedTypes.indexOf(inputType) < 0) {
            action.graphql_field = "";
            action.graphql_field_label = "";
          }
        } else if (kind === "dataset") {
          action.graphql_field = "";
          action.graphql_field_label = "";
        } else {
          action.graphql_field = "";
          action.graphql_field_label = "";
          action.dataset_field_id = null;
          action.dataset_field_label = "";
        }
      });
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
        reconcileActionTargets();
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
      row.appendChild(shopFieldPicker({
        value: cond.field_path,
        placeholder: "Shop-Feld suchen…",
        onSelect: function (field) {
          markDirty();
          cond.field_path = field.path;
          if (field.allowed_operator_codes && field.allowed_operator_codes.indexOf(cond.operator_code) < 0) {
            cond.operator_code = "";
          }
          render();
        },
        onClear: function () {
          cond.field_path = "";
          cond.operator_code = "";
          renderSummary();
        },
      }));

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
        var scopePicker = actionScopePicker(a);
        if (scopePicker) row.appendChild(scopePicker);
        row.appendChild(actionFieldPicker(a));
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

      var pick = shopFieldPicker({
        placeholder: "Shop-Feld einfügen…",
        clearAfterSelect: true,
        onSelect: function (field) {
          markDirty();
          input.value = "{{ " + field.path + " }}";
          a.target_value = input.value;
          renderSummary();
        },
      });
      pick.style.display = isVar ? "" : "none";
      wrap.appendChild(pick);
      return wrap;
    }

    // Searchable pickers -------------------------------------------------
    // The source list comes from the bridge's current model metadata.  The
    // GraphQL list is fetched from the Microtech API's live schema.
    function searchablePicker(config) {
      config = config || {};
      var wrap = el("span", "re-ac-wrap");
      var input = el("input", "re-ac-input");
      input.type = "text";
      input.placeholder = config.placeholder || "Feld suchen…";
      input.autocomplete = "off";
      input.setAttribute("role", "combobox");
      input.setAttribute("aria-autocomplete", "list");
      input.setAttribute("aria-expanded", "false");
      var results = el("div", "re-ac-results");
      results.setAttribute("role", "listbox");
      results.style.display = "none";
      wrap.appendChild(input);
      wrap.appendChild(results);

      var items = config.items || [];
      var selectedValue = config.value == null ? "" : String(config.value);
      var activeIndex = -1;
      var matches = [];
      var emptyText = config.emptyText || "Keine passenden Felder.";

      function itemValue(item) { return String(config.itemValue(item)); }
      function itemLabel(item) { return config.itemLabel(item) || itemValue(item); }
      function itemMeta(item) { return config.itemMeta ? config.itemMeta(item) : ""; }
      function itemTitle(item) { return config.itemTitle ? config.itemTitle(item) : itemLabel(item); }
      function setInputForSelectedValue() {
        for (var i = 0; i < items.length; i++) {
          if (itemValue(items[i]) === selectedValue) {
            input.value = itemLabel(items[i]);
            input.title = itemTitle(items[i]);
            return;
          }
        }
        input.value = config.initialText || "";
        input.title = config.initialTitle || input.value;
      }
      function filter(term) {
        term = String(term || "").trim().toLowerCase();
        return items.filter(function (item) {
          if (!term) return true;
          return String(config.searchText(item) || "").toLowerCase().indexOf(term) >= 0;
        }).slice(0, 60);
      }
      function choose(item) {
        selectedValue = itemValue(item);
        input.value = itemLabel(item);
        input.title = itemTitle(item);
        results.style.display = "none";
        input.setAttribute("aria-expanded", "false");
        if (typeof config.onSelect === "function") config.onSelect(item);
        if (config.clearAfterSelect) {
          selectedValue = "";
          input.value = "";
        }
      }
      function renderResults(term) {
        results.innerHTML = "";
        matches = filter(term);
        activeIndex = -1;
        if (!items.length) {
          results.appendChild(el("div", "re-ac-empty", emptyText));
          results.style.display = "";
          input.setAttribute("aria-expanded", "true");
          return;
        }
        if (!matches.length) {
          results.appendChild(el("div", "re-ac-empty", "Keine passenden Felder."));
          results.style.display = "";
          input.setAttribute("aria-expanded", "true");
          return;
        }
        matches.forEach(function (item, index) {
          var row = el("button", "re-ac-item");
          row.type = "button";
          row.setAttribute("role", "option");
          row.appendChild(el("span", "re-ac-name", itemLabel(item)));
          var meta = itemMeta(item);
          if (meta) row.appendChild(el("span", "re-ac-meta", " · " + meta));
          row.addEventListener("mousedown", function (ev) {
            ev.preventDefault();
            choose(item);
          });
          row.addEventListener("mouseenter", function () { activeIndex = index; });
          results.appendChild(row);
        });
        results.style.display = "";
        input.setAttribute("aria-expanded", "true");
      }
      function closeResults() {
        results.style.display = "none";
        input.setAttribute("aria-expanded", "false");
      }
      function setActive(index) {
        for (var i = 0; i < results.children.length; i++) {
          results.children[i].classList.toggle("re-ac-active", i === index);
        }
      }

      setInputForSelectedValue();
      input.addEventListener("input", function () {
        if (selectedValue) {
          selectedValue = "";
          input.title = "";
          if (typeof config.onClear === "function") config.onClear();
        }
        renderResults(input.value);
      });
      input.addEventListener("focus", function () { renderResults(input.value); });
      input.addEventListener("blur", function () { setTimeout(closeResults, 150); });
      input.addEventListener("keydown", function (event) {
        if (event.key === "ArrowDown" && matches.length) {
          event.preventDefault();
          activeIndex = Math.min(activeIndex + 1, matches.length - 1);
          setActive(activeIndex);
        } else if (event.key === "ArrowUp" && matches.length) {
          event.preventDefault();
          activeIndex = Math.max(activeIndex - 1, 0);
          setActive(activeIndex);
        } else if (event.key === "Enter" && activeIndex >= 0 && matches[activeIndex]) {
          event.preventDefault();
          choose(matches[activeIndex]);
        } else if (event.key === "Escape") {
          closeResults();
        }
      });

      return {
        element: wrap,
        input: input,
        setItems: function (newItems) {
          items = newItems || [];
          setInputForSelectedValue();
          if (document.activeElement === input) renderResults(input.value);
        },
        setEmptyText: function (text) {
          emptyText = text || emptyText;
          if (document.activeElement === input) renderResults(input.value);
        },
      };
    }

    function shopFieldPicker(config) {
      config = config || {};
      var selectedField = fieldByPath(config.value || "");
      var picker = searchablePicker({
        value: config.value || "",
        initialText: selectedField ? shopFieldDisplay(selectedField) : (config.value || ""),
        initialTitle: selectedField ? [shopFieldDisplay(selectedField), selectedField.value_kind, selectedField.hint].filter(Boolean).join(" · ") : "",
        placeholder: config.placeholder || "Shop-Feld suchen (Name oder Pfad)…",
        items: fieldsForContext(),
        itemValue: function (field) { return field.path; },
        itemLabel: function (field) { return shopFieldDisplay(field); },
        itemMeta: function (field) {
          return field.path + (field.value_kind ? " · " + field.value_kind : "") + (field.hint ? " — " + field.hint : "");
        },
        itemTitle: function (field) {
          return [shopFieldDisplay(field), field.value_kind, field.hint].filter(Boolean).join(" · ");
        },
        searchText: function (field) {
          return [field.path, field.label, field.hint, field.example, field.value_kind].join(" ");
        },
        onSelect: config.onSelect,
        onClear: config.onClear,
        clearAfterSelect: !!config.clearAfterSelect,
      });
      return picker.element;
    }

    function actionScopePicker(action) {
      var scopes = graphqlScopesForCurrentTrigger();
      if (!scopes.length) return null;
      var wrap = el("span", "re-scope-control");
      var select = el("select");
      select.title = "Zielbereich";
      var current = action.target_scope || "customer";
      scopes.forEach(function (scope) {
        select.appendChild(opt(scope.code, scope.label || scope.code, current === scope.code));
      });
      select.addEventListener("change", function () {
        markDirty();
        action.target_scope = select.value;
        action.graphql_field = "";
        action.graphql_field_label = "";
        reconcileActionTargets();
        render();
      });
      wrap.appendChild(select);
      return wrap;
    }

    function actionFieldPicker(action) {
      if (actionTargetKind(action) === "graphql") return graphqlFieldPicker(action);
      if (actionTargetKind(action) === "dataset") return datasetFieldPicker(action);
      return searchablePicker({
        placeholder: "Zuerst einen Trigger wählen…",
        emptyText: "Für diesen Trigger sind keine Zielfelder konfiguriert.",
        items: [],
        itemValue: function () { return ""; },
        itemLabel: function () { return ""; },
        searchText: function () { return ""; },
      }).element;
    }

    function graphqlFieldPicker(action) {
      var allowedTypes = graphqlInputTypesForCurrentTrigger(action);
      var picker = searchablePicker({
        value: action.graphql_field || "",
        initialText: action.graphql_field_label || graphqlFieldDisplayFromValue(action.graphql_field),
        initialTitle: action.graphql_field_label || action.graphql_field || "",
        placeholder: "API-Feld suchen (Name oder Typ)…",
        emptyText: "API-Felder werden geladen…",
        items: [],
        itemValue: function (item) { return item.value; },
        itemLabel: function (item) { return graphqlFieldDisplay(item); },
        itemMeta: function (item) {
          return item.typeLabel + (item.description ? " — " + item.description : "");
        },
        itemTitle: function (item) {
          return [graphqlFieldDisplay(item), item.typeLabel, item.description].filter(Boolean).join(" · ");
        },
        searchText: function (item) {
          return [item.name, item.value, item.type, item.typeLabel, item.description].join(" ");
        },
        onSelect: function (item) {
          markDirty();
          action.graphql_field = item.value;
          action.graphql_field_label = graphqlFieldDisplay(item);
          action.dataset_field_id = null;
          action.dataset_field_label = "";
          renderSummary();
        },
        onClear: function () {
          action.graphql_field = "";
          action.graphql_field_label = "";
          renderSummary();
        },
      });
      var control = el("span", "re-ac-control");
      control.appendChild(picker.element);
      var refresh = el("button", "re-btn re-ac-refresh", "↻");
      refresh.type = "button";
      refresh.title = "Felder direkt aus der Microtech-API neu laden";
      refresh.setAttribute("aria-label", refresh.title);
      control.appendChild(refresh);
      var sourceHint = el("span", "re-ac-source");
      control.appendChild(sourceHint);

      function load(refreshFromApi) {
        picker.setEmptyText(refreshFromApi ? "API-Felder werden aktualisiert…" : "API-Felder werden geladen…");
        loadGraphqlFields(GQLGROUP_URL, refreshFromApi).then(function (groups) {
          var flat = [];
          groups.forEach(function (group) {
            if (allowedTypes.indexOf(group.input_type) < 0) return;
            (group.fields || []).forEach(function (field) {
              flat.push({
                value: group.input_type + "." + field.name,
                name: field.name,
                type: group.input_type,
                typeLabel: group.label || group.input_type,
                description: field.description || "",
              });
            });
          });
          picker.setItems(flat);
          picker.setEmptyText("Keine passenden API-Felder.");
          sourceHint.textContent = GQLFIELD_SOURCE === "fallback"
            ? "Fallback-Liste – API nicht erreichbar"
            : (GQLFIELD_SOURCE === "introspection" ? "Microtech-API" : "API nicht erreichbar");
        });
      }
      refresh.addEventListener("click", function () { load(true); });
      load(false);
      return control;
    }

    function datasetFieldPicker(action) {
      var picker = searchablePicker({
        value: action.dataset_field_id || "",
        initialText: action.dataset_field_label || (action.dataset_field_id ? "Gewähltes Microtech-Feld" : ""),
        initialTitle: action.dataset_field_label || "",
        placeholder: "Microtech-Feld suchen (Name, Bereich oder Kurzname)…",
        emptyText: "Microtech-Felder werden geladen…",
        items: [],
        itemValue: function (item) { return item.id; },
        itemLabel: function (item) { return datasetFieldDisplay(item); },
        itemMeta: function (item) {
          return item.datasetName + "." + item.fieldName + (item.fieldType ? " · " + item.fieldType : "");
        },
        itemTitle: function (item) { return datasetFieldTitle(item); },
        searchText: function (item) {
          return [item.datasetName, item.sourceIdentifier, item.fieldName, item.label, item.fieldType].join(" ");
        },
        onSelect: function (item) {
          markDirty();
          action.dataset_field_id = item.id;
          action.dataset_field_label = datasetFieldDisplay(item);
          action.graphql_field = "";
          action.graphql_field_label = "";
          renderSummary();
        },
        onClear: function () {
          action.dataset_field_id = null;
          action.dataset_field_label = "";
          renderSummary();
        },
      });
      loadDatasetFieldsForPicker();

      function loadDatasetFieldsForPicker() {
        loadDatasetFields(DSGROUP_URL)
          .then(function (datasets) {
            var flat = [];
            (datasets || []).forEach(function (dataset) {
              (dataset.fields || []).forEach(function (field) {
                flat.push({
                  id: field.id,
                  fieldName: field.field_name,
                  label: field.label || field.field_name,
                  fieldType: field.field_type || "",
                  datasetName: dataset.name || "Microtech",
                  sourceIdentifier: dataset.source_identifier || "",
                });
              });
            });
            picker.setItems(flat);
            picker.setEmptyText("Keine verfügbaren Microtech-Felder.");
          })
          .catch(function () { picker.setEmptyText("Microtech-Felder konnten nicht geladen werden."); });
      }
      return picker.element;
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
        if (a.action_type === "set_field") {
          var scopeLabel = "";
          var scopes = graphqlScopesForCurrentTrigger();
          for (var i = 0; i < scopes.length; i++) {
            if (scopes[i].code === (a.target_scope || "customer")) {
              scopeLabel = (scopes[i].label || scopes[i].code) + ": ";
              break;
            }
          }
          return "setze " + scopeLabel + (a.graphql_field_label || a.graphql_field || a.dataset_field_label || "Feld") + " = " + (a.target_value || "?");
        }
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
          return { action_type: a.action_type,
                   target_scope: a.target_scope || "customer",
                   graphql_field: a.action_type === "set_field" ? (a.graphql_field || "") : "",
                   dataset_field_id: a.action_type === "set_field" ? (a.dataset_field_id || null) : null,
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
  function newAction() {
    return {
      action_type: "set_field", target_scope: "customer", graphql_field: "", graphql_field_label: "",
      dataset_field_id: null, dataset_field_label: "", target_value: "",
    };
  }
  function normalizeState(data) {
    var s = data ? JSON.parse(JSON.stringify(data)) : {};
    if (!s.actions) s.actions = [];
    s.actions.forEach(function (action) {
      if (!action.target_scope) action.target_scope = "customer";
    });
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
