(function () {
  "use strict";

  function ensureStyles() {
    if (document.getElementById("sw-state-control-styles")) {
      return;
    }

    const style = document.createElement("style");
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
    const name = "csrftoken=";
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (let i = 0; i < cookies.length; i += 1) {
      const cookie = cookies[i].trim();
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

  function setFeedback(control, message, kind) {
    const loadingEl = control.querySelector(".js-sw-state-loading");
    if (!loadingEl) {
      return;
    }

    const colorByKind = {
      info: "#6b7280",
      success: "#166534",
      error: "#b91c1c",
    };

    loadingEl.style.display = "inline";
    loadingEl.style.color = colorByKind[kind] || colorByKind.info;
    loadingEl.textContent = message || "";
  }

  function setProgress(control, isVisible) {
    const progressEl = control.querySelector(".js-sw-state-progress");
    if (!progressEl) {
      return;
    }
    progressEl.style.display = isVisible ? "block" : "none";
  }

  function setBusy(control, isBusy) {
    control.dataset.busy = isBusy ? "1" : "0";
    const select = control.querySelector(".js-sw-state-select");
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
    const handles = [];
    messages.forEach(function (entry) {
      const handle = window.setTimeout(function () {
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

  function appendOption(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  async function loadOptions(control, select) {
    if (isBusy(control)) {
      return;
    }
    if (control.dataset.loaded === "1") {
      return;
    }

    const baseUrl = control.dataset.optionsUrl;
    const scope = control.dataset.scope;
    if (!baseUrl || !scope) {
      return;
    }

    const url = new URL(baseUrl, window.location.origin);
    url.searchParams.set("scope", scope);
    let messageHandles = [];

    try {
      setFeedback(control, "Anfrage gestartet...", "info");
      setProgress(control, true);
      setBusy(control, true);
      messageHandles = startProgressMessages(control, [
        { delayMs: 250, text: "Optionen werden bei Shopware angefordert..." },
        { delayMs: 900, text: "Auf Antwort von Shopware warten..." },
      ]);

      const response = await fetch(url.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        setFeedback(control, "Optionen konnten nicht geladen werden.", "error");
        return;
      }

      clearOptions(select);
      appendOption(select, "", "Status waehlen...");
      (data.actions || []).forEach(function (item) {
        appendOption(select, item.action || "", item.label || item.action || "");
      });
      control.dataset.loaded = "1";
      setFeedback(control, "Optionen geladen. Bitte neuen Status waehlen.", "success");
    } catch (error) {
      console.error("Could not load Shopware state transitions", error);
      setFeedback(control, "Netzwerkfehler beim Laden der Optionen.", "error");
    } finally {
      clearProgressMessages(messageHandles);
      setProgress(control, false);
      setBusy(control, false);
    }
  }

  function updateCurrentStates(control, payload) {
    const container = control.closest("tr") || document;
    const statesByScope = {
      order: payload.order_state,
      payment: payload.payment_state,
      delivery: payload.shipping_state,
    };

    Object.keys(statesByScope).forEach(function (scope) {
      const state = statesByScope[scope];
      if (!state) {
        return;
      }
      const targetControl = container.querySelector('.js-sw-state-control[data-scope="' + scope + '"]');
      if (!targetControl) {
        return;
      }
      const currentEl = targetControl.querySelector(".js-sw-state-current");
      if (currentEl) {
        currentEl.textContent = state;
      }
      targetControl.dataset.loaded = "0";
    });
  }

  async function setState(control, select) {
    if (isBusy(control)) {
      return;
    }
    const setUrl = control.dataset.setUrl;
    const scope = control.dataset.scope;
    const action = select.value;
    if (!setUrl || !scope || !action) {
      return;
    }

    let messageHandles = [];
    setBusy(control, true);
    setFeedback(control, "Speichern gestartet...", "info");
    setProgress(control, true);
    messageHandles = startProgressMessages(control, [
      { delayMs: 250, text: "Status wird an Shopware gesendet..." },
      { delayMs: 900, text: "Auf Antwort von Shopware warten..." },
      { delayMs: 1700, text: "Lokalen Status aktualisieren..." },
    ]);

    try {
      const response = await fetch(setUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({
          scope: scope,
          action: action,
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        const message = (payload && payload.error) || "Status konnte nicht gesetzt werden.";
        setFeedback(control, message, "error");
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

  function bindControl(control) {
    const select = control.querySelector(".js-sw-state-select");
    if (!select) {
      return;
    }

    if (select.disabled) {
      setFeedback(control, "Keine API-ID vorhanden.", "error");
    } else {
      setFeedback(control, "Bereit. Status waehlen oder Optionen laden.", "info");
    }

    const load = function () {
      loadOptions(control, select);
    };

    select.addEventListener("focus", load);
    select.addEventListener("mousedown", load);
    select.addEventListener("change", function () {
      if (isBusy(control)) {
        return;
      }
      setState(control, select);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    ensureStyles();
    document.querySelectorAll(".js-sw-state-control").forEach(function (control) {
      bindControl(control);
    });
  });
})();
