(function () {
  "use strict";

  const LOADER_ACTIVE_CLASS = "gc-admin-button-loader-active";
  const LOADER_INLINE_CLASS = "gc-admin-button-loader-inline";
  const SUBMIT_BUTTON_SELECTOR = 'button[type="submit"]';

  function createLoaderElement() {
    const loader = document.createElement("span");
    loader.className = LOADER_INLINE_CLASS;
    loader.setAttribute("aria-hidden", "true");
    return loader;
  }

  function getInsertionReference(element) {
    let child = element.firstElementChild;
    let lastLeadingIcon = null;

    while (child && child.classList.contains("material-symbols-outlined")) {
      lastLeadingIcon = child;
      child = child.nextElementSibling;
    }

    return lastLeadingIcon;
  }

  function insertLoaderElement(element) {
    if (element.querySelector(`.${LOADER_INLINE_CLASS}`)) {
      return;
    }

    const loader = createLoaderElement();
    const reference = getInsertionReference(element);

    if (reference) {
      reference.insertAdjacentElement("afterend", loader);
      return;
    }

    element.prepend(loader);
  }

  function activateButtonLoader(element) {
    if (!element || element.dataset.gcAdminButtonLoaderActive === "true") {
      return;
    }

    element.dataset.gcAdminButtonLoaderActive = "true";
    insertLoaderElement(element);
    element.classList.add(LOADER_ACTIVE_CLASS);
    element.setAttribute("aria-busy", "true");

    if ("disabled" in element) {
      element.disabled = true;
    }
  }

  function shouldHandleSubmitter(submitter) {
    return Boolean(
      submitter &&
      submitter.matches(SUBMIT_BUTTON_SELECTOR) &&
      submitter.dataset.adminLoader !== "off"
    );
  }

  function shouldHandleLink(link, event) {
    if (!link || link.dataset.adminLoader === "off") {
      return false;
    }

    const href = link.getAttribute("href");
    if (!href || href === "#" || href.startsWith("javascript:")) {
      return false;
    }

    if (link.hasAttribute("download") || (link.target && link.target !== "_self")) {
      return false;
    }

    if (event.defaultPrevented || event.button !== 0) {
      return false;
    }

    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return false;
    }

    if (link.classList.contains("addlink")) {
      return true;
    }

    if (link.closest("#submit-row")) {
      return true;
    }

    if (link.closest(".field-actions_holder")) {
      return true;
    }

    if (link.classList.contains("cursor-pointer")) {
      return true;
    }

    return false;
  }

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }

    const submitter = event.submitter || document.activeElement;
    if (!shouldHandleSubmitter(submitter)) {
      return;
    }

    activateButtonLoader(submitter);
  }, true);

  document.addEventListener("click", function (event) {
    const link = event.target.closest("a");
    if (!shouldHandleLink(link, event)) {
      return;
    }

    activateButtonLoader(link);
  }, true);

  window.GCAdminButtonLoader = {
    activate: activateButtonLoader,
  };
})();
