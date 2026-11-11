(() => {
  const root = document.getElementById('customer-mapping');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const state = { sw: [], mt: [], swCustomer: null, mtCustomer: null,
    swAddress: null, mtAddress: null, customerId: null, busy: false, run: 0,
    mappedAddresses: new Set() };

  function message(value, error = false) {
    $('mapping-message').textContent = value;
    $('mapping-message').classList.toggle('error', error);
  }
  function result(id, value, error = false) {
    $(id).textContent = value;
    $(id).classList.toggle('error', error);
  }
  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value != null) node.textContent = String(value);
    return node;
  }
  function line(card, value) {
    if (value != null && String(value).trim()) card.append(el('span', 'mapping-meta', value));
  }
  function card(kind, side, item, inSlot = false) {
    const node = el('article', 'mapping-card');
    if (kind === 'address' && side === 'sw' && state.mappedAddresses.has(item.id)) node.classList.add('mapped');
    node.append(el('strong', '', kind === 'customer'
      ? (side === 'sw' ? item.company || [item.firstName, item.lastName].filter(Boolean).join(' ') : item.name) || 'Kunde'
      : side === 'sw' ? item.company || [item.firstName, item.lastName].filter(Boolean).join(' ') || 'Adresse'
      : item.name1 || 'Anschrift'));
    if (kind === 'customer') {
      line(node, side === 'sw' ? `Shopware Nr. ${item.customerNumber || '–'}` : `AdrNr ${item.erp_nr}`);
      if (side === 'sw') line(node, `SW6-ID ${item.id}`);
      line(node, item.email);
      line(node, `${(item.addresses || []).length} Anschrift(en)`);
      if (side === 'sw') line(node, [item.firstName, item.lastName].filter(Boolean).join(' '));
    } else {
      line(node, [item.street, [item.zipcode || item.postal_code, item.city].filter(Boolean).join(' ')].filter(Boolean).join(', '));
      line(node, item.countryIso || item.country_code);
      if (side === 'sw') {
        line(node, `SW6-Adresse ${item.id}`);
        line(node, [item.firstName, item.lastName, item.email].filter(Boolean).join(' · '));
        line(node, [item.department, item.phone].filter(Boolean).join(' · '));
        line(node, [item.is_invoice && 'Rechnung', item.is_shipping && 'Lieferung'].filter(Boolean).join(' · '));
      } else {
        line(node, `AnsNr ${item.ans_nr}`);
        if (item.selectedContact != null) {
          const contact = item.contacts.find(c => String(c.asp_nr) === String(item.selectedContact));
          line(node, contact ? [contact.first_name, contact.last_name, contact.email].filter(Boolean).join(' · ') : 'Ohne Ansprechpartner');
          if (contact) line(node, contact.phone);
        }
        if (!inSlot) {
          const label = el('label', 'mapping-contact-choice', 'Ansprechpartner');
          const select = el('select');
          const empty = el('option', '', 'Nur Anschrift'); empty.value = '';
          select.append(empty);
          for (const contact of item.contacts || []) {
            const option = el('option', '', `${[contact.first_name, contact.last_name].filter(Boolean).join(' ') || 'Ansprechpartner'}${contact.email ? ' · ' + contact.email : ''}${contact.phone ? ' · ' + contact.phone : ''} (Nr. ${contact.asp_nr}${contact.is_default ? ', bisher Standard' : ''})`);
            option.value = String(contact.asp_nr); select.append(option);
          }
          select.value = item.selectedContact == null ? '' : String(item.selectedContact);
          select.addEventListener('change', () => { item.selectedContact = select.value === '' ? null : Number(select.value); });
          label.append(select); node.append(label);
        }
      }
    }
    if (!inSlot) {
      node.draggable = true;
      node.addEventListener('dragstart', event => {
        event.dataTransfer.setData('text/plain', JSON.stringify({ kind, side, id: identity(kind, side, item) }));
        event.dataTransfer.effectAllowed = 'move';
      });
      const button = el('button', '', 'In die Mitte'); button.type = 'button';
      button.addEventListener('click', () => select(kind, side, item));
      node.append(button);
    }
    return node;
  }
  function identity(kind, side, item) {
    if (kind === 'customer') return side === 'sw' ? item.id : item.erp_nr;
    return side === 'sw' ? item.id : `${item.customerErpNr}:${item.ans_nr}`;
  }
  function renderList(id, items, kind, side) {
    const target = $(id); target.replaceChildren();
    for (const item of items) target.append(card(kind, side, item));
    if (!items.length) target.append(el('p', 'mapping-meta', 'Keine Einträge gefunden.'));
  }
  function renderSlots() {
    for (const [id, item, kind, side, placeholder] of [
      ['mapping-sw-customer-slot', state.swCustomer, 'customer', 'sw', 'Shopware-Konto hier ablegen'],
      ['mapping-mt-customer-slot', state.mtCustomer, 'customer', 'mt', 'microtech-Konto hier ablegen'],
      ['mapping-sw-address-slot', state.swAddress, 'address', 'sw', 'Shopware-Adresse hier ablegen'],
      ['mapping-mt-address-slot', state.mtAddress, 'address', 'mt', 'microtech-Anschrift hier ablegen'],
    ]) {
      $(id).replaceChildren(item ? card(kind, side, item, true) : document.createTextNode(placeholder));
    }
  }
  function renderAddresses() {
    const sw = state.customerId && state.swCustomer ? state.swCustomer.addresses || [] : [];
    const mt = state.customerId && state.mtCustomer ? state.mtCustomer.addresses || [] : [];
    renderList('mapping-sw-addresses', sw, 'address', 'sw');
    renderList('mapping-mt-addresses', mt, 'address', 'mt');
  }
  async function save(payload) {
    const response = await fetch(root.dataset.saveUrl, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Die Zuordnung konnte nicht gespeichert werden.');
    return data;
  }
  async function mapCustomer() {
    if (!state.swCustomer || !state.mtCustomer || state.busy) return;
    state.busy = true; result('mapping-customer-result', 'Zuordnung wird gespeichert …');
    try {
      const data = await save({ action: 'customer', shopware_id: state.swCustomer.id,
        erp_nr: state.mtCustomer.erp_nr, job_id: state.mtCustomer.jobId });
      state.customerId = data.customer_id;
      $('mapping-sync').disabled = false;
      result('mapping-customer-result', `Gespeichert: SW6-ID ↔ AdrNr ${data.erp_nr}.`);
      message('Kunden zugeordnet. Jetzt die passenden Adressen und gegebenenfalls Ansprechpartner in die Mitte ziehen.');
      renderAddresses();
    } catch (error) { result('mapping-customer-result', error.message, true); message(error.message, true); }
    finally { state.busy = false; }
  }
  async function mapAddress() {
    if (!state.customerId || !state.swAddress || !state.mtAddress || state.busy) return;
    state.busy = true; result('mapping-address-result', 'Adresszuordnung wird gespeichert …');
    try {
      const data = await save({ action: 'address', customer_id: state.customerId,
        shopware_address_id: state.swAddress.id, ans_nr: state.mtAddress.ans_nr,
        asp_nr: state.mtAddress.selectedContact, job_id: state.mtCustomer.jobId });
      result('mapping-address-result', `Gespeichert: Shopware-Adresse ↔ AnsNr ${data.ans_nr}${data.asp_nr == null ? '' : ` · Ansprechpartner ${data.asp_nr}`}.`);
      state.mappedAddresses.add(state.swAddress.id);
      state.swAddress = null; state.mtAddress = null; renderSlots();
      renderAddresses();
      message('Adresse zugeordnet. Weitere Adressen können genauso zugeordnet werden.');
    } catch (error) { result('mapping-address-result', error.message, true); message(error.message, true); }
    finally { state.busy = false; }
  }
  function select(kind, side, item) {
    if (state.busy) return;
    if (kind === 'address' && !state.customerId) { message('Bitte zuerst die Kundenkonten zuordnen.', true); return; }
    if (kind === 'customer') {
      state.customerId = null; state.swAddress = null; state.mtAddress = null;
      state.mappedAddresses.clear();
      $('mapping-sync').disabled = true;
      state[side === 'sw' ? 'swCustomer' : 'mtCustomer'] = item;
      result('mapping-customer-result', ''); result('mapping-address-result', '');
      renderAddresses();
    } else state[side === 'sw' ? 'swAddress' : 'mtAddress'] = { ...item };
    renderSlots();
    if (kind === 'customer') mapCustomer(); else mapAddress();
  }
  async function searchCell(number, system) {
    const url = new URL(root.dataset.searchUrl, location.origin);
    url.searchParams.set('erp_nr', number); url.searchParams.set('system', system);
    const response = await fetch(url, { credentials: 'same-origin' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Suche fehlgeschlagen.');
    if (system === 'shopware') return data.data && !data.data.error ? data.data : null;
    if (data.data && data.data.error) throw new Error(data.data.error);
    if (!data.microtech_job_id) return null;
    const statusUrl = new URL(root.dataset.statusUrl, location.origin);
    statusUrl.searchParams.set('job_ids', data.microtech_job_id);
    for (let attempt = 0; attempt < 40; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      const result = await fetch(statusUrl, { credentials: 'same-origin' });
      const body = await result.json();
      const job = body.jobs && body.jobs[0];
      if (job && job.state === 'succeeded') return job.data ? { ...job.data, jobId: data.microtech_job_id } : null;
      if (job && job.state === 'failed') throw new Error(job.error || 'microtech-Suche fehlgeschlagen.');
    }
    throw new Error('microtech antwortet noch nicht. Bitte die Suche erneut starten.');
  }
  $('mapping-search').addEventListener('submit', async event => {
    event.preventDefault(); const run = ++state.run;
    const numbers = [...new Set($('mapping-numbers').value.split(',').map(v => v.trim()).filter(Boolean))].slice(0, 8);
    state.sw = []; state.mt = []; state.swCustomer = null; state.mtCustomer = null;
    state.swAddress = null; state.mtAddress = null; state.customerId = null;
    state.mappedAddresses.clear();
    renderList('mapping-sw-customers', [], 'customer', 'sw');
    renderList('mapping-mt-customers', [], 'customer', 'mt');
    $('mapping-sync').disabled = true;
    renderSlots(); renderAddresses(); result('mapping-customer-result', ''); result('mapping-address-result', '');
    message('Shopware und microtech werden durchsucht …');
    const tasks = numbers.flatMap(number => ['shopware', 'microtech'].map(system => searchCell(number, system).then(item => ({ item, system }))));
    const responses = await Promise.allSettled(tasks);
    if (run !== state.run) return;
    const errors = [];
    for (const response of responses) {
      if (response.status === 'rejected') { errors.push(response.reason.message); continue; }
      const { item, system } = response.value;
      if (item) {
        if (system === 'shopware' && !state.sw.some(v => v.id === item.id)) state.sw.push(item);
        if (system === 'microtech' && !state.mt.some(v => v.erp_nr === item.erp_nr)) {
          for (const address of item.addresses || []) address.customerErpNr = item.erp_nr;
          state.mt.push(item);
        }
      }
    }
    renderList('mapping-sw-customers', state.sw, 'customer', 'sw');
    renderList('mapping-mt-customers', state.mt, 'customer', 'mt');
    message(errors.length ? `Suche abgeschlossen. ${errors.join(' ')}` : 'Suche abgeschlossen. Ziehe die beiden passenden Kundenkonten in die Mitte.', !!errors.length);
  });
  for (const slot of document.querySelectorAll('.mapping-slot')) {
    slot.addEventListener('dragover', event => { event.preventDefault(); slot.classList.add('over'); });
    slot.addEventListener('dragleave', () => slot.classList.remove('over'));
    slot.addEventListener('drop', event => {
      event.preventDefault(); slot.classList.remove('over');
      try {
        const { kind, side, id } = JSON.parse(event.dataTransfer.getData('text/plain'));
        if (kind !== slot.dataset.kind || side !== slot.dataset.side) return;
        const list = kind === 'customer' ? state[side] : state[side === 'sw' ? 'swCustomer' : 'mtCustomer']?.addresses || [];
        const item = list.find(value => identity(kind, side, value) === id);
        if (item) select(kind, side, item);
      } catch (_) { /* Ignore external drag data. */ }
    });
  }
  $('mapping-sync').addEventListener('click', async () => {
    if (!state.customerId || state.busy) return;
    state.busy = true; $('mapping-sync').disabled = true;
    result('mapping-sync-result', 'microtech wird aktualisiert und geprüft …');
    try {
      const data = await save({ action: 'sync', customer_id: state.customerId });
      result('mapping-sync-result', `${data.addresses_checked} zugeordnete Adressen in microtech geprüft.`);
      message('Übertragung abgeschlossen. Die Adress- und Ansprechpartnernummern wurden in microtech erneut geprüft.');
    } catch (error) { result('mapping-sync-result', error.message, true); message(error.message, true); }
    finally { state.busy = false; $('mapping-sync').disabled = false; }
  });
})();
