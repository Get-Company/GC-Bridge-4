(function () {
  "use strict";

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

  function setLoading(control, isLoading, message) {
    const loadingEl = control.querySelector(".js-sw-state-loading");
    if (!loadingEl) {
      return;
    }
    if (isLoading) {
      loadingEl.style.display = "inline";
      loadingEl.textContent = message || "Wird geladen...";
    } else {
      loadingEl.style.display = "none";
      loadingEl.textContent = "";
    }
  }

  function setBusy(control, isBusy) {
    control.dataset.busy = isBusy ? "1" : "0";
    const select = control.querySelector(".js-sw-state-select");
    if (select) {
      select.disabled = !!isBusy;
    }
  }

  function isBusy(control) {
    return control.dataset.busy === "1";
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

    try {
      setLoading(control, true, "Optionen laden...");
      setBusy(control, true);
      const response = await fetch(url.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        return;
      }

      clearOptions(select);
      appendOption(select, "", "Status waehlen...");
      (data.actions || []).forEach(function (item) {
        appendOption(select, item.action || "", item.label || item.action || "");
      });
      control.dataset.loaded = "1";
    } catch (error) {
      console.error("Could not load Shopware state transitions", error);
    } finally {
      setLoading(control, false);
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

    setBusy(control, true);
    setLoading(control, true, "Speichern...");
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
        window.alert(message);
        return;
      }

      updateCurrentStates(control, payload);
      select.value = "";
    } catch (error) {
      console.error("Could not set Shopware state", error);
      window.alert("Status konnte nicht gesetzt werden.");
    } finally {
      setLoading(control, false);
      setBusy(control, false);
    }
  }

  function bindControl(control) {
    const select = control.querySelector(".js-sw-state-select");
    if (!select) {
      return;
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
    document.querySelectorAll(".js-sw-state-control").forEach(function (control) {
      bindControl(control);
    });
  });
})();
