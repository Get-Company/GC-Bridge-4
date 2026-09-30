(function () {
    "use strict";

    const page = document.querySelector(".tc-page");
    const stateElement = document.getElementById("telefon-time-control-state");
    if (!page || !stateElement) return;

    let state = JSON.parse(stateElement.textContent || "{}");
    const actionUrl = page.dataset.actionUrl;
    const chainElement = page.querySelector("[data-chain]");
    const detachedSection = page.querySelector("[data-detached]");
    const detachedGrid = page.querySelector("[data-detached-grid]");
    const healthElement = page.querySelector("[data-health]");
    const countElement = page.querySelector("[data-node-count]");
    const dialog = page.querySelector("[data-insert-dialog]");
    const insertForm = page.querySelector("[data-insert-form]");
    const toast = page.querySelector("[data-toast]");
    const weekdayLabels = {
        MONDAY: "Montag",
        TUESDAY: "Dienstag",
        WEDNESDAY: "Mittwoch",
        THURSDAY: "Donnerstag",
        FRIDAY: "Freitag",
        SATURDAY: "Samstag",
        SUNDAY: "Sonntag",
    };
    const monthNumbers = {
        Jan: "01",
        Feb: "02",
        Mar: "03",
        Apr: "04",
        May: "05",
        Jun: "06",
        Jul: "07",
        Aug: "08",
        Sep: "09",
        Oct: "10",
        Nov: "11",
        Dec: "12",
    };

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function getCookie(name) {
        const match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
        return match ? match.pop() : "";
    }

    function showToast(message, isError) {
        toast.textContent = message;
        toast.classList.toggle("tc-toast-error", !!isError);
        toast.hidden = false;
        window.clearTimeout(showToast.timeout);
        showToast.timeout = window.setTimeout(function () {
            toast.hidden = true;
        }, isError ? 7000 : 3500);
    }

    function setBusy(button, busy, busyLabel) {
        if (!button) return;
        if (busy) {
            button.dataset.originalText = button.innerHTML;
            button.innerHTML = '<span class="material-symbols-outlined">progress_activity</span>' + escapeHtml(busyLabel || "Speichern …");
            button.disabled = true;
        } else {
            button.innerHTML = button.dataset.originalText || button.innerHTML;
            button.disabled = false;
        }
    }

    function postAction(payload, button) {
        setBusy(button, true, "NFON wird aktualisiert …");
        return fetch(actionUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: JSON.stringify(payload),
        }).then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok || !data.ok) {
                    throw new Error(data.error || "NFON-Aktion fehlgeschlagen.");
                }
                return data;
            });
        }).finally(function () {
            setBusy(button, false);
        });
    }

    function formatDate(value) {
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return value;
        return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" }).format(parsed);
    }

    function formatWindow(node) {
        if (node.is_partial_day) {
            return node.from_time + "–" + node.to_time + " Uhr";
        }
        const fromDay = weekdayLabels[node.from_day] || node.from_day;
        const toDay = weekdayLabels[node.to_day] || node.to_day;
        const days = fromDay === toDay ? fromDay : fromDay + "–" + toDay;
        return days + " · " + node.from_time + "–" + node.to_time + " Uhr";
    }

    function outcomeText(node) {
        if (!node.outcomes || !node.outcomes.length) return "Kein Endziel";
        return node.outcomes.map(function (outcome) {
            const relation = outcome.rel === "destinationIfDenied" ? "bei Ausnahme" : "bei Treffer";
            return outcome.name + " (" + relation + ")";
        }).join(" · ");
    }

    function dateMarkup(node) {
        const denied = (node.denied_dates || []).map(function (value) {
            return '<span class="tc-date-chip">' + escapeHtml(formatDate(value)) + "</span>";
        });
        const allowed = (node.allowed_dates || []).map(function (value) {
            return '<span class="tc-date-chip tc-date-allowed" title="Als referralAllowed gespeichert">' + escapeHtml(formatDate(value)) + " erlaubt</span>";
        });
        return denied.concat(allowed).join("") || '<span class="tc-summary-value">Keine Ausnahmedaten</span>';
    }

    function nfonDateKey(value) {
        const text = String(value || "").trim();
        const isoMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (isoMatch) return isoMatch[1] + "-" + isoMatch[2] + "-" + isoMatch[3];
        const nfonMatch = text.match(/^([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})$/);
        if (!nfonMatch || !monthNumbers[nfonMatch[1]]) return "";
        return nfonMatch[3] + "-" + monthNumbers[nfonMatch[1]] + "-" + nfonMatch[2].padStart(2, "0");
    }

    function currentMoment() {
        const formatter = new Intl.DateTimeFormat("en-GB", {
            timeZone: state.time_zone || "Europe/Berlin",
            weekday: "long",
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            hourCycle: "h23",
        });
        const values = {};
        formatter.formatToParts(new Date()).forEach(function (part) {
            if (part.type !== "literal") values[part.type] = part.value;
        });
        return {
            date: values.year + "-" + values.month + "-" + values.day,
            weekday: String(values.weekday || "").toUpperCase(),
            time: values.hour + ":" + values.minute,
        };
    }

    function weekdayInRange(weekday, fromDay, toDay) {
        const weekdays = state.weekdays || Object.keys(weekdayLabels);
        const currentIndex = weekdays.indexOf(weekday);
        const fromIndex = weekdays.indexOf(fromDay);
        const toIndex = weekdays.indexOf(toDay);
        if (currentIndex < 0 || fromIndex < 0 || toIndex < 0) return false;
        if (fromIndex <= toIndex) return currentIndex >= fromIndex && currentIndex <= toIndex;
        return currentIndex >= fromIndex || currentIndex <= toIndex;
    }

    function nodeAllowsMoment(node, moment) {
        const deniedDates = (node.denied_dates || []).map(nfonDateKey);
        if (deniedDates.indexOf(moment.date) !== -1) return false;
        const allowedDates = (node.allowed_dates || []).map(nfonDateKey);
        if (allowedDates.indexOf(moment.date) !== -1) return true;

        const fromTime = node.from_time || "00:00";
        const toTime = node.to_time || "23:59";
        if (fromTime <= toTime) {
            return weekdayInRange(moment.weekday, node.from_day, node.to_day)
                && moment.time >= fromTime
                && moment.time <= toTime;
        }

        const weekdays = state.weekdays || Object.keys(weekdayLabels);
        const currentIndex = weekdays.indexOf(moment.weekday);
        const previousDay = currentIndex >= 0 ? weekdays[(currentIndex + weekdays.length - 1) % weekdays.length] : "";
        return (weekdayInRange(moment.weekday, node.from_day, node.to_day) && moment.time >= fromTime)
            || (weekdayInRange(previousDay, node.from_day, node.to_day) && moment.time <= toTime);
    }

    function inferredNextRelation(node) {
        if (node.next_relation) return node.next_relation;
        const outcomeRelations = (node.outcomes || []).map(function (outcome) { return outcome.rel; });
        if (node.next_id && outcomeRelations.length === 1) {
            return outcomeRelations[0] === "destinationIfAllowed" ? "destinationIfDenied" : "destinationIfAllowed";
        }
        return "";
    }

    function activeNodeId() {
        const moment = currentMoment();
        const chain = state.chain || [];
        const nodesById = {};
        chain.forEach(function (node) { nodesById[String(node.id)] = node; });
        const visited = {};
        let node = chain.length ? chain[0] : null;
        while (node && !visited[String(node.id)]) {
            visited[String(node.id)] = true;
            const relation = nodeAllowsMoment(node, moment) ? "destinationIfAllowed" : "destinationIfDenied";
            const outcomeMatches = (node.outcomes || []).some(function (outcome) {
                return outcome.rel === relation;
            });
            if (outcomeMatches) return String(node.id);
            let targetId = "";
            if (node.next_id && inferredNextRelation(node) === relation) {
                targetId = String(node.next_id);
            } else if (node.bypass_id && node.bypass_relation === relation) {
                targetId = String(node.bypass_id);
            }
            node = targetId ? nodesById[targetId] : null;
        }
        return "";
    }

    function updateActiveNodeHighlight() {
        const activeId = activeNodeId();
        page.querySelectorAll(".tc-node[data-node-id]").forEach(function (element) {
            const memberIds = String(element.dataset.nodeIds || element.dataset.nodeId || "").split(",");
            const isActive = activeId !== "" && memberIds.indexOf(activeId) !== -1;
            element.classList.toggle("tc-node-active", isActive);
            if (isActive) {
                element.setAttribute("aria-current", "true");
            } else {
                element.removeAttribute("aria-current");
            }
            const badge = element.querySelector("[data-active-badge]");
            if (badge) badge.hidden = !isActive;
        });
    }

    function toDateTimeLocal(value, time) {
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return "";
        const year = parsed.getFullYear();
        const month = String(parsed.getMonth() + 1).padStart(2, "0");
        const day = String(parsed.getDate()).padStart(2, "0");
        return year + "-" + month + "-" + day + "T" + (time || "00:00");
    }

    function dateTimeRow(value) {
        return [
            '<div class="tc-datetime-row">',
            '  <input type="datetime-local" name="trigger_datetime" required value="' + escapeHtml(value || "") + '">',
            '  <button type="button" class="tc-remove-datetime" data-remove-datetime aria-label="Datum entfernen" title="Datum entfernen">&times;</button>',
            "</div>",
        ].join("");
    }

    function dateSelectorMarkup(values, fromTime) {
        const dateValues = (values || []).map(function (value) {
            return toDateTimeLocal(value, fromTime);
        }).filter(Boolean);
        if (!dateValues.length) dateValues.push("");
        return [
            '<div class="tc-field tc-field-wide tc-date-selector" data-date-selector>',
            '  <div class="tc-date-selector-head"><span>Auslösedatum</span><select name="date_mode" data-date-mode><option value="single">Einzeltermine</option><option value="range">Zeitraum</option></select></div>',
            '  <div data-date-single><div class="tc-datetime-list" data-datetime-list>' + dateValues.map(dateTimeRow).join("") + '</div><button type="button" class="tc-add-datetime" data-add-datetime>+ Weiteren Termin hinzufügen</button></div>',
            '  <div class="tc-range-grid" data-date-range hidden><label><span>Start</span><input type="datetime-local" name="range_start"></label><label><span>Ende</span><input type="datetime-local" name="range_end"></label></div>',
            '  <small>NFON speichert einzelne Kalendertage. Ein Zeitraum wird inklusiv in diese Tage aufgelöst; die Uhrzeiten gelten als gemeinsames tägliches Zeitfenster. Beim Einfügen haben die Zeitfenster-Vorgaben darunter Vorrang.</small>',
            "</div>",
        ].join("");
    }

    function weekdayOptions(selected) {
        return (state.weekdays || Object.keys(weekdayLabels)).map(function (day) {
            return '<option value="' + escapeHtml(day) + '"' + (day === selected ? " selected" : "") + ">" + escapeHtml(weekdayLabels[day] || day) + "</option>";
        }).join("");
    }

    function destinationOptionMarkup(selectedHref, includePlaceholder, selectedOutcome) {
        const labels = {
            "ivr-services": "Ansagen / IVR",
            "voice-mail": "Anrufbeantworter",
            "group-services": "Gruppen",
            "queue-services": "Warteschlangen",
            "phone-extensions": "Nebenstellen",
            "targets": "Systemziele",
            "conference-services": "Konferenzen",
            "virtual-fax-extensions": "Faxziele",
            "routing-prefix": "Routing-Ziele",
            "skill-services": "Skills",
            "frontdesk-services": "Frontdesk",
        };
        const groups = {};
        const options = (state.destination_options || []).slice();
        if (selectedHref && !options.some(function (option) { return option.href === selectedHref; }) && selectedOutcome) {
            options.push({
                href: selectedHref,
                name: selectedOutcome.name || selectedHref,
                kind: selectedOutcome.kind || "Aktuelles Ziel",
            });
        }
        options.forEach(function (option) {
            if (!groups[option.kind]) groups[option.kind] = [];
            groups[option.kind].push(option);
        });
        const placeholder = includePlaceholder ? '<option value="">Ziel auswählen …</option>' : "";
        return placeholder + Object.keys(groups).map(function (kind) {
            return '<optgroup label="' + escapeHtml(labels[kind] || kind) + '">' + groups[kind].map(function (option) {
                const selected = option.href === selectedHref ? " selected" : "";
                return '<option value="' + escapeHtml(option.href) + '"' + selected + ">" + escapeHtml(option.name) + "</option>";
            }).join("") + "</optgroup>";
        }).join("");
    }

    function nodeMarkup(node, index, detached) {
        const nextName = node.next_id ? "Node " + node.next_id : "Endziel";
        const editorId = "tc-editor-" + node.id;
        const outcome = node.outcomes && node.outcomes.length ? node.outcomes[0] : null;
        const memberIds = node.technical_ids || [node.id];
        const technicalLabel = node.is_partial_day
            ? "NFON IDs " + memberIds.join(" + ") + " · technisch gekoppelt"
            : "NFON ID " + node.id;
        const nodeClass = node.is_partial_day ? " tc-node-compound" : "";
        const windowLabel = node.is_partial_day ? "Gültige Uhrzeit" : "Zeitfenster";
        const dateLabel = node.is_partial_day ? "Gültiges Datum" : "Auslösedaten";
        const weekdayFields = node.is_partial_day ? "" : [
            '      <label class="tc-field"><span>Von Wochentag</span><select name="from_day">' + weekdayOptions(node.from_day) + "</select></label>",
            '      <label class="tc-field"><span>Bis Wochentag</span><select name="to_day">' + weekdayOptions(node.to_day) + "</select></label>",
        ].join("");
        return [
            '<article class="tc-node' + nodeClass + (detached ? " tc-node-detached" : "") + '" data-node-id="' + escapeHtml(node.id) + '" data-node-ids="' + escapeHtml(memberIds.join(",")) + '" data-window-service-id="' + escapeHtml(node.window_service_id || "") + '">',
            '  <div class="tc-node-head">',
            '    <div class="tc-node-title">',
            '      <span class="tc-node-index">' + (detached ? "!" : index + 1) + "</span>",
            "      <div><div class=\"tc-node-heading-line\"><h3>" + escapeHtml(node.name) + "</h3>" + (node.is_partial_day ? '<span class="tc-compound-badge"><span class="material-symbols-outlined">join_inner</span>Datum + Uhrzeit</span>' : "") + '</div><span class="tc-node-id">' + escapeHtml(technicalLabel) + "</span></div>",
            "    </div>",
            '    <div class="tc-node-actions">',
            '      <span class="tc-active-badge" data-active-badge hidden><span class="material-symbols-outlined">phone_in_talk</span>Jetzt aktiv</span>',
            '      <button type="button" class="tc-icon-button" data-toggle-editor="' + escapeHtml(editorId) + '" title="Node bearbeiten" aria-expanded="false"><span class="material-symbols-outlined">tune</span></button>',
            "    </div>",
            "  </div>",
            '  <div class="tc-node-summary">',
            '    <div class="tc-summary-cell"><span class="tc-summary-label">' + escapeHtml(dateLabel) + '</span><div class="tc-date-list">' + dateMarkup(node) + "</div></div>",
            '    <div class="tc-summary-cell"><span class="tc-summary-label">' + escapeHtml(windowLabel) + '</span><span class="tc-summary-value">' + escapeHtml(formatWindow(node)) + "</span></div>",
            '    <div class="tc-summary-cell"><span class="tc-summary-label">Ansage / Ziel</span><span class="tc-summary-value">' + escapeHtml(outcomeText(node)) + "</span></div>",
            "  </div>",
            '  <form class="tc-node-editor" data-edit-form id="' + escapeHtml(editorId) + '" hidden>',
            '    <div class="tc-form-grid">',
            node.is_partial_day ? '      <div class="tc-compound-note tc-field-wide"><span class="material-symbols-outlined">join_inner</span><span>Eine fachliche Spezial-Node. Datum und Uhrzeit werden gemeinsam bearbeitet und intern auf zwei verbundene NFON-Nodes verteilt.</span></div>' : "",
            '      <label class="tc-field tc-field-wide"><span>Name</span><input name="name" maxlength="160" required value="' + escapeHtml(node.name) + '"></label>',
            weekdayFields,
            '      <label class="tc-field"><span>Von Uhrzeit</span><input type="time" name="from_time" required value="' + escapeHtml(node.from_time) + '"></label>',
            '      <label class="tc-field"><span>Bis Uhrzeit</span><input type="time" name="to_time" required value="' + escapeHtml(node.to_time) + '"></label>',
            dateSelectorMarkup(node.denied_dates || [], node.from_time),
            outcome ? '      <label class="tc-field tc-field-wide"><span>Ansage / Anrufbeantworter</span><input type="hidden" name="outcome_relation" value="' + escapeHtml(outcome.rel) + '"><select name="outcome_href">' + destinationOptionMarkup(outcome.href, false, outcome) + '</select><small>Alle von NFON für Zeitsteuerungen freigegebenen Ziele werden geladen. Die Verbindung zur nächsten Node bleibt geschützt.</small></label>' : "",
            "    </div>",
            '    <div class="tc-editor-actions"><button class="tc-primary" type="submit"><span class="material-symbols-outlined">save</span>In NFON speichern</button></div>',
            "  </form>",
            !detached ? '<div class="tc-node-route"><span class="material-symbols-outlined">arrow_downward</span>' + escapeHtml(nextName) + "</div>" : "",
            "</article>",
        ].join("");
    }

    function renderHealth() {
        const warnings = Array.isArray(state.warnings) ? state.warnings : [];
        const clientWarnings = [];
        (state.chain || []).forEach(function (node, index, chain) {
            const expectedNext = chain[index + 1];
            if (expectedNext && node.next_id !== expectedNext.id) {
                clientWarnings.push("Die Verbindung nach „" + node.name + "“ ist unterbrochen. Die Auswertung stoppt dort.");
            }
        });
        const allWarnings = warnings.concat(clientWarnings);
        healthElement.className = "tc-health";
        if (allWarnings.length) healthElement.classList.add(state.chain && state.chain.length ? "tc-health-warning" : "tc-health-error");
        const icon = allWarnings.length ? "warning" : "verified";
        const title = allWarnings.length ? "Kette prüfen – nicht alle Nodes sind durchgehend verbunden" : "Kette vollständig verbunden";
        healthElement.innerHTML = '<div class="tc-health-title"><span class="material-symbols-outlined">' + icon + "</span><span>" + escapeHtml(title) + "</span></div>";
        if (allWarnings.length) {
            healthElement.innerHTML += "<ul>" + allWarnings.map(function (warning) { return "<li>" + escapeHtml(warning) + "</li>"; }).join("") + "</ul>";
        }
    }

    function dateSelectionPayload(form) {
        return {
            date_mode: form.elements.date_mode.value,
            dates: Array.from(form.querySelectorAll('[name="trigger_datetime"]')).map(function (input) {
                return input.value;
            }).filter(Boolean),
            range_start: form.elements.range_start.value,
            range_end: form.elements.range_end.value,
        };
    }

    function updateDateSelector(selector) {
        const isRange = selector.querySelector("[data-date-mode]").value === "range";
        const single = selector.querySelector("[data-date-single]");
        const range = selector.querySelector("[data-date-range]");
        single.hidden = isRange;
        range.hidden = !isRange;
        single.querySelectorAll("input").forEach(function (input) { input.required = !isRange; });
        range.querySelectorAll("input").forEach(function (input) { input.required = isRange; });

        if (isRange) {
            const values = Array.from(single.querySelectorAll("input")).map(function (input) {
                return input.value;
            }).filter(Boolean).sort();
            if (values.length && !range.querySelector('[name="range_start"]').value) {
                range.querySelector('[name="range_start"]').value = values[0];
                range.querySelector('[name="range_end"]').value = values[values.length - 1];
            }
        }
    }

    function syncDateTimeWindow(input) {
        if (!input.value || input.value.indexOf("T") === -1) return;
        const form = input.closest("form");
        if (!form) return;
        const time = input.value.split("T")[1].slice(0, 5);
        const windowMode = form.elements.mode ? form.elements.mode.value : "custom";
        if (form.elements.mode && windowMode !== "custom") return;
        if ((input.name === "trigger_datetime" || input.name === "range_start") && form.elements.from_time) {
            form.elements.from_time.value = time;
        }
        if (input.name === "range_end" && form.elements.to_time) {
            form.elements.to_time.value = time;
        }
    }

    function bindDateSelectors(root) {
        root.querySelectorAll("[data-date-selector]").forEach(function (selector) {
            if (selector.dataset.bound === "true") return;
            selector.dataset.bound = "true";
            const mode = selector.querySelector("[data-date-mode]");
            mode.addEventListener("change", function () { updateDateSelector(selector); });
            selector.querySelector("[data-add-datetime]").addEventListener("click", function () {
                selector.querySelector("[data-datetime-list]").insertAdjacentHTML("beforeend", dateTimeRow(""));
            });
            selector.addEventListener("click", function (event) {
                const button = event.target.closest("[data-remove-datetime]");
                if (!button) return;
                const rows = selector.querySelectorAll(".tc-datetime-row");
                if (rows.length === 1) {
                    rows[0].querySelector("input").value = "";
                } else {
                    button.closest(".tc-datetime-row").remove();
                }
            });
            selector.addEventListener("input", function (event) {
                if (event.target.matches('input[type="datetime-local"]')) syncDateTimeWindow(event.target);
            });
            updateDateSelector(selector);
        });
    }

    function bindNodeEvents() {
        page.querySelectorAll("[data-toggle-editor]").forEach(function (button) {
            button.addEventListener("click", function () {
                const editor = document.getElementById(button.dataset.toggleEditor);
                const opening = editor.hidden;
                editor.hidden = !opening;
                button.setAttribute("aria-expanded", opening ? "true" : "false");
            });
        });

        page.querySelectorAll("[data-edit-form]").forEach(function (form) {
            form.addEventListener("submit", function (event) {
                event.preventDefault();
                const node = form.closest("[data-node-id]");
                const data = new FormData(form);
                const button = form.querySelector("button[type=submit]");
                postAction(Object.assign({
                    action: node.dataset.windowServiceId ? "update_partial_day_node" : "update_node",
                    service_id: node.dataset.nodeId,
                    window_service_id: node.dataset.windowServiceId,
                    name: data.get("name"),
                    from_day: data.get("from_day"),
                    from_time: data.get("from_time"),
                    to_day: data.get("to_day"),
                    to_time: data.get("to_time"),
                    outcome_relation: data.get("outcome_relation"),
                    outcome_href: data.get("outcome_href"),
                }, dateSelectionPayload(form)), button).then(function (response) {
                    state = response.state;
                    render();
                    showToast("Node wurde in NFON gespeichert.", false);
                }).catch(function (error) {
                    showToast(error.message, true);
                });
            });
        });

        page.querySelectorAll("[data-insert-after]").forEach(function (button) {
            button.addEventListener("click", function () {
                openInsertDialog(button.dataset.insertAfter);
            });
        });
    }

    function render() {
        const chain = state.display_chain || state.chain || [];
        const detached = state.display_detached || state.detached || [];
        countElement.textContent = String(state.node_count || chain.length + detached.length);
        const technicalCount = page.querySelector("[data-technical-node-count]");
        if (technicalCount) technicalCount.textContent = String(state.technical_node_count || state.node_count || chain.length + detached.length);
        chainElement.innerHTML = chain.map(function (node, index) {
            const canInsert = index < chain.length - 1;
            const insertAfterId = node.insert_after_id || node.id;
            return '<div class="tc-node-wrap">' + nodeMarkup(node, index, false) + (canInsert ? '<button type="button" class="tc-insert-between" data-insert-after="' + escapeHtml(insertAfterId) + '" title="Hier Node einfügen" aria-label="Hier Node einfügen"><span class="tc-insert-plus" aria-hidden="true">+</span></button>' : "") + "</div>";
        }).join("") || '<p class="tc-intro">Keine Zeitsteuerungen aus NFON geladen.</p>';
        detachedSection.hidden = !detached.length;
        detachedGrid.innerHTML = detached.map(function (node, index) {
            return nodeMarkup(node, index, true);
        }).join("");
        renderHealth();
        bindNodeEvents();
        bindDateSelectors(chainElement);
        bindDateSelectors(detachedGrid);
        populateDestinationOptions();
        updateActiveNodeHighlight();
    }

    function populateDestinationOptions() {
        const select = page.querySelector("[data-destination-select]");
        if (!select) return;
        select.innerHTML = destinationOptionMarkup("", true);
    }

    function openInsertDialog(afterId) {
        if (!afterId) {
            showToast("Es gibt keine verbundene Node, hinter der eingefügt werden kann.", true);
            return;
        }
        insertForm.reset();
        insertForm.elements.after_id.value = afterId;
        insertForm.elements.date_mode.value = "single";
        insertForm.querySelector("[data-datetime-list]").innerHTML = dateTimeRow("");
        updateDateSelector(insertForm.querySelector("[data-date-selector]"));
        updateWindowFields();
        populateDestinationOptions();
        dialog.showModal();
    }

    function updateWindowFields() {
        const mode = insertForm.elements.mode.value;
        const timeFields = insertForm.querySelectorAll("[data-time-field]");
        timeFields.forEach(function (field) { field.hidden = mode === "full_day"; });
        if (mode === "morning") {
            insertForm.elements.from_time.value = "00:00";
            insertForm.elements.to_time.value = "12:00";
        } else if (mode === "afternoon") {
            insertForm.elements.from_time.value = "12:00";
            insertForm.elements.to_time.value = "23:59";
        }
    }

    page.querySelector("[data-window-mode]").addEventListener("change", updateWindowFields);
    page.querySelector("[data-add-at-end]").addEventListener("click", function () {
        const chain = state.display_chain || state.chain || [];
        const lastNode = chain.length ? chain[chain.length - 1] : null;
        openInsertDialog(lastNode ? (lastNode.insert_after_id || lastNode.id) : "");
    });
    page.querySelectorAll("[data-dialog-close]").forEach(function (button) {
        button.addEventListener("click", function () { dialog.close(); });
    });
    insertForm.addEventListener("submit", function (event) {
        event.preventDefault();
        const data = new FormData(insertForm);
        const button = insertForm.querySelector("[data-insert-submit]");
        postAction(Object.assign({
            action: "insert_node",
            after_id: data.get("after_id"),
            name: data.get("name"),
            mode: data.get("mode"),
            from_time: data.get("from_time"),
            to_time: data.get("to_time"),
            destination_href: data.get("destination_href"),
        }, dateSelectionPayload(insertForm)), button).then(function (response) {
            state = response.state;
            dialog.close();
            render();
            showToast("Neue Node wurde angelegt und in die NFON-Kette eingefügt.", false);
        }).catch(function (error) {
            showToast(error.message, true);
        });
    });

    bindDateSelectors(insertForm);
    render();
    window.setInterval(updateActiveNodeHighlight, 30000);
})();
