(function () {
    "use strict";

    var activeEditor = null;

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

        editor.addEventListener("focus", function () {
            activeEditor = editor;
        });
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

    function setupLivePreview() {
        var btn = document.querySelector("[data-live-preview]");
        if (!btn || btn.dataset.documentEnhanced === "1") return;
        btn.dataset.documentEnhanced = "1";
        btn.addEventListener("click", function () {
            var url = btn.dataset.livePreview;
            var html = (document.querySelector('textarea[data-document-editor="html"]') || {}).value || "";
            var css = (document.querySelector('textarea[data-document-editor="css"]') || {}).value || "";
            var jinja2Checkbox = document.querySelector('[name="use_jinja2"]');
            var jinja2 = jinja2Checkbox && jinja2Checkbox.checked ? "true" : "false";
            var csrf = (document.querySelector('[name="csrfmiddlewaretoken"]') || {}).value || "";
            var label = btn.textContent;
            btn.textContent = "Laden…";
            btn.disabled = true;
            fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: new URLSearchParams({
                    html_content: html,
                    css_content: css,
                    use_jinja2: jinja2,
                    csrfmiddlewaretoken: csrf,
                }).toString(),
            })
            .then(function (resp) { return resp.text(); })
            .then(function (text) {
                var win = window.open("", "_blank");
                if (win) { win.document.write(text); win.document.close(); }
            })
            .catch(function (e) { alert("Fehler: " + e.message); })
            .finally(function () { btn.textContent = label; btn.disabled = false; });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("trix-editor").forEach(setupTrixEditor);
        document.querySelectorAll('textarea[data-document-editor="html"], textarea[data-document-editor="css"]').forEach(setupTextarea);
        setupTokenButtons();
        setupLivePreview();
    });
})();
