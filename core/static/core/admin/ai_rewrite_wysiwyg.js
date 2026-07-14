(function () {
  "use strict";

  const COLOR_ATTRIBUTES = {
    foregroundColor: "color",
    backgroundColor: "backgroundColor",
  };

  function configureColorAttributes() {
    if (!window.Trix) {
      return;
    }

    Object.entries(COLOR_ATTRIBUTES).forEach(function ([name, styleProperty]) {
      if (window.Trix.config.textAttributes[name]) {
        return;
      }

      window.Trix.config.textAttributes[name] = {
        styleProperty: styleProperty,
        inheritable: true,
        parser: function (element) {
          return element.style[styleProperty] || false;
        },
      };
    });
  }

  function restoreSelection(editor, selection) {
    if (selection) {
      editor.editor.setSelectedRange(selection);
    }
  }

  function createColorInput(editor, attribute, labelText, iconName) {
    const label = document.createElement("label");
    label.className = "flex cursor-pointer items-center gap-1 border-r border-base-200 px-2 dark:border-base-700";
    label.title = labelText;

    const icon = document.createElement("span");
    icon.className = "material-symbols-outlined text-base-500 dark:text-base-300";
    icon.textContent = iconName;
    icon.setAttribute("aria-hidden", "true");
    label.appendChild(icon);

    const input = document.createElement("input");
    input.type = "color";
    input.value = "#111827";
    input.title = labelText;
    input.setAttribute("aria-label", labelText);
    input.className = "h-6 w-6 cursor-pointer rounded border-0 bg-transparent p-0";
    label.appendChild(input);

    let selection = null;
    input.addEventListener("pointerdown", function () {
      selection = editor.editor.getSelectedRange();
    });
    input.addEventListener("change", function () {
      restoreSelection(editor, selection);
      editor.editor.activateAttribute(attribute, input.value);
      editor.focus();
    });

    return label;
  }

  function createClearColorsButton(editor) {
    const button = document.createElement("button");
    button.type = "button";
    button.title = "Text- und Hintergrundfarbe entfernen";
    button.setAttribute("aria-label", button.title);
    button.className = "cursor-pointer px-2 text-base-500 transition-colors hover:text-primary-600 dark:text-base-300";

    const icon = document.createElement("span");
    icon.className = "material-symbols-outlined";
    icon.textContent = "format_color_reset";
    icon.setAttribute("aria-hidden", "true");
    button.appendChild(icon);

    button.addEventListener("click", function () {
      const selection = editor.editor.getSelectedRange();
      restoreSelection(editor, selection);
      Object.keys(COLOR_ATTRIBUTES).forEach(function (attribute) {
        editor.editor.deactivateAttribute(attribute);
      });
      editor.focus();
    });

    return button;
  }

  function addColorControls(event) {
    const editor = event.target;
    const toolbar = editor.toolbarElement;
    if (!toolbar || toolbar.querySelector("[data-gc-ai-rewrite-color-tools]")) {
      return;
    }

    const textTools = toolbar.querySelector('[data-trix-button-group="text-tools"]');
    if (!textTools) {
      return;
    }

    const colorTools = document.createElement("div");
    colorTools.dataset.gcAiRewriteColorTools = "true";
    colorTools.dataset.trixButtonGroup = "color-tools";
    colorTools.className = "bg-white border border-base-200 border-md flex flex-row rounded-default shadow-xs shrink-0 dark:bg-base-900 dark:border-base-700";
    colorTools.appendChild(createColorInput(editor, "foregroundColor", "Textfarbe", "format_color_text"));
    colorTools.appendChild(createColorInput(editor, "backgroundColor", "Hintergrundfarbe", "format_color_fill"));
    colorTools.appendChild(createClearColorsButton(editor));
    textTools.insertAdjacentElement("afterend", colorTools);
  }

  document.addEventListener("trix-before-initialize", configureColorAttributes);
  document.addEventListener("trix-initialize", addColorControls);
})();
