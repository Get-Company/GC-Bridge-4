(function () {
    "use strict";

    var activeEditor = null;

    function scopeCssSelectors(selectors, scope) {
        return selectors.split(",").map(function (selector) {
            var normalized = selector.trim();
            if (!normalized) {
                return normalized;
            }
            normalized = normalized.replace(/^(html|body)(?=\s|$)/, scope);
            return normalized.indexOf(scope) === 0 ? normalized : scope + " " + normalized;
        }).join(", ");
    }

    function scopeCss(css, scope) {
        var output = "";
        var offset = 0;
        while (offset < css.length) {
            var openingBrace = css.indexOf("{", offset);
            if (openingBrace === -1) {
                return output + css.slice(offset);
            }
            var header = css.slice(offset, openingBrace);
            var depth = 1;
            var cursor = openingBrace + 1;
            while (cursor < css.length && depth > 0) {
                if (css[cursor] === "{") {
                    depth += 1;
                } else if (css[cursor] === "}") {
                    depth -= 1;
                }
                cursor += 1;
            }
            if (depth !== 0) {
                return output + css.slice(offset);
            }
            var body = css.slice(openingBrace + 1, cursor - 1);
            var trimmedHeader = header.trim();
            if (
                trimmedHeader.indexOf("@media") === 0 ||
                trimmedHeader.indexOf("@supports") === 0 ||
                trimmedHeader.indexOf("@container") === 0 ||
                trimmedHeader.indexOf("@layer") === 0
            ) {
                output += header + "{" + scopeCss(body, scope) + "}";
            } else if (trimmedHeader.indexOf("@") === 0) {
                output += header + "{" + body + "}";
            } else {
                output += scopeCssSelectors(header, scope) + "{" + body + "}";
            }
            offset = cursor;
        }
        return output;
    }

    function applyWysiwygCss() {
        var cssField = document.querySelector('textarea[name="css_content"]');
        var editor = document.querySelector('trix-editor[data-document-editor="html"]');
        if (!cssField || !editor) {
            return;
        }
        var style = document.getElementById("document-wysiwyg-css");
        if (!style) {
            style = document.createElement("style");
            style.id = "document-wysiwyg-css";
            document.head.appendChild(style);
        }
        style.textContent = scopeCss(cssField.value || "", 'trix-editor[data-document-editor="html"]');
    }

    function makeButton(label, className) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = className || "document-editor-action";
        button.textContent = label;
        return button;
    }

    function toggleFullscreen(target, controls, button) {
        var isFullscreen = !target.classList.contains("is-document-fullscreen");
        target.classList.toggle("is-document-fullscreen", isFullscreen);
        controls.classList.toggle("is-document-fullscreen-controls", isFullscreen);
        document.body.classList.toggle("document-editor-fullscreen", isFullscreen);
        button.textContent = isFullscreen ? "Vollbild beenden" : "Vollbild";
    }

    function buildControls(shell) {
        var existing = shell.querySelector(".document-editor-controls");
        if (existing) {
            return existing;
        }
        var controls = document.createElement("div");
        controls.className = "document-editor-controls";
        var fullscreen = makeButton("Vollbild", "document-editor-action");
        fullscreen.addEventListener("click", function () {
            toggleFullscreen(shell, controls, fullscreen);
        });
        controls.appendChild(fullscreen);
        shell.insertBefore(controls, shell.firstChild);
        return controls;
    }

    function syncHtmlSource(source, input) {
        input.value = source.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function setupHtmlSourceToggle(editor, input, shell, controls) {
        var source = document.createElement("textarea");
        source.className = "document-html-source";
        source.setAttribute("aria-label", "HTML-Quellcode");
        source.setAttribute("spellcheck", "false");
        shell.appendChild(source);

        source.addEventListener("input", function () {
            syncHtmlSource(source, input);
        });

        var toggle = makeButton("HTML-Code", "document-editor-action");
        toggle.addEventListener("click", function () {
            var isSourceMode = shell.classList.contains("is-document-source-mode");
            if (!isSourceMode) {
                source.value = input.value || editor.value || "";
                shell.classList.add("is-document-source-mode");
                toggle.textContent = "Visueller Editor";
                window.setTimeout(function () { source.focus(); }, 0);
                return;
            }

            syncHtmlSource(source, input);
            if (editor.editor && typeof editor.editor.loadHTML === "function") {
                editor.editor.loadHTML(source.value);
            }
            shell.classList.remove("is-document-source-mode");
            toggle.textContent = "HTML-Code";
            editor.focus();
        });
        controls.insertBefore(toggle, controls.firstChild);
    }

    function setupTrixEditor(editor) {
        if (editor.dataset.documentEnhanced === "1") {
            return;
        }
        editor.dataset.documentEnhanced = "1";

        var wrapper = editor.closest("div");
        if (!wrapper) {
            return;
        }

        var shell = document.createElement("div");
        shell.className = "document-editor-shell";
        wrapper.parentNode.insertBefore(shell, wrapper);
        buildControls(shell);

        if (editor.toolbarElement) {
            shell.appendChild(editor.toolbarElement);
        }
        var inputId = editor.getAttribute("input");
        var input = inputId ? document.getElementById(inputId) : null;
        if (input) {
            shell.appendChild(input);
        }
        shell.appendChild(wrapper);
        if (input) {
            setupHtmlSourceToggle(editor, input, shell, buildControls(shell));
        }

        editor.addEventListener("focus", function () {
            activeEditor = editor;
        });
        applyWysiwygCss();
    }

    function setupTextarea(textarea) {
        if (textarea.dataset.documentEnhanced === "1") {
            return;
        }
        textarea.dataset.documentEnhanced = "1";
        var controls = document.createElement("div");
        controls.className = "document-editor-controls document-textarea-controls";
        var fullscreen = makeButton("Vollbild", "document-editor-action");
        fullscreen.addEventListener("click", function () {
            toggleFullscreen(textarea, controls, fullscreen);
        });
        controls.appendChild(fullscreen);
        textarea.parentNode.insertBefore(controls, textarea);
        textarea.addEventListener("focus", function () {
            activeEditor = textarea;
        });
    }

    function insertIntoTextarea(textarea, token) {
        var start = textarea.selectionStart || 0;
        var end = textarea.selectionEnd || 0;
        textarea.value = textarea.value.slice(0, start) + token + textarea.value.slice(end);
        textarea.focus();
        textarea.selectionStart = textarea.selectionEnd = start + token.length;
        textarea.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function insertToken(token) {
        if (!activeEditor) {
            activeEditor = document.querySelector('textarea[data-document-editor="html"]') ||
                document.querySelector('trix-editor[data-document-editor="html"]') ||
                document.querySelector('textarea[data-document-editor="css"]');
        }
        if (!activeEditor) {
            return;
        }
        if (activeEditor.tagName && activeEditor.tagName.toLowerCase() === "trix-editor" && activeEditor.editor) {
            activeEditor.editor.insertString(token);
            activeEditor.focus();
            return;
        }
        if (activeEditor.tagName && activeEditor.tagName.toLowerCase() === "textarea") {
            insertIntoTextarea(activeEditor, token);
        }
    }

    function setupTokenButtons() {
        document.querySelectorAll(".js-document-token").forEach(function (button) {
            if (button.dataset.documentEnhanced === "1") {
                return;
            }
            button.dataset.documentEnhanced = "1";
            button.addEventListener("click", function () {
                insertToken(button.dataset.token || button.textContent || "");
            });
        });
    }

    document.addEventListener("trix-initialize", function (event) {
        setupTrixEditor(event.target);
    });

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("trix-editor").forEach(setupTrixEditor);
        document.querySelectorAll('textarea[data-document-editor="html"], textarea[data-document-editor="css"]').forEach(setupTextarea);
        var cssField = document.querySelector('textarea[name="css_content"]');
        if (cssField) {
            cssField.addEventListener("input", applyWysiwygCss);
        }
        applyWysiwygCss();
        setupTokenButtons();
    });
})();
