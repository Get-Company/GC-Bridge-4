(function () {
  const root = document.getElementById("category-manager")
  const dataElement = document.getElementById("category-manager-data")

  if (!root || !dataElement) {
    return
  }

  const canChange = root.dataset.canChange === "1"
  const csrfToken = root.querySelector("input[name=csrfmiddlewaretoken]")?.value || ""
  const treeElement = document.getElementById("category-tree")
  const treeSearchInput = document.getElementById("category-tree-search")
  const productSearchInput = document.getElementById("category-product-search")
  const productsContent = document.getElementById("category-products-content")
  const emptyState = document.getElementById("category-empty-state")
  const productsTitle = document.getElementById("category-products-title")
  const productsMeta = document.getElementById("category-products-meta")
  const editLink = document.getElementById("category-edit-link")
  const assignedList = document.getElementById("assigned-products-list")
  const availableList = document.getElementById("available-products-list")
  const assignedCount = document.getElementById("assigned-products-count")
  const availableCount = document.getElementById("available-products-count")
  const collapsedKey = "gc_bridge_category_manager_collapsed"

  let categories = JSON.parse(dataElement.textContent || "[]")
  let selectedId = categories.length ? categories[0].id : null
  let draggedId = null
  let dropState = null
  let productSearchTimeout = null
  let collapsed = readCollapsed()

  function readCollapsed() {
    try {
      return new Set(JSON.parse(window.localStorage.getItem(collapsedKey) || "[]"))
    } catch (_error) {
      return new Set()
    }
  }

  function storeCollapsed() {
    window.localStorage.setItem(collapsedKey, JSON.stringify(Array.from(collapsed)))
  }

  function urlFor(template, id) {
    return template.replace("{id}", String(id))
  }

  function childrenByParent() {
    return categories.reduce((result, category) => {
      const key = category.parent_id || 0
      if (!result[key]) {
        result[key] = []
      }
      result[key].push(category.id)
      return result
    }, {})
  }

  function categoryById(id) {
    return categories.find((category) => category.id === Number(id))
  }

  function visibleCategoryIds() {
    const searchTerm = (treeSearchInput.value || "").trim().toLowerCase()
    if (!searchTerm) {
      return new Set(categories.map((category) => category.id))
    }

    const visibleIds = new Set()
    categories.forEach((category) => {
      const haystack = `${category.name} ${category.slug} ${category.legacy_erp_nr || ""}`.toLowerCase()
      if (!haystack.includes(searchTerm)) {
        return
      }
      visibleIds.add(category.id)
      let parentId = category.parent_id
      while (parentId) {
        visibleIds.add(parentId)
        parentId = categoryById(parentId)?.parent_id
      }
    })
    return visibleIds
  }

  function isHiddenByCollapse(category) {
    let parentId = category.parent_id
    while (parentId) {
      if (collapsed.has(parentId)) {
        return true
      }
      parentId = categoryById(parentId)?.parent_id
    }
    return false
  }

  function icon(name) {
    const span = document.createElement("span")
    span.className = "material-symbols-outlined"
    span.textContent = name
    return span
  }

  function renderTree() {
    const visibleIds = visibleCategoryIds()
    const searchTerm = (treeSearchInput.value || "").trim()
    treeElement.replaceChildren()

    categories.forEach((category) => {
      if (!visibleIds.has(category.id) || (!searchTerm && isHiddenByCollapse(category))) {
        return
      }

      const row = document.createElement("div")
      row.className = "category-manager-row"
      row.dataset.id = category.id
      row.style.paddingLeft = `${0.5 + category.level * 1.25}rem`
      if (category.id === selectedId) {
        row.classList.add("is-selected")
      }
      if (canChange) {
        row.draggable = true
      }

      const toggle = document.createElement("button")
      toggle.type = "button"
      toggle.className = "category-manager-toggle"
      const toggleIcon = category.has_children
        ? (collapsed.has(category.id) ? "chevron_right" : "expand_more")
        : "fiber_manual_record"
      toggle.appendChild(icon(toggleIcon))
      toggle.addEventListener("click", (event) => {
        event.stopPropagation()
        if (!category.has_children) {
          return
        }
        if (collapsed.has(category.id)) {
          collapsed.delete(category.id)
        } else {
          collapsed.add(category.id)
        }
        storeCollapsed()
        renderTree()
      })

      const drag = document.createElement("span")
      drag.className = "category-manager-drag"
      drag.appendChild(icon("drag_indicator"))

      const title = document.createElement("div")
      title.className = "min-w-0"
      const name = document.createElement("div")
      name.className = "category-manager-name"
      name.textContent = category.name
      const meta = document.createElement("div")
      meta.className = "category-manager-meta"
      meta.textContent = category.legacy_erp_nr ? `ERP ${category.legacy_erp_nr}` : category.slug
      title.append(name, meta)

      const count = document.createElement("span")
      count.className = "category-manager-count"
      count.textContent = category.product_count

      row.append(toggle, drag, title, count)
      row.addEventListener("click", () => selectCategory(category.id))
      bindDragEvents(row)
      treeElement.appendChild(row)
    })
  }

  function bindDragEvents(row) {
    if (!canChange) {
      return
    }

    row.addEventListener("dragstart", (event) => {
      draggedId = Number(row.dataset.id)
      event.dataTransfer.effectAllowed = "move"
      event.dataTransfer.setData("text/plain", String(draggedId))
    })

    row.addEventListener("dragend", () => {
      draggedId = null
      clearDropClasses()
    })

    row.addEventListener("dragover", (event) => {
      if (!draggedId || Number(row.dataset.id) === draggedId) {
        return
      }
      event.preventDefault()
      const rect = row.getBoundingClientRect()
      const offset = event.clientY - rect.top
      const zone = offset < rect.height / 3 ? "before" : offset > (rect.height * 2) / 3 ? "after" : "inside"
      dropState = { targetId: Number(row.dataset.id), position: zone }
      clearDropClasses()
      row.classList.add(`is-drop-${zone}`)
    })

    row.addEventListener("drop", (event) => {
      event.preventDefault()
      if (!draggedId || !dropState) {
        return
      }
      moveCategory(draggedId, dropState.targetId, dropState.position)
    })
  }

  function clearDropClasses() {
    treeElement.querySelectorAll(".is-drop-before, .is-drop-after, .is-drop-inside").forEach((row) => {
      row.classList.remove("is-drop-before", "is-drop-after", "is-drop-inside")
    })
  }

  function postForm(url, data) {
    const body = new FormData()
    Object.entries(data).forEach(([key, value]) => body.append(key, value))
    return fetch(url, {
      body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
      method: "POST",
    }).then((response) => response.json().then((payload) => ({ ok: response.ok, payload })))
  }

  function moveCategory(categoryId, targetId, position) {
    postForm(root.dataset.moveUrl, {
      category_id: categoryId,
      target_id: targetId,
      position,
    }).then(({ ok, payload }) => {
      if (!ok) {
        window.alert(payload.error || "Die Kategorie konnte nicht verschoben werden.")
        return
      }
      categories = payload.categories || categories
      selectedId = categoryId
      renderTree()
    })
  }

  function selectCategory(categoryId) {
    selectedId = Number(categoryId)
    renderTree()
    loadProducts()
  }

  function loadProducts() {
    if (!selectedId) {
      return
    }
    const url = new URL(urlFor(root.dataset.productsUrl, selectedId), window.location.origin)
    url.searchParams.set("q", productSearchInput.value || "")
    fetch(url, { credentials: "same-origin" })
      .then((response) => response.json())
      .then((payload) => renderProducts(payload))
  }

  function renderProducts(payload) {
    productsContent.classList.remove("hidden")
    emptyState.classList.add("hidden")
    productsTitle.textContent = payload.category.name
    productsMeta.textContent = payload.category.legacy_erp_nr ? `ERP ${payload.category.legacy_erp_nr}` : ""
    editLink.href = payload.category.edit_url
    assignedCount.textContent = payload.assigned_total
    availableCount.textContent = payload.available_products.length
    renderProductList(assignedList, payload.assigned_products, "remove")
    renderProductList(availableList, payload.available_products, "add")
    const searchLength = (productSearchInput.value || "").trim().length
    if (!payload.available_products.length && searchLength < payload.search_min_length) {
      renderNotice(availableList, `Mindestens ${payload.search_min_length} Zeichen eingeben.`)
    }
  }

  function renderNotice(list, text) {
    const notice = document.createElement("div")
    notice.className = "category-manager-notice"
    notice.textContent = text
    list.replaceChildren(notice)
  }

  function renderProductList(list, products, actionName) {
    list.replaceChildren()
    if (!products.length) {
      renderNotice(list, "Keine Einträge.")
      return
    }

    products.forEach((product) => {
      const row = document.createElement("div")
      row.className = "category-manager-product-row"

      const text = document.createElement("a")
      text.href = product.edit_url
      text.className = "min-w-0"
      const title = document.createElement("div")
      title.className = "category-manager-product-title"
      title.textContent = product.erp_nr
      const meta = document.createElement("div")
      meta.className = "category-manager-product-meta"
      meta.textContent = product.name || (product.is_active ? "Aktiv" : "Inaktiv")
      text.append(title, meta)

      const button = document.createElement("button")
      button.type = "button"
      button.className = "category-manager-product-action"
      button.title = actionName === "add" ? "Zuordnen" : "Entfernen"
      button.appendChild(icon(actionName === "add" ? "add" : "remove"))
      button.addEventListener("click", () => updateAssignment(product.id, actionName))

      row.append(text, button)
      list.appendChild(row)
    })
  }

  function updateAssignment(productId, actionName) {
    if (!selectedId) {
      return
    }
    postForm(urlFor(root.dataset.assignmentUrl, selectedId), {
      action: actionName,
      product_id: productId,
      q: productSearchInput.value || "",
    }).then(({ ok, payload }) => {
      if (!ok) {
        window.alert(payload.error || "Die Produktzuordnung konnte nicht gespeichert werden.")
        return
      }
      const currentCategory = categories.find((category) => category.id === selectedId)
      if (currentCategory) {
        currentCategory.product_count = payload.assigned_total
      }
      renderTree()
      renderProducts(payload)
    })
  }

  document.querySelector('[data-action="refresh-tree"]')?.addEventListener("click", () => {
    fetch(root.dataset.treeUrl, { credentials: "same-origin" })
      .then((response) => response.json())
      .then((payload) => {
        categories = payload.categories || categories
        renderTree()
      })
  })

  treeSearchInput.addEventListener("input", renderTree)
  productSearchInput.addEventListener("input", () => {
    window.clearTimeout(productSearchTimeout)
    productSearchTimeout = window.setTimeout(loadProducts, 180)
  })

  renderTree()
  if (selectedId) {
    loadProducts()
  }
})()
