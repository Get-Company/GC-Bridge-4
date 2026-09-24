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
