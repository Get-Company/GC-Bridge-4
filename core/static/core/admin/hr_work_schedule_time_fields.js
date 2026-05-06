(function () {
  "use strict";

  function getTimeInput(target) {
    if (!(target instanceof HTMLInputElement)) {
      return null;
    }
    if (!target.classList.contains("vTimeField")) {
      return null;
    }
    return target;
  }

  function getClockLink(input) {
    return input.parentElement?.querySelector(".datetimeshortcuts a[id^='clocklink']") || null;
  }

  function getClockBox(link) {
    if (!link || !link.id) {
      return null;
    }
    const suffix = link.id.replace("clocklink", "");
    return document.getElementById(`clockbox${suffix}`);
  }

  function openClockChooser(input) {
    const link = getClockLink(input);
    const clockBox = getClockBox(link);
    if (!link || !clockBox) {
      return;
    }
    if (clockBox.style.display === "block") {
      return;
    }
    window.requestAnimationFrame(() => {
      link.click();
    });
  }

  document.addEventListener("pointerdown", (event) => {
    const input = getTimeInput(event.target);
    if (input) {
      openClockChooser(input);
    }
  });

  document.addEventListener("focusin", (event) => {
    const input = getTimeInput(event.target);
    if (input) {
      openClockChooser(input);
    }
  });
})();
