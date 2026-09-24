(() => {
  const config = window.visualEditorConfig;
  let activeVisual = config.activeVisual;
  const schema = JSON.parse(document.getElementById('visual-schema').textContent);
  const products = JSON.parse(document.getElementById('visual-products').textContent);
  let documentTree = JSON.parse(document.getElementById('visual-document').textContent);
  let selectedId = null;
  let activeDrag = null;
  let undoStack = [];
  let redoStack = [];
  let previewTimer = null;
  let previewVersion = 0;
  let savedState = JSON.stringify(documentTree);
  const treeEl = document.getElementById('document-tree');
  const inspectorEl = document.getElementById('node-inspector');
  const statusEl = document.getElementById('save-status');
  const frameEl = document.getElementById('preview-frame');
  const sourceEl = document.getElementById('mjml-source');

  const groups = [
    ['Head', ['mj-title', 'mj-preview', 'mj-font', 'mj-breakpoint', 'mj-style', 'mj-attributes', 'mj-all', 'mj-body']],
    ['Layout', ['mj-wrapper', 'mj-section', 'mj-group', 'mj-column', 'mj-hero']],
    ['Inhalt', ['mj-text', 'mj-image', 'mj-button', 'mj-divider', 'mj-spacer', 'order-form']],
    ['Navigation', ['mj-social', 'mj-social-element', 'mj-navbar', 'mj-navbar-link']],
  ];
  const labels = {
    'mj-title': 'HTML-Titel', 'mj-preview': 'Vorschautext', 'mj-font': 'Schrift',
    'mj-breakpoint': 'Mobil-Breite', 'mj-style': 'CSS', 'mj-attributes': 'Standard-Stile', 'mj-all': 'Alle Bausteine',
    'mj-body': 'Body-Standard', 'mj-wrapper': 'Wrapper', 'mj-section': 'Abschnitt',
    'mj-group': 'Spaltengruppe', 'mj-column': 'Spalte', 'mj-hero': 'Hero',
    'mj-text': 'Text', 'mj-image': 'Bild', 'mj-button': 'Button',
    'mj-divider': 'Trennlinie', 'mj-spacer': 'Abstand', 'mj-social': 'Social',
    'mj-social-element': 'Social-Link', 'mj-navbar': 'Navigation', 'mj-navbar-link': 'Navigationslink', 'product': 'Produkt', 'order-form': 'Bestelltabelle',
  };
  const contentTypes = new Set(['mj-title', 'mj-preview', 'mj-style', 'mj-text', 'mj-button', 'mj-social-element', 'mj-navbar-link', 'product']);
  const defaults = {
    'mj-text': {content: 'Text eingeben', attrs: {'font-size': '16px'}},
    'mj-image': {attrs: {src: 'https://assets.classei.de/', alt: 'Bild'}},
    'mj-button': {content: 'Mehr erfahren', attrs: {href: 'https://www.classei-shop.com/', 'background-color': '#ff9933'}},
    'mj-divider': {attrs: {'border-color': '#dddddd'}},
    'mj-spacer': {attrs: {height: '20px'}},
    'mj-social-element': {content: 'Social-Link', attrs: {name: 'facebook', href: 'https://www.classei.de/'}},
    'mj-navbar-link': {content: 'Link', attrs: {href: 'https://www.classei.de/'}},
    'mj-title': {content: 'Newsletter'}, 'mj-preview': {content: 'Vorschautext'},
    'mj-style': {content: 'h1, h2 { color: #ff9933; }', attrs: {inline: 'inline'}},
    'mj-font': {attrs: {name: 'Roboto', href: 'https://assets.classei.de/css/emails_fonts.css'}},
    'mj-breakpoint': {attrs: {width: '480px'}},
  };

  function make(tag) {
    const initial = defaults[tag] || {};
    return {id: crypto.randomUUID(), type: tag, attrs: {...(initial.attrs || {})}, content: initial.content || '', children: []};
  }
  function copyState() { return JSON.stringify(documentTree); }
  function setStatus(message, error = false) {
    statusEl.textContent = message;
    statusEl.style.color = error ? '#b44444' : '#54806c';
  }
  function changed() {
    setStatus(copyState() === savedState ? 'Gespeichert' : 'Ungespeicherte Änderungen');
    clearTimeout(previewTimer);
    previewTimer = setTimeout(preview, 700);
  }
  function remember() {
    undoStack.push(copyState());
    if (undoStack.length > 50) undoStack.shift();
    redoStack = [];
    document.getElementById('undo').disabled = false;
    document.getElementById('redo').disabled = true;
  }
  function locate(id, nodes = null, parent = null) {
    if (!nodes) nodes = [...documentTree.head, ...documentTree.body];
    for (const node of nodes) {
      if (node.id === id) return {node, parent};
      const found = locate(id, node.children, node);
      if (found) return found;
    }
    return null;
  }
  function childrenOf(parentId) {
    if (parentId === 'head' || parentId === 'body') return {children: documentTree[parentId], type: parentId};
    const found = locate(parentId);
    return found ? {children: found.node.children, type: found.node.type} : null;
  }
  function contains(node, id) {
    return node.id === id || node.children.some(child => contains(child, id));
  }
  function canPlace(tag, parentId, movingId = null) {
    const parent = childrenOf(parentId);
    if (!parent || !(schema.children[parent.type] || []).includes(tag)) return false;
    if (movingId && parentId !== 'head' && parentId !== 'body') {
      const moving = locate(movingId);
      if (moving && contains(moving.node, parentId)) return false;
    }
    return true;
  }
  function removeNode(id, nodes = null) {
    if (!nodes) {
      return removeNode(id, documentTree.head) || removeNode(id, documentTree.body);
    }
    const index = nodes.findIndex(node => node.id === id);
    if (index >= 0) return nodes.splice(index, 1)[0];
    for (const node of nodes) {
      const found = removeNode(id, node.children);
      if (found) return found;
    }
    return null;
  }
  function insert(node, parentId, beforeId = null) {
    const parent = childrenOf(parentId);
    if (!parent) return;
    const index = beforeId ? parent.children.findIndex(item => item.id === beforeId) : -1;
    parent.children.splice(index < 0 ? parent.children.length : index, 0, node);
  }
  function parentFor(id, nodes = documentTree.head, parentId = 'head') {
    for (const node of nodes) {
      if (node.id === id) return {parentId, siblings: nodes};
      const nested = parentFor(id, node.children, node.id);
      if (nested) return nested;
    }
    if (nodes === documentTree.head) return parentFor(id, documentTree.body, 'body');
    return null;
  }
  function mutate(callback) {
    remember();
    callback();
    renderTree();
    renderInspector();
    changed();
  }
  function add(tag) {
    const current = selectedId && locate(selectedId);
    const parent = current && canPlace(tag, current.node.id) ? current.node.id : null;
    mutate(() => {
      const node = make(tag);
      if (parent) insert(node, parent);
      else if (canPlace(tag, 'head')) insert(node, 'head');
      else if ((schema.children['mj-attributes'] || []).includes(tag)) {
        let attributes = documentTree.head.find(item => item.type === 'mj-attributes');
        if (!attributes) { attributes = make('mj-attributes'); insert(attributes, 'head'); }
        insert(node, attributes.id);
      }
      else if (canPlace(tag, 'body')) insert(node, 'body');
      else if (tag === 'mj-column' || tag === 'mj-group') {
        const section = make('mj-section');
        section.children.push(node);
        insert(section, 'body');
      } else {
        const section = make('mj-section');
        const column = make('mj-column');
        if ((schema.children['mj-column'] || []).includes(tag)) {
          column.children.push(node);
        } else if (tag === 'mj-social-element' || tag === 'mj-navbar-link') {
          const container = make(tag === 'mj-social-element' ? 'mj-social' : 'mj-navbar');
          container.children.push(node);
          column.children.push(container);
        } else {
          setStatus('Bitte einen passenden Elternbaustein auswählen.', true);
          undoStack.pop();
          return;
        }
        section.children.push(column);
        insert(section, 'body');
      }
      selectedId = node.id;
    });
  }
  function palette() {
    const root = document.getElementById('palette-list');
    const productGroup = document.createElement('div');
    productGroup.className = 'palette-group';
    const productHeading = document.createElement('h3');
    productHeading.textContent = 'Produkte';
    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'product-search';
    search.placeholder = 'Artikel suchen …';
    search.disabled = !activeVisual;
    if (!activeVisual) search.title = 'Zuerst den visuellen Entwurf speichern.';
    search.setAttribute('aria-label', 'Produkt suchen');
    const results = document.createElement('div');
    let searchTimer;
    search.addEventListener('input', () => {
      clearTimeout(searchTimer);
      results.replaceChildren();
      if (search.value.trim().length < 2) return;
      searchTimer = setTimeout(async () => {
        try {
          const response = await fetch(`${config.search}?q=${encodeURIComponent(search.value.trim())}`);
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Suche fehlgeschlagen.');
          results.replaceChildren();
          (data.products || []).forEach(product => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'product-result';
            button.textContent = product.label;
            button.addEventListener('click', () => addProduct(product));
            results.append(button);
          });
        } catch (error) { setStatus(error.message, true); }
      }, 250);
    });
    productGroup.append(productHeading, search, results);
    root.append(productGroup);
    groups.forEach(([title, tags]) => {
      const group = document.createElement('div');
      group.className = 'palette-group';
      const heading = document.createElement('h3');
      heading.textContent = title;
      group.append(heading);
      tags.forEach(tag => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'palette-item';
        button.draggable = true;
        button.textContent = labels[tag];
        const small = document.createElement('small');
        small.textContent = tag;
        button.append(small);
        button.addEventListener('click', () => add(tag));
        button.addEventListener('dragstart', event => { activeDrag = {tag}; event.dataTransfer.setData('application/x-mjml-node', JSON.stringify(activeDrag)); });
        button.addEventListener('dragend', () => { activeDrag = null; });
        group.append(button);
      });
      root.append(group);
    });
  }
  async function addProduct(product) {
    try {
      const response = await fetch(config.add, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': config.csrf},
        body: JSON.stringify({product_id: product.id}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Produkt konnte nicht hinzugefügt werden.');
      products[String(data.id)] ||= {label: product.label, mode: 'none', value: ''};
      const selected = selectedId && locate(selectedId);
      const parent = selected && canPlace('product', selected.node.id) ? selected.node.id : 'body';
      mutate(() => {
        const node = make('product');
        node.attrs['campaign-product-id'] = String(data.id);
        insert(node, parent);
        selectedId = node.id;
      });
    } catch (error) { setStatus(error.message, true); }
  }
  function dropTarget(element, parentId, beforeId = null) {
    element.addEventListener('dragover', event => {
      const drag = dragData(event);
      if (!drag || !canPlace(drag.tag, parentId, drag.id)) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = drag.id ? 'move' : 'copy';
      element.classList.add('drag-over');
    });
    element.addEventListener('dragleave', () => element.classList.remove('drag-over'));
    element.addEventListener('drop', event => {
      element.classList.remove('drag-over');
      const drag = dragData(event);
      if (!drag || !canPlace(drag.tag, parentId, drag.id)) return;
      event.preventDefault();
      event.stopPropagation();
      mutate(() => {
        const node = drag.id ? removeNode(drag.id) : make(drag.tag);
        insert(node, parentId, beforeId);
        selectedId = node.id;
      });
    });
  }
  function dragData(event) {
    try {
      const value = event.dataTransfer.getData('application/x-mjml-node');
      return value ? JSON.parse(value) : activeDrag;
    } catch { return activeDrag; }
  }
  function zone(parentId, beforeId = null) {
    const el = document.createElement('div');
    el.className = 'drop-zone';
    el.setAttribute('aria-label', 'Ablageposition');
    dropTarget(el, parentId, beforeId);
    return el;
  }
  function nodeElement(node, parentId) {
    const wrap = document.createElement('div');
    wrap.className = 'node' + (node.id === selectedId ? ' selected' : '');
    const row = document.createElement('div');
    row.className = 'node-row';
    row.draggable = true;
    row.addEventListener('dragstart', event => {
      activeDrag = {tag: node.type, id: node.id};
      event.dataTransfer.setData('application/x-mjml-node', JSON.stringify(activeDrag));
      event.stopPropagation();
    });
    row.addEventListener('dragend', () => { activeDrag = null; });
    const handle = document.createElement('span');
    handle.className = 'node-handle';
    handle.textContent = '⋮⋮';
    const label = document.createElement('button');
    label.type = 'button';
    label.className = 'node-label';
    const strong = document.createElement('strong');
    strong.textContent = labels[node.type] || node.type;
    const small = document.createElement('small');
    small.textContent = node.type === 'product' ? (products[node.attrs['campaign-product-id']]?.label || 'Produkt') : (node.content || node.attrs.src || node.attrs.href || node.type);
    label.append(strong, small);
    label.addEventListener('click', () => { selectedId = node.id; renderTree(); renderInspector(); });
    row.append(handle, label);
    for (const [direction, symbol] of [['up', '↑'], ['down', '↓']]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'move';
      button.textContent = symbol;
      button.setAttribute('aria-label', direction === 'up' ? 'Nach oben' : 'Nach unten');
      button.addEventListener('click', () => moveSibling(node.id, direction));
      row.append(button);
    }
    wrap.append(row);
    if (schema.children[node.type]) {
      const children = document.createElement('div');
      children.className = 'tree-children';
      dropTarget(children, node.id);
      node.children.forEach(child => {
        children.append(zone(node.id, child.id), nodeElement(child, node.id));
      });
      children.append(zone(node.id));
      wrap.append(children);
    }
    return wrap;
  }
  function renderTree() {
    treeEl.replaceChildren();
    for (const rootName of ['head', 'body']) {
      const root = document.createElement('div');
      root.className = 'tree-root';
      const heading = document.createElement('h3');
      heading.textContent = rootName === 'head' ? 'mj-head · Einstellungen' : 'mj-body · sichtbare E-Mail';
      root.append(heading);
      const children = document.createElement('div');
      children.className = 'tree-children';
      dropTarget(children, rootName);
      documentTree[rootName].forEach(node => children.append(zone(rootName, node.id), nodeElement(node, rootName)));
      children.append(zone(rootName));
      root.append(children);
      treeEl.append(root);
    }
    highlightPreview();
  }
  function previewNodeId(element) {
    const marked = element?.closest?.('[class*="visual-node-"]');
    const token = [...(marked?.classList || [])].find(value => value.startsWith('visual-node-'));
    return token ? token.slice('visual-node-'.length) : null;
  }
  function highlightPreview() {
    const previewDocument = frameEl.contentDocument;
    if (!previewDocument) return;
    previewDocument.querySelectorAll('.visual-selected').forEach(element => element.classList.remove('visual-selected'));
    if (selectedId) {
      const element = previewDocument.querySelector(`.visual-node-${selectedId}`);
      if (element) element.classList.add('visual-selected');
    }
  }
  function canvasPlacement(targetId, tag, movingId, y, element) {
    let currentId = targetId;
    while (currentId) {
      const current = locate(currentId);
      if (!current) break;
      if (canPlace(tag, currentId, movingId)) return {parentId: currentId, beforeId: null};
      if (current.node.type === 'mj-section') {
        const column = current.node.children.find(node => node.type === 'mj-column');
        if (column && canPlace(tag, column.id, movingId)) return {parentId: column.id, beforeId: null};
      }
      const relation = parentFor(currentId);
      if (!relation) break;
      if (canPlace(tag, relation.parentId, movingId)) {
        const index = relation.siblings.findIndex(node => node.id === currentId);
        const before = y < element.getBoundingClientRect().top + element.getBoundingClientRect().height / 2;
        return {parentId: relation.parentId, beforeId: before ? currentId : (relation.siblings[index + 1]?.id || null)};
      }
      currentId = relation.parentId === 'body' || relation.parentId === 'head' ? null : relation.parentId;
    }
    return null;
  }
  function bindPreviewCanvas() {
    const previewDocument = frameEl.contentDocument;
    if (!previewDocument) return;
    const style = previewDocument.createElement('style');
    style.textContent = '[class*="visual-node-"]:hover{outline:1px dashed #e9892b;cursor:pointer}.visual-selected{outline:2px solid #e9892b!important}[class*="visual-node-"].visual-drop{outline:3px dashed #e9892b!important}';
    previewDocument.head.append(style);
    previewDocument.addEventListener('click', event => {
      const id = previewNodeId(event.target);
      if (!id) return;
      event.preventDefault();
      selectedId = id;
      renderTree(); renderInspector();
      inspectorEl.parentElement.scrollTop = 0;
    }, true);
    previewDocument.addEventListener('dragover', event => {
      const drag = dragData(event);
      const id = previewNodeId(event.target);
      if (!drag || !id) return;
      const placement = canvasPlacement(id, drag.tag, drag.id, event.clientY, event.target.closest('[class*="visual-node-"]'));
      if (!placement) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = drag.id ? 'move' : 'copy';
    });
    previewDocument.addEventListener('drop', event => {
      const drag = dragData(event);
      const id = previewNodeId(event.target);
      if (!drag || !id) return;
      const placement = canvasPlacement(id, drag.tag, drag.id, event.clientY, event.target.closest('[class*="visual-node-"]'));
      if (!placement) return;
      event.preventDefault();
      mutate(() => {
        const node = drag.id ? removeNode(drag.id) : make(drag.tag);
        insert(node, placement.parentId, placement.beforeId);
        selectedId = node.id;
      });
    });
    highlightPreview();
  }
  function moveSibling(id, direction) {
    const found = parentFor(id);
    if (!found) return;
    const index = found.siblings.findIndex(node => node.id === id);
    const next = index + (direction === 'up' ? -1 : 1);
    if (next < 0 || next >= found.siblings.length) return;
    mutate(() => {
      [found.siblings[index], found.siblings[next]] = [found.siblings[next], found.siblings[index]];
    });
  }
  function renderInspector() {
    inspectorEl.replaceChildren();
    const found = selectedId && locate(selectedId);
    if (!found) { inspectorEl.textContent = 'Baustein auswählen.'; return; }
    const node = found.node;
    const heading = document.createElement('h3');
    heading.textContent = node.type === 'product' ? (products[node.attrs['campaign-product-id']]?.label || 'Produkt') : `${labels[node.type] || node.type} · ${node.type}`;
    inspectorEl.append(heading);
    if (contentTypes.has(node.type)) {
      const label = document.createElement('label');
      label.textContent = node.type === 'product' ? 'Beschreibung überschreiben · optional' : 'Inhalt';
      const input = document.createElement('textarea');
      input.value = node.content;
      input.addEventListener('focus', remember, {once: true});
      input.addEventListener('input', () => { node.content = input.value; changed(); });
      input.addEventListener('change', renderTree);
      inspectorEl.append(label, input);
    }
    (schema.attrs[node.type] || []).forEach(attr => {
      if (attr === 'campaign-product-id') return;
      const label = document.createElement('label');
      label.textContent = attr;
      const input = document.createElement('input');
      input.type = ['href', 'src', 'background-url', 'base-url'].includes(attr) ? 'url' : 'text';
      input.value = node.attrs[attr] || '';
      input.addEventListener('focus', remember, {once: true});
      input.addEventListener('input', () => {
        if (input.value) node.attrs[attr] = input.value;
        else delete node.attrs[attr];
        changed();
      });
      input.addEventListener('change', renderTree);
      inspectorEl.append(label, input);
    });
    if (node.type === 'product') productPriceControls(node);
    const hint = document.createElement('p');
    hint.className = 'hint';
    hint.textContent = 'Texte werden als Klartext eingefügt. {{ recipient.full_name }} setzt beim Versand den Empfängernamen ein. Gestaltung erfolgt über die Attribute.';
    inspectorEl.append(hint);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'delete';
    remove.textContent = 'Baustein entfernen';
    remove.addEventListener('click', () => mutate(() => { removeNode(node.id); selectedId = null; }));
    inspectorEl.append(remove);
  }
  function productPriceControls(node) {
    const productId = node.attrs['campaign-product-id'];
    const product = products[productId] || {mode: 'none', value: ''};
    const label = document.createElement('label');
    label.textContent = 'Sonderpreis';
    const controls = document.createElement('div');
    controls.className = 'price-controls';
    const mode = document.createElement('select');
    [['none', 'Katalogpreis'], ['price', 'Neuer Preis €'], ['percent', 'Rabatt %']].forEach(([value, title]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = title;
      mode.append(option);
    });
    mode.value = product.mode;
    const amount = document.createElement('input');
    amount.type = 'number';
    amount.min = '0.01';
    amount.step = '0.01';
    amount.value = product.value;
    amount.placeholder = 'Wert';
    controls.append(mode, amount);
    const savePrice = document.createElement('button');
    savePrice.type = 'button';
    savePrice.className = 'price-save';
    savePrice.textContent = 'Preis übernehmen';
    savePrice.disabled = !activeVisual;
    if (!activeVisual) savePrice.title = 'Zuerst den visuellen Entwurf speichern.';
    savePrice.addEventListener('click', async () => {
      try {
        const response = await fetch(`${config.productBase}${productId}/`, {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': config.csrf},
          body: JSON.stringify({action: 'price', mode: mode.value, value: amount.value}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Preis konnte nicht gespeichert werden.');
        products[productId] = {...product, mode: mode.value, value: amount.value};
        setStatus('Preis gespeichert');
        preview();
      } catch (error) { setStatus(error.message, true); }
    });
    inspectorEl.append(label, controls, savePrice);
  }
  async function preview() {
    const version = ++previewVersion;
    try {
      const response = await fetch(config.preview, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': config.csrf},
        body: copyState(),
      });
      const data = await response.json();
      if (version !== previewVersion) return;
      if (!response.ok) throw new Error(data.error || 'Vorschau fehlgeschlagen.');
      frameEl.srcdoc = data.html;
      sourceEl.textContent = data.mjml;
      if (copyState() === savedState) setStatus('Gespeichert');
    } catch (error) {
      if (version === previewVersion) setStatus(error.message, true);
    }
  }
  async function save() {
    try {
      setStatus('Speichere …');
      const response = await fetch(config.save, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': config.csrf},
        body: copyState(),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Speichern fehlgeschlagen.');
      savedState = copyState();
      activeVisual = true;
      const search = document.querySelector('.product-search');
      if (search) { search.disabled = false; search.title = ''; }
      if (selectedId) renderInspector();
      setStatus('Gespeichert');
      const notice = document.querySelector('.notice');
      if (notice) notice.remove();
    } catch (error) { setStatus(error.message, true); }
  }
  function history(kind) {
    const source = kind === 'undo' ? undoStack : redoStack;
    const destination = kind === 'undo' ? redoStack : undoStack;
    if (!source.length) return;
    destination.push(copyState());
    documentTree = JSON.parse(source.pop());
    if (selectedId && !locate(selectedId)) selectedId = null;
    renderTree(); renderInspector(); changed();
    document.getElementById('undo').disabled = !undoStack.length;
    document.getElementById('redo').disabled = !redoStack.length;
  }
  document.getElementById('undo').addEventListener('click', () => history('undo'));
  document.getElementById('redo').addEventListener('click', () => history('redo'));
  document.getElementById('undo').disabled = true;
  document.getElementById('redo').disabled = true;
  document.getElementById('save').addEventListener('click', save);
  document.getElementById('refresh').addEventListener('click', preview);
  frameEl.addEventListener('load', bindPreviewCanvas);
  document.getElementById('toggle-mjml').addEventListener('click', event => {
    const showSource = sourceEl.hidden;
    sourceEl.hidden = !showSource;
    frameEl.hidden = showSource;
    event.target.textContent = showSource ? 'Vorschau anzeigen' : 'MJML anzeigen';
  });
  window.addEventListener('beforeunload', event => {
    if (copyState() !== savedState) { event.preventDefault(); event.returnValue = ''; }
  });
  palette(); renderTree(); renderInspector(); preview();
})();
