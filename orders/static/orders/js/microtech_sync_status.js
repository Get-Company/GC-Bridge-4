(function () {
  "use strict";

  var ACTIVE_STATUSES = { pending: true, running: true, waiting: true };
  var POLL_MS = 2000;

  function text(value, fallback) {
    if (value === null || value === undefined || String(value).trim() === "") {
      return fallback || "";
    }
    return String(value).trim();
  }

  function setHidden(element, hidden) {
    if (!element) {
      return;
    }
    if (hidden) {
      element.classList.add("hidden");
    } else {
      element.classList.remove("hidden");
    }
  }

  function render(container, payload) {
    var label = container.querySelector(".js-microtech-sync-label");
    var beleg = container.querySelector(".js-microtech-sync-beleg");
    var spinner = container.querySelector(".js-microtech-sync-spinner");

    var status = text(payload.status_display, "-");
    if (label) {
      label.textContent = status;
    }
    if (beleg) {
      beleg.textContent = text(payload.erp_order_id, "-");
    }
    setHidden(spinner, !payload.is_active && !ACTIVE_STATUSES[payload.status]);
  }

  function poll(container) {
    var url = container.getAttribute("data-status-url");
    if (!url) {
      return;
    }

    fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        if (!payload || !payload.ok) {
          throw new Error((payload && payload.error) || "Microtech-Sync konnte nicht geladen werden.");
        }
        render(container, payload);
        if (payload.is_active || ACTIVE_STATUSES[payload.status]) {
          window.setTimeout(function () { poll(container); }, POLL_MS);
        }
      })
      .catch(function (error) {
        window.console.warn(error.message || String(error));
        window.setTimeout(function () { poll(container); }, POLL_MS * 3);
      });
  }

  function init() {
    document.querySelectorAll(".js-microtech-sync-status[data-status-url]").forEach(function (container) {
      if (container.getAttribute("data-microtech-sync-bound") === "1") {
        return;
      }
      container.setAttribute("data-microtech-sync-bound", "1");
      poll(container);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
