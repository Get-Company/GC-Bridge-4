document.addEventListener("DOMContentLoaded", () => {
    const search = document.querySelector("[data-extension-search]");
    const extensions = [...document.querySelectorAll("[data-extension]")];
    const normalize = (value) => value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("de");
    search?.addEventListener("input", () => {
        const terms = normalize(search.value).trim().split(/\s+/).filter(Boolean);
        let visible = 0;
        for (const element of extensions) {
            const haystack = normalize(element.dataset.search);
            element.hidden = !terms.every((term) => haystack.includes(term));
            if (!element.hidden) visible += 1;
        }
        document.querySelector("[data-search-empty]").hidden = visible !== 0;
    });

    const form = document.querySelector("[data-key-form]");
    if (!form) return;
    const type = form.elements.type;
    const updateFields = () => {
        for (const group of form.querySelectorAll("[data-key-field]")) {
            const active = group.dataset.keyField.split(" ").includes(type.value);
            group.hidden = !active;
            for (const input of group.querySelectorAll("input, select")) {
                input.disabled = !active;
                input.required = active;
            }
        }
        const target = form.elements.target;
        if (target) {
            for (const group of target.querySelectorAll("optgroup")) {
                group.disabled = type.value === "SERVICE" ? group.label !== "Dienste" : group.label !== "Nebenstellen";
                group.hidden = group.disabled;
            }
            if (target.selectedOptions[0]?.parentElement.disabled) target.value = "";
        }
    };
    type.addEventListener("change", updateFields);
    updateFields();
});
