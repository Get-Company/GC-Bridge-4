(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Static fallback: standard Shopware 6 state machine graph.
  // Used when localStorage is empty and the backend is unreachable.
  // ---------------------------------------------------------------------------
  var STATIC_TRANSITIONS = {
    order: {
      open:        ["process", "cancel"],
      in_progress: ["complete", "cancel"],
      completed:   ["reopen"],
      cancelled:   ["reopen"],
    },
    delivery: {
      open:               ["ship", "ship_partially", "cancel"],
      shipped:            ["retour", "retour_partially", "reopen"],
      shipped_partially:  ["ship", "retour", "retour_partially", "reopen"],
      returned:           ["reopen"],
      returned_partially: ["retour", "retour_partially", "reopen"],
      cancelled:          ["reopen"],
    },
    payment: {
      open:               ["do_pay", "paid", "paid_partially", "authorize", "remind", "cancel", "fail"],
      in_progress:        ["paid", "paid_partially", "remind", "cancel", "fail"],
      authorized:         ["paid", "paid_partially", "refund", "refund_partially", "cancel"],
      paid:               ["refund", "refund_partially", "reopen"],
      paid_partially:     ["paid", "paid_partially", "refund", "refund_partially", "reopen"],
      refunded:           ["reopen"],
      refunded_partially: ["paid", "paid_partially", "refund", "refund_partially", "reopen"],
      cancelled:          ["reopen"],
      failed:             ["reopen"],
      reminded:           ["paid", "paid_partially", "cancel", "fail"],
      chargeback:         ["reopen"],
    },
  };

  // ---------------------------------------------------------------------------
  // German labels — shared for state names and action names.
  // Actions are named after their resulting state (short & intuitive).
  // ---------------------------------------------------------------------------
  var LABELS = {
    // states / actions
    open:               "Offen",
    in_progress:        "In Bearbeitung",
    completed:          "Abgeschlossen",
    cancelled:          "Storniert",
    shipped:            "Versendet",
    shipped_partially:  "Teilw. versendet",
    returned:           "Retourniert",
    returned_partially: "Teilw. retourniert",
    paid:               "Bezahlt",
    paid_partially:     "Teilzahlung",
    authorized:         "Autorisiert",
    refunded:           "Erstattet",
    refunded_partially: "Teilerstattung",
    failed:             "Fehlgeschlagen",
    reminded:           "Gemahnt",
    chargeback:         "Rückbuchung",
    // action-only names (no matching state)
    process:            "In Bearbeitung",
    complete:           "Abschließen",
    cancel:             "Stornieren",
    reopen:             "Wieder öffnen",
    ship:               "Versenden",
    ship_partially:     "Teilversand",
    retour:             "Retoure",
    retour_partially:   "Teilretoure",
    do_pay:             "Bezahlen",
    authorize:          "Autorisieren",
    remind:             "Mahnen",
    refund:             "Erstatten",
    refund_partially:   "Teilerstattung",
    fail:               "Fehlgeschlagen",
  };

  function label(key) {
    return LABELS[key] || key.replace(/_/g, " ");
  }

  var LS_KEY = "sw_transitions_v1";

  // Active transition graph (static fallback or localStorage/API override).
  var SW_TRANSITIONS = STATIC_TRANSITIONS;

  // Load cached graph from localStorage.
  try {
    var stored = localStorage.getItem(LS_KEY);
    if (stored) {
      var parsed = JSON.parse(stored);
      if (parsed && typeof parsed === "object") {
        SW_TRANSITIONS = parsed;
      }
    }
  } catch (e) {}

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function ensureStyles() {
    if (document.getElementById("sw-state-control-styles")) {
      return;
    }
    var style = document.createElement("style");
    style.id = "sw-state-control-styles";
    style.textContent = [
      ".js-sw-state-select{transition:background-color .18s ease,color .18s ease,opacity .18s ease;}",
      ".js-sw-state-select.js-sw-state-disabled{background:#f3f4f6 !important;color:#6b7280 !important;opacity:.9;cursor:not-allowed;}",
      ".js-sw-state-progress-bar{animation:swStateBar 1.1s linear infinite;}",
      "@keyframes swStateBar{0%{transform:translateX(-130%);}100%{transform:translateX(360%);}}",
    ].join("");
    document.head.appendChild(style);
  }

  function getCsrfToken() {
    var name = "csrftoken=";
    var cookies = document.cookie ? document.cookie.split(";") : [];
    for (var i = 0; i < cookies.length; i++) {
      var cookie = cookies[i].trim();
      if (cookie.startsWith(name)) {
        return decodeURIComponent(cookie.substring(name.length));
      }
    }
    return "";
  }

  function clearOptions(select) {
    while (select.options.length > 0) {
      select.remove(0);
    }
  }

  function appendOption(select, value, label) {
    var option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  function setFeedback(control, message, kind) {
    var loadingEl = control.querySelector(".js-sw-state-loading");
    if (!loadingEl) {
      return;
    }
    var colorByKind = { info: "#6b7280", success: "#166534", error: "#b91c1c" };
    loadingEl.style.display = "inline";
    loadingEl.style.color = colorByKind[kind] || colorByKind.info;
    loadingEl.textContent = message || "";
  }

  function setProgress(control, isVisible) {
    var progressEl = control.querySelector(".js-sw-state-progress");
    if (!progressEl) return;
    progressEl.style.display = isVisible ? "block" : "none";
  }

  function setBusy(control, isBusy) {
    control.dataset.busy = isBusy ? "1" : "0";
    var select = control.querySelector(".js-sw-state-select");
    if (select) {
      select.disabled = !!isBusy;
      if (isBusy) {
        select.classList.add("js-sw-state-disabled");
      } else {
        select.classList.remove("js-sw-state-disabled");
      }
    }
  }

  function isBusy(control) {
    return control.dataset.busy === "1";
  }

  function startProgressMessages(control, messages) {
    var handles = [];
    messages.forEach(function (entry) {
      var handle = window.setTimeout(function () {
        setFeedback(control, entry.text, "info");
      }, entry.delayMs);
      handles.push(handle);
    });
    return handles;
  }

  function clearProgressMessages(handles) {
    (handles || []).forEach(function (handle) {
      window.clearTimeout(handle);
    });
  }

  // ---------------------------------------------------------------------------
  // Populate a select from the local transition graph.
  // ---------------------------------------------------------------------------

  function getActionsForControl(control) {
    var scope = control.dataset.scope;
    var currentState = control.dataset.currentState || "";
    var scopeMap = SW_TRANSITIONS[scope] || {};

    // Try exact match first, then case-insensitive.
    var actions = scopeMap[currentState];
    if (!actions && currentState) {
      var lower = currentState.toLowerCase();
      for (var key in scopeMap) {
        if (key.toLowerCase() === lower) {
          actions = scopeMap[key];
          break;
        }
      }
    }
    return actions || [];
  }

  function populateSelect(control, select) {
    var actions = getActionsForControl(control);
    clearOptions(select);
    if (actions.length === 0) {
      appendOption(select, "", "Keine Optionen verfügbar");
      select.disabled = true;
      select.classList.add("js-sw-state-disabled");
    } else {
      appendOption(select, "", "Status wählen…");
      actions.forEach(function (a) {
        appendOption(select, a, label(a));
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Fetch fresh transition graph from backend & cache in localStorage.
  // ---------------------------------------------------------------------------

  function getMetaUrl() {
    var el = document.querySelector("[data-transitions-meta-url]");
    return el ? el.dataset.transitionsMetaUrl : null;
  }

  async function fetchAndCacheTransitions() {
    var metaUrl = getMetaUrl();
    if (!metaUrl) return null;
    try {
      var response = await fetch(metaUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      var data = await response.json();
      if (data.ok && data.transitions) {
        SW_TRANSITIONS = data.transitions;
        try {
          localStorage.setItem(LS_KEY, JSON.stringify(data.transitions));
        } catch (e) {}
        return data.transitions;
      }
    } catch (e) {
      console.error("Could not fetch Shopware transition graph", e);
    }
    return null;
  }

  // Re-populate every control on the page (called after a refresh).
  function repopulateAllControls() {
    document.querySelectorAll(".js-sw-state-control").forEach(function (control) {
      var select = control.querySelector(".js-sw-state-select");
      if (select && !isBusy(control)) {
        populateSelect(control, select);
      }
    });
  }

  // Public: called by the "Übergänge aktualisieren" button.
  window.swRefreshTransitions = async function (btn) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Wird geladen…";
    }
    var result = await fetchAndCacheTransitions();
    if (btn) {
      btn.disabled = false;
      btn.textContent = result ? "Übergänge aktualisiert ✓" : "Fehler beim Laden";
      window.setTimeout(function () {
        if (btn) btn.textContent = "Übergänge aktualisieren";
      }, 3000);
    }
    if (result) {
      repopulateAllControls();
    }
  };

  // ---------------------------------------------------------------------------
  // State update after a successful set-state response.
  // ---------------------------------------------------------------------------

  function updateCurrentStates(control, payload) {
    var container = control.closest("tbody") || document;
    var statesByScope = {
      order:    payload.order_state,
      payment:  payload.payment_state,
      delivery: payload.shipping_state,
    };

    Object.keys(statesByScope).forEach(function (scope) {
      var state = statesByScope[scope];
      if (!state) return;

      var targetControl = container.querySelector(
        '.js-sw-state-control[data-scope="' + scope + '"]'
      );
      if (!targetControl) return;

      // Update display text.
      var currentEl = targetControl.querySelector(".js-sw-state-current");
      if (currentEl) currentEl.textContent = label(state);

      // Update data-current-state and repopulate options.
      targetControl.dataset.currentState = state;
      var select = targetControl.querySelector(".js-sw-state-select");
      if (select) {
        populateSelect(targetControl, select);
        setFeedback(targetControl, "Status aktualisiert.", "success");
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Send state-change request to backend / Shopware.
  // ---------------------------------------------------------------------------

  async function setState(control, select) {
    if (isBusy(control)) return;

    var setUrl = control.dataset.setUrl;
    var scope = control.dataset.scope;
    var action = select.value;
    if (!setUrl || !scope || !action) return;

    var messageHandles = [];
    setBusy(control, true);
    setFeedback(control, "Speichern gestartet…", "info");
    setProgress(control, true);
    messageHandles = startProgressMessages(control, [
      { delayMs: 250,  text: "Status wird an Shopware gesendet…" },
      { delayMs: 900,  text: "Auf Antwort von Shopware warten…" },
      { delayMs: 1700, text: "Lokalen Status aktualisieren…" },
    ]);

    try {
      var response = await fetch(setUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ scope: scope, action: action }),
      });
      var payload = await response.json();

      if (!response.ok || !payload.ok) {
        // Fetch fresh transitions from backend so the user sees only valid options.
        var freshGraph = await fetchAndCacheTransitions();
        if (freshGraph) {
          repopulateAllControls();
          var currentState = control.dataset.currentState || "";
          var validActions = ((freshGraph[scope] || {})[currentState] || []);
          var validStr = validActions.length
            ? validActions.join(", ")
            : "keine";
          setFeedback(
            control,
            "Nicht möglich. Verfügbare Übergänge: " + validStr,
            "error"
          );
        } else {
          var message = (payload && payload.error) || "Status konnte nicht gesetzt werden.";
          setFeedback(control, message, "error");
        }
        return;
      }

      updateCurrentStates(control, payload);
      select.value = "";
      setFeedback(control, "Status erfolgreich gespeichert.", "success");
    } catch (error) {
      console.error("Could not set Shopware state", error);
      setFeedback(control, "Netzwerkfehler beim Speichern.", "error");
    } finally {
      clearProgressMessages(messageHandles);
      setProgress(control, false);
      setBusy(control, false);
    }
  }

  // ---------------------------------------------------------------------------
  // Bind a single control: populate options + wire change event.
  // ---------------------------------------------------------------------------

  function bindControl(control) {
    var select = control.querySelector(".js-sw-state-select");
    if (!select) return;

    // Populate immediately from local graph.
    if (!select.disabled) {
      populateSelect(control, select);
      setFeedback(control, "Bereit. Status wählen.", "info");
    } else {
      setFeedback(control, "Keine API-ID vorhanden.", "error");
      return;
    }

    select.addEventListener("change", function () {
      if (isBusy(control)) return;
      setState(control, select);
    });
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    ensureStyles();
    document.querySelectorAll(".js-sw-state-control").forEach(function (control) {
      bindControl(control);
    });
  });
})();
