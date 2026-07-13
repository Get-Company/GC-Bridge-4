(function () {
  "use strict";

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function saveVirtualStock(input) {
    const previousValue = input.dataset.previousValue ?? input.value;
    input.disabled = true;
    input.setCustomValidity("");

    try {
      const response = await fetch(input.dataset.virtualStockUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-CSRFToken": csrfToken(),
        },
        body: new URLSearchParams({ virtual_stock: input.value }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Virtueller Bestand konnte nicht gespeichert werden.");
      }

      input.value = payload.virtual_stock || "";
      input.dataset.previousValue = input.value;
      const stockCell = input.closest("tr")?.querySelector(".field-available_stock");
      if (stockCell) {
        stockCell.textContent = String(payload.available_stock);
      }
    } catch (error) {
      input.value = previousValue;
      input.setCustomValidity(error.message);
      input.reportValidity();
    } finally {
      input.disabled = false;
    }
  }

  document.addEventListener("focusin", function (event) {
    const input = event.target.closest("input[data-virtual-stock-url]");
    if (input) {
      input.dataset.previousValue = input.value;
    }
  });

  document.addEventListener("change", function (event) {
    const input = event.target.closest("input[data-virtual-stock-url]");
    if (input) {
      saveVirtualStock(input);
    }
  });
})();
