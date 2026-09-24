(() => {
  const config = window.emailEditorConfig;
  const initial = JSON.parse(document.getElementById('initial-content').textContent);
  const frame = document.getElementById('email-preview');
  const track = document.getElementById('editor-track');
  const status = document.getElementById('save-status');
  const search = document.getElementById('product-search');
  const results = document.getElementById('search-results');
  let editTimer;
  let searchTimer;
  let previewGeneration = 0;

  document.querySelectorAll('.product-card').forEach(card => {
    const custom = (initial.product_texts || {})[card.dataset.catalogId] || {};
    card.querySelectorAll('[data-product-text]').forEach(input => {
      input.value = custom[input.dataset.productText] || '';
    });
  });

  function insertHeading(heading) {
    const afterProduct = String(heading.after_product_id || '');
    const card = document.createElement('section');
    card.className = 'editor-card heading-card';
    card.dataset.anchor = `editor-heading-${heading.id}`;
    card.dataset.headingId = heading.id;
    card.dataset.afterProductId = afterProduct;
    card.innerHTML = `
      <span class="eyebrow">Zwischenblock</span>
      <h2>Zwischenüberschrift</h2>
      <div class="row-actions"><button type="button" data-remove-heading class="danger">Entfernen</button></div>
      <label for="heading-title-${heading.id}">Überschrift links</label>
      <input id="heading-title-${heading.id}" data-heading-field="title" type="text" placeholder="z. B. Bestellformular">
      <label for="heading-center-${heading.id}">Text mittig · optional</label>
      <textarea id="heading-center-${heading.id}" data-heading-field="center_text" rows="2" placeholder="Einfach antworten und Anzahl eingeben"></textarea>
      <label for="heading-right-${heading.id}">Text rechts · optional</label>
      <textarea id="heading-right-${heading.id}" data-heading-field="right_text" rows="2" placeholder="oder schnell anrufen: …"></textarea>`;
    card.querySelector('[data-heading-field="title"]').value = heading.title || '';
    card.querySelector('[data-heading-field="center_text"]').value = heading.center_text || '';
    card.querySelector('[data-heading-field="right_text"]').value = heading.right_text || '';
    let anchor = afterProduct
      ? Array.from(document.querySelectorAll('.product-card')).find(item => item.dataset.productId === afterProduct)
      : document.querySelector('[data-anchor="editor-products"]');
    if (!anchor) anchor = Array.from(document.querySelectorAll('.product-card')).at(-1) || document.querySelector('[data-anchor="editor-products"]');
    while (anchor.nextElementSibling?.classList.contains('heading-card') &&
           anchor.nextElementSibling.dataset.afterProductId === afterProduct) {
      anchor = anchor.nextElementSibling;
    }
    anchor.after(card);
    return card;
  }

  (initial.headings || []).forEach(insertHeading);

  function content() {
    const data = {};
    document.querySelectorAll('[data-field]').forEach(input => { data[input.dataset.field] = input.value; });
    data.product_texts = {};
    document.querySelectorAll('.product-card').forEach(card => {
      const custom = {};
      card.querySelectorAll('[data-product-text]').forEach(input => {
        custom[input.dataset.productText] = input.value;
      });
      data.product_texts[card.dataset.catalogId] = custom;
    });
    data.headings = Array.from(document.querySelectorAll('.heading-card')).map(card => {
      const heading = {id: card.dataset.headingId, after_product_id: card.dataset.afterProductId};
      card.querySelectorAll('[data-heading-field]').forEach(input => {
        heading[input.dataset.headingField] = input.value;
      });
      return heading;
    });
    return data;
  }

  async function api(url, data) {
    const response = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': config.csrf},
      body: JSON.stringify(data)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Anfrage fehlgeschlagen');
    return result;
  }

  function showError(error) { status.textContent = error.message || String(error); status.style.color = '#bd4e4e'; }
  async function save() {
    status.textContent = 'Speichert …'; status.style.color = '#8b7a5b';
    try { await api(config.save, content()); status.textContent = 'Gespeichert'; status.style.color = '#2d8b62'; }
    catch (error) { showError(error); }
  }
  async function preview() {
    const generation = ++previewGeneration;
    status.textContent = 'Vorschau wird erstellt …';
    try {
      const result = await api(config.preview, content());
      if (generation !== previewGeneration) return;
      frame.srcdoc = result.html;
      status.textContent = 'Vorschau aktuell'; status.style.color = '#2d8b62';
    } catch (error) { if (generation === previewGeneration) showError(error); }
  }
  function changed() {
    status.textContent = 'Ungespeicherte Änderung'; status.style.color = '#8b7a5b';
    clearTimeout(editTimer);
    editTimer = setTimeout(() => { save(); preview(); }, 650);
  }
  document.querySelectorAll('[data-field],[data-product-text]').forEach(input => input.addEventListener('input', changed));
  document.querySelectorAll('[data-add-heading]').forEach(button => button.addEventListener('click', () => {
    const card = insertHeading({id: crypto.randomUUID(), after_product_id: button.dataset.afterProduct});
    card.querySelector('[data-heading-field="title"]').focus();
    changed();
  }));
  track.addEventListener('input', event => {
    if (event.target.matches('[data-heading-field]')) changed();
  });
  track.addEventListener('click', event => {
    if (!event.target.matches('[data-remove-heading]')) return;
    event.target.closest('.heading-card').remove();
    changed();
  });
  document.getElementById('refresh-preview').addEventListener('click', preview);

  function align() {
    const doc = frame.contentDocument;
    if (!doc || !doc.body) return;
    const height = Math.max(doc.documentElement.scrollHeight, doc.body.scrollHeight, 900);
    frame.style.height = `${height + 4}px`;
    if (window.matchMedia('(max-width: 940px)').matches) return;
    let bottom = 0;
    track.querySelectorAll('.editor-card').forEach(card => {
      const anchor = doc.querySelector(`.${card.dataset.anchor}`);
      const naturalTop = anchor ? anchor.getBoundingClientRect().top : bottom;
      const top = Math.max(naturalTop, bottom + 12);
      card.style.top = `${top}px`;
      bottom = top + card.offsetHeight;
    });
    track.style.height = `${Math.max(height, bottom + 20)}px`;
  }
  frame.addEventListener('load', () => { align(); frame.contentDocument?.querySelectorAll('img').forEach(image => image.addEventListener('load', align)); });
  window.addEventListener('resize', align);

  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    results.replaceChildren();
    const q = search.value.trim();
    if (q.length < 2) return;
    searchTimer = setTimeout(async () => {
      try {
        const response = await fetch(`${config.search}?q=${encodeURIComponent(q)}`, {credentials:'same-origin'});
        const data = await response.json();
        if (search.value.trim() !== q) return;
        if (!data.products.length) { results.textContent = 'Keine Produkte gefunden.'; return; }
        data.products.forEach(product => {
          const button = document.createElement('button');
          button.type = 'button'; button.textContent = product.label;
          button.addEventListener('click', async () => {
            try { await save(); await api(config.add, {product_id: product.id}); window.location.reload(); }
            catch (error) { showError(error); }
          });
          results.append(button);
        });
      } catch (error) { showError(error); }
    }, 250);
  });

  document.querySelectorAll('.product-card').forEach(card => {
    const itemUrl = `${config.productBase}${card.dataset.productId}/`;
    const mode = card.querySelector('[data-price-mode]');
    const value = card.querySelector('[data-price-value]');
    let priceTimer;
    async function updatePrice() {
      try {
        await api(itemUrl, {action:'price', mode:mode.value, value:value.value});
        status.textContent = 'Preis gespeichert'; status.style.color = '#2d8b62';
        preview();
      } catch (error) { showError(error); }
    }
    mode.addEventListener('change', () => {
      value.value = '';
      clearTimeout(priceTimer);
      updatePrice();
    });
    value.addEventListener('input', () => { clearTimeout(priceTimer); priceTimer = setTimeout(updatePrice, 650); });
    card.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', async () => {
      if (button.dataset.action === 'remove' && !confirm('Produkt aus dieser Kampagne entfernen?')) return;
      try { await save(); await api(itemUrl, {action:button.dataset.action}); window.location.reload(); }
      catch (error) { showError(error); }
    }));
  });
  preview();
})();
