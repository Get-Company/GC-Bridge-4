(() => {
  const root = document.getElementById('customer-mapping');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const state = {
    sw: [], mt: [], swCustomer: null, mtCustomer: null, customerId: null,
    step: 'customer', pair: { customer: { sw: null, mt: null },
      address: { sw: null, mt: null }, contact: { sw: null, mt: null } },
    mappings: new Map(), editingAddress: '', editingContact: '',
    busy: false, run: 0, editTarget: null,
  };
  const editFields = [
    ['company', 'Firma'], ['name1', 'Name 1'], ['name2', 'Name 2'],
    ['name3', 'Name 3'], ['department', 'Abteilung'], ['street', 'Straße'],
    ['postal_code', 'PLZ'], ['city', 'Ort'], ['country_code', 'Land'],
    ['email', 'E-Mail'], ['phone', 'Telefon'],
  ];

  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value != null) node.textContent = String(value);
    return node;
  }
  function line(node, value) {
    if (value != null && String(value).trim()) node.append(el('span', 'mapping-meta', value));
  }
  function message(value, error = false) {
    $('mapping-message').textContent = value;
    $('mapping-message').classList.toggle('error', error);
  }
  function result(kind, value, error = false) {
    const node = $('mapping-' + kind + '-result');
    node.textContent = value;
    node.classList.toggle('error', error);
  }
  function swAddresses() {
    return state.sw.flatMap(customer => (customer.addresses || []).map(address => ({
      ...address, customerId: customer.id, customerNumber: customer.customerNumber,
    })));
  }
  function mtAddresses() {
    return state.mt.flatMap(customer => (customer.addresses || []).map(address => ({
      ...address, customerErpNr: customer.erp_nr,
    })));
  }
  function swContacts() {
    return swAddresses().filter(address => address.firstName || address.lastName).map(address => ({
      ...address, addressId: address.id,
    }));
  }
  function mtContacts() {
    return mtAddresses().flatMap(address => (address.contacts || []).map(contact => ({
      ...contact, ans_nr: address.ans_nr, customerErpNr: address.customerErpNr,
      id: String(address.customerErpNr) + ':' + String(address.ans_nr) + ':' + String(contact.asp_nr),
    })));
  }
  function identity(kind, side, item) {
    if (kind === 'customer') return side === 'sw' ? item.id : item.erp_nr;
    if (kind === 'address') return side === 'sw' ? item.id : String(item.customerErpNr) + ':' + String(item.ans_nr);
    return side === 'sw' ? item.addressId : item.id;
  }
  function mapped(kind, side, item) {
    if (kind === 'customer') return Boolean(state.customerId &&
      (side === 'sw' ? state.swCustomer?.id === item.id : state.mtCustomer?.erp_nr === item.erp_nr));
    if (kind === 'address') {
      if (side === 'sw') return state.mappings.has(item.id);
      return [...state.mappings.values()].some(row => String(row.ans_nr) === String(item.ans_nr) &&
        state.mtCustomer?.erp_nr === item.customerErpNr);
    }
    if (side === 'sw') return state.mappings.get(item.addressId)?.asp_nr != null;
    return [...state.mappings.values()].some(row => String(row.ans_nr) === String(item.ans_nr) &&
      String(row.asp_nr) === String(item.asp_nr) && state.mtCustomer?.erp_nr === item.customerErpNr);
  }
  function eligible(kind, side, item) {
    if (state.step !== kind || state.busy) return false;
    if (kind === 'customer') return !state.customerId;
    if (!state.customerId) return false;
    if (side === 'sw' && item.customerId !== state.swCustomer?.id) return false;
    if (side === 'mt' && item.customerErpNr !== state.mtCustomer?.erp_nr) return false;
    if (kind === 'contact' && side === 'sw' && !state.mappings.has(item.addressId)) return false;
    if (kind === 'contact' && side === 'mt' && state.pair.contact.sw) {
      const expected = state.mappings.get(state.pair.contact.sw.addressId)?.ans_nr;
      if (String(expected) !== String(item.ans_nr)) return false;
    }
    return true;
  }
  function card(kind, side, item, inSlot = false) {
    const node = el('article', 'mapping-card');
    const already = mapped(kind, side, item);
    if (already) node.classList.add('mapped');
    const name = kind === 'customer'
      ? (side === 'sw' ? item.company || [item.firstName, item.lastName].filter(Boolean).join(' ') : item.name) || 'Kunde'
      : kind === 'contact'
        ? [side === 'sw' ? item.firstName : item.first_name,
           side === 'sw' ? item.lastName : item.last_name].filter(Boolean).join(' ') || 'Ansprechpartner'
        : side === 'sw' ? item.company || [item.firstName, item.lastName].filter(Boolean).join(' ') || 'Adresse'
          : item.name1 || 'Anschrift';
    node.append(el('strong', '', name));
    if (kind === 'customer') {
      line(node, side === 'sw' ? 'Shopware Nr. ' + (item.customerNumber || '–') : 'AdrNr ' + item.erp_nr);
      if (side === 'sw') line(node, 'SW6-ID ' + item.id);
      line(node, item.email);
      line(node, (item.addresses || []).length + ' Anschrift(en)');
    } else if (kind === 'address') {
      line(node, side === 'sw' ? 'Konto ' + item.customerNumber : 'AdrNr ' + item.customerErpNr);
      line(node, side === 'sw' ? 'SW6-Adresse ' + item.id : 'AnsNr ' + item.ans_nr);
      line(node, [item.street, [item.zipcode || item.postal_code, item.city].filter(Boolean).join(' ')].filter(Boolean).join(', '));
      line(node, item.countryIso || item.country_code);
      if (side === 'sw') {
        line(node, [item.is_invoice && 'Rechnung', item.is_shipping && 'Lieferung'].filter(Boolean).join(' · '));
        const mapping = state.mappings.get(item.id);
        if (mapping) line(node, 'Zugeordnet zu AnsNr ' + mapping.ans_nr);
        const bridge = mapping?.bridge;
        if (bridge) line(node, 'Bridge: ' + [bridge.street, bridge.postal_code, bridge.city].filter(Boolean).join(', '));
      }
    } else {
      line(node, side === 'sw' ? 'Aus SW6-Adresse ' + item.addressId : 'AnsNr ' + item.ans_nr + ' · AnspNr ' + item.asp_nr);
      if (side === 'sw' && state.mappings.get(item.addressId)?.asp_nr != null)
        line(node, 'Zugeordnet zu AnspNr ' + state.mappings.get(item.addressId).asp_nr);
      line(node, item.email);
      line(node, item.phone);
      if (side === 'mt' && item.is_default) line(node, 'Bisher Standard');
    }
    if (already) node.append(el('span', 'mapping-flag', 'Zugeordnet'));
    if (!inSlot) {
      const allowed = eligible(kind, side, item);
      const canChange = allowed && already && side === 'sw' && kind !== 'customer';
      const canReuse = allowed && already && side === 'mt';
      const canPick = allowed && !already;
      if (canPick || canChange || canReuse) {
        node.draggable = true;
        node.addEventListener('dragstart', event => {
          event.dataTransfer.setData('text/plain', JSON.stringify({
            kind, side, id: identity(kind, side, item),
          }));
          event.dataTransfer.effectAllowed = 'move';
        });
      }
      if (canPick || canChange || canReuse) {
        const button = el('button', '', canChange ? 'Zuordnung ändern' :
          canReuse ? 'Erneut verwenden' : 'In die Mitte');
        button.type = 'button';
        button.addEventListener('click', () => select(kind, side, item, true));
        node.append(button);
      }
      if (kind === 'address' && side === 'sw' && already && state.customerId &&
          item.customerId === state.swCustomer?.id) {
        const edit = el('button', '', 'Bridge-Daten bearbeiten');
        edit.type = 'button';
        edit.addEventListener('click', () => openEditor(item));
        node.append(edit);
      }
      if (kind === 'contact' && side === 'sw' && allowed && !already) {
        const mapping = state.mappings.get(item.addressId);
        if (mapping) {
          const create = el('button', '', 'Fehlt in microtech? Anlegen');
          create.type = 'button';
          create.addEventListener('click', () => createContact(item));
          node.append(create);
        }
      }
    }
    return node;
  }
  function renderList(id, items, kind, side) {
    const target = $(id);
    target.replaceChildren();
    for (const item of items) target.append(card(kind, side, item));
    if (!items.length) target.append(el('p', 'mapping-meta', 'Keine Einträge vorhanden.'));
  }
  function renderSlots() {
    const slots = [
      ['mapping-sw-customer-slot', 'customer', 'sw', 'Shopware-Konto hier ablegen'],
      ['mapping-mt-customer-slot', 'customer', 'mt', 'microtech-Konto hier ablegen'],
      ['mapping-sw-address-slot', 'address', 'sw', 'Shopware-Adresse hier ablegen'],
      ['mapping-mt-address-slot', 'address', 'mt', 'microtech-Anschrift hier ablegen'],
      ['mapping-sw-contact-slot', 'contact', 'sw', 'Shopware-Ansprechpartner hier ablegen'],
      ['mapping-mt-contact-slot', 'contact', 'mt', 'microtech-Ansprechpartner hier ablegen'],
    ];
    for (const [id, kind, side, placeholder] of slots) {
      const item = state.pair[kind][side] || (kind === 'customer'
        ? (side === 'sw' ? state.swCustomer : state.mtCustomer) : null);
      $(id).replaceChildren(item ? card(kind, side, item, true) : document.createTextNode(placeholder));
    }
  }
  function render() {
    renderList('mapping-sw-customers', state.sw, 'customer', 'sw');
    renderList('mapping-mt-customers', state.mt, 'customer', 'mt');
    renderList('mapping-sw-addresses', swAddresses(), 'address', 'sw');
    renderList('mapping-mt-addresses', mtAddresses(), 'address', 'mt');
    renderList('mapping-sw-contacts', swContacts(), 'contact', 'sw');
    renderList('mapping-mt-contacts', mtContacts(), 'contact', 'mt');
    renderSlots();
    const selectedAddresses = state.swCustomer?.addresses || [];
    const selectedContacts = selectedAddresses.filter(a => a.firstName || a.lastName);
    const mappedAddresses = selectedAddresses.filter(a => state.mappings.has(a.id)).length;
    const mappedContacts = selectedContacts.filter(a => state.mappings.get(a.id)?.asp_nr != null).length;
    const unmatchedMtContacts = mtContacts().filter(contact =>
      contact.customerErpNr === state.mtCustomer?.erp_nr && !mapped('contact', 'mt', contact)).length;
    $('mapping-address-count').textContent = '(' + mappedAddresses + '/' + selectedAddresses.length + ')';
    $('mapping-contact-count').textContent = '(' + mappedContacts + '/' + selectedContacts.length + ')';
    $('mapping-missing-contacts').textContent = selectedContacts.length
      ? (selectedContacts.length - mappedContacts) + ' Shopware-Ansprechpartner noch offen; ' +
        unmatchedMtContacts + ' microtech-Ansprechpartner ohne Shopware-Zuordnung. Fehlende microtech-Ansprechpartner können einzeln angelegt werden.'
      : 'Diese Shopware-Adressen enthalten keinen Ansprechpartner. ' +
        unmatchedMtContacts + ' microtech-Ansprechpartner bleiben ohne Shopware-Zuordnung sichtbar.';
    $('mapping-sync').disabled = !state.customerId || state.busy;
  }
  function setStep(step) {
    state.step = step;
    document.querySelectorAll('.mapping-step').forEach(button =>
      button.classList.toggle('active', button.dataset.step === step));
    document.querySelectorAll('[data-panel]').forEach(panel => {
      panel.hidden = panel.dataset.panel !== step;
    });
    render();
  }
  async function save(payload) {
    const response = await fetch(root.dataset.saveUrl, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json',
        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Speichern fehlgeschlagen.');
    return data;
  }
  async function loadMappings() {
    if (!state.customerId) return;
    const url = new URL(root.dataset.saveUrl, location.origin);
    url.searchParams.set('customer_id', String(state.customerId));
    const response = await fetch(url, { credentials: 'same-origin' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Zuordnungen konnten nicht geladen werden.');
    state.mappings = new Map((data.addresses || []).map(row => [row.shopware_address_id, row]));
  }
  async function mapCustomer() {
    const pair = state.pair.customer;
    if (!pair.sw || !pair.mt || state.busy) return;
    state.busy = true; result('customer', 'Zuordnung wird gespeichert …'); render();
    try {
      const data = await save({ action: 'customer', shopware_id: pair.sw.id,
        erp_nr: pair.mt.erp_nr, job_id: pair.mt.jobId });
      state.swCustomer = pair.sw; state.mtCustomer = pair.mt;
      state.customerId = data.customer_id;
      await loadMappings();
      result('customer', 'Gespeichert: SW6-ID ↔ AdrNr ' + data.erp_nr + '.');
      message('Konto zugeordnet. ' + state.mappings.size +
        ' Adresse(n) bereits zugeordnet. Auch ausgegraute Karten können erneut in die Mitte gezogen werden.');
      setStep('address');
    } catch (error) { result('customer', error.message, true); message(error.message, true); }
    finally { state.busy = false; render(); }
  }
  async function mapAddress() {
    const pair = state.pair.address;
    if (!pair.sw || !pair.mt || !state.customerId || state.busy) return;
    state.busy = true; result('address', 'Adresszuordnung wird gespeichert …'); render();
    try {
      const data = await save({ action: 'address', customer_id: state.customerId,
        shopware_address_id: pair.sw.id, ans_nr: pair.mt.ans_nr,
        job_id: state.mtCustomer.jobId });
      await loadMappings();
      state.pair.address = { sw: null, mt: null };
      state.editingAddress = '';
      result('address', 'Gespeichert: SW6-Adresse ↔ AnsNr ' + data.ans_nr + '.');
      message('Adresse zugeordnet. Weitere Adressen können genauso zugeordnet werden.');
      const allDone = (state.swCustomer.addresses || []).every(a => state.mappings.has(a.id));
      if (allDone) setStep('contact'); else render();
    } catch (error) { result('address', error.message, true); message(error.message, true); }
    finally { state.busy = false; render(); }
  }
  async function mapContact() {
    const pair = state.pair.contact;
    if (!pair.sw || !pair.mt || !state.customerId || state.busy) return;
    const address = state.mappings.get(pair.sw.addressId);
    if (!address || String(address.ans_nr) !== String(pair.mt.ans_nr)) {
      result('contact', 'Der microtech-Ansprechpartner gehört nicht zur zugeordneten Anschrift.', true);
      return;
    }
    state.busy = true; result('contact', 'Ansprechpartner wird zugeordnet …'); render();
    try {
      const data = await save({ action: 'contact', customer_id: state.customerId,
        shopware_address_id: pair.sw.addressId, asp_nr: pair.mt.asp_nr,
        job_id: state.mtCustomer.jobId });
      await loadMappings();
      state.pair.contact = { sw: null, mt: null };
      state.editingContact = '';
      result('contact', 'Gespeichert: SW6-Person ↔ AnsNr ' + data.ans_nr +
        ' / AnspNr ' + data.asp_nr + '.');
      message('Ansprechpartner zugeordnet. Weitere Personen bleiben sichtbar.');
    } catch (error) { result('contact', error.message, true); message(error.message, true); }
    finally { state.busy = false; render(); }
  }
  function select(kind, side, item, explicit = false) {
    if (!eligible(kind, side, item)) return;
    if (mapped(kind, side, item) && !explicit) return;
    if (kind === 'customer') {
      state.pair.customer[side] = item;
      if (side === 'sw') state.swCustomer = item; else state.mtCustomer = item;
    } else state.pair[kind][side] = item;
    if (kind === 'address' && side === 'sw') state.editingAddress = item.id;
    if (kind === 'contact' && side === 'sw') state.editingContact = item.addressId;
    render();
    if (kind === 'customer') mapCustomer();
    if (kind === 'address') mapAddress();
    if (kind === 'contact') mapContact();
  }
  function openEditor(address) {
    const mapping = state.mappings.get(address.id);
    if (!mapping) return;
    state.editTarget = address;
    setStep('address');
    const fields = $('mapping-edit-fields');
    fields.replaceChildren();
    for (const [key, labelText] of editFields) {
      const label = el('label', '', labelText);
      const input = el('input');
      input.name = key;
      input.value = mapping.bridge?.[key] || '';
      label.append(input); fields.append(label);
    }
    $('mapping-address-edit').hidden = false;
  }
  async function createContact(contact) {
    if (!state.customerId || state.busy || !state.mappings.has(contact.addressId)) return;
    state.busy = true; result('contact', 'Ansprechpartner wird in microtech angelegt …'); render();
    try {
      const data = await save({ action: 'create_contact', customer_id: state.customerId,
        shopware_address_id: contact.addressId });
      await loadMappings();
      const mtAddress = (state.mtCustomer.addresses || []).find(address =>
        String(address.ans_nr) === String(data.ans_nr));
      if (mtAddress && !(mtAddress.contacts || []).some(item => String(item.asp_nr) === String(data.asp_nr))) {
        mtAddress.contacts = mtAddress.contacts || [];
        mtAddress.contacts.push({ asp_nr: data.asp_nr, first_name: contact.firstName,
          last_name: contact.lastName, email: contact.email, phone: contact.phone,
          is_default: false });
      }
      state.pair.contact = { sw: null, mt: null };
      result('contact', 'microtech-Ansprechpartner ' + data.asp_nr + ' angelegt und zugeordnet.');
      message('Ansprechpartner in microtech angelegt. Shopware blieb unverändert.');
    } catch (error) { result('contact', error.message, true); message(error.message, true); }
    finally { state.busy = false; render(); }
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
      const response = await fetch(statusUrl, { credentials: 'same-origin' });
      const body = await response.json();
      const job = body.jobs && body.jobs[0];
      if (job && job.state === 'succeeded') return job.data
        ? { ...job.data, jobId: data.microtech_job_id } : null;
      if (job && job.state === 'failed') throw new Error(job.error || 'microtech-Suche fehlgeschlagen.');
    }
    throw new Error('microtech antwortet noch nicht. Bitte die Suche erneut starten.');
  }
  $('mapping-search').addEventListener('submit', async event => {
    event.preventDefault(); const run = ++state.run;
    const numbers = [...new Set($('mapping-numbers').value.split(',')
      .map(value => value.trim()).filter(Boolean))].slice(0, 8);
    state.sw = []; state.mt = []; state.swCustomer = null; state.mtCustomer = null;
    state.customerId = null; state.mappings.clear();
    state.pair = { customer: { sw: null, mt: null }, address: { sw: null, mt: null },
      contact: { sw: null, mt: null } };
    $('mapping-address-edit').hidden = true;
    setStep('customer');
    result('customer', ''); result('address', ''); result('contact', ''); result('sync', '');
    message('Shopware und microtech werden durchsucht …');
    const tasks = numbers.flatMap(number => ['shopware', 'microtech'].map(system =>
      searchCell(number, system).then(item => ({ item, system }))));
    const responses = await Promise.allSettled(tasks);
    if (run !== state.run) return;
    const errors = [];
    for (const response of responses) {
      if (response.status === 'rejected') { errors.push(response.reason.message); continue; }
      const { item, system } = response.value;
      if (item) {
        if (system === 'shopware' && !state.sw.some(row => row.id === item.id)) state.sw.push(item);
        if (system === 'microtech' && !state.mt.some(row => row.erp_nr === item.erp_nr)) state.mt.push(item);
      }
    }
    render();
    message(errors.length ? 'Suche abgeschlossen. ' + errors.join(' ') :
      'Suche abgeschlossen. Konto-Paar in die Mitte ziehen.', !!errors.length);
  });
  for (const button of document.querySelectorAll('.mapping-step')) {
    button.addEventListener('click', () => setStep(button.dataset.step));
  }
  for (const slot of document.querySelectorAll('.mapping-slot')) {
    slot.addEventListener('dragover', event => { event.preventDefault(); slot.classList.add('over'); });
    slot.addEventListener('dragleave', () => slot.classList.remove('over'));
    slot.addEventListener('drop', event => {
      event.preventDefault(); slot.classList.remove('over');
      try {
        const { kind, side, id } = JSON.parse(event.dataTransfer.getData('text/plain'));
        if (kind !== slot.dataset.kind || side !== slot.dataset.side) return;
        const list = kind === 'customer' ? state[side] :
          kind === 'address' ? (side === 'sw' ? swAddresses() : mtAddresses()) :
            (side === 'sw' ? swContacts() : mtContacts());
        const item = list.find(row => identity(kind, side, row) === id);
        if (item) select(kind, side, item, true);
      } catch (_) { /* Ignore unrelated drag data. */ }
    });
  }
  $('mapping-edit-cancel').addEventListener('click', () => {
    $('mapping-address-edit').hidden = true; state.editTarget = null;
  });
  $('mapping-address-edit').addEventListener('submit', async event => {
    event.preventDefault();
    if (!state.editTarget || state.busy) return;
    const fields = Object.fromEntries(editFields.map(([key]) =>
      [key, $('mapping-address-edit').elements.namedItem(key).value]));
    state.busy = true; result('address', 'Bridge-Adresse wird gespeichert …');
    try {
      await save({ action: 'edit_address', customer_id: state.customerId,
        shopware_address_id: state.editTarget.id, fields });
      await loadMappings();
      $('mapping-address-edit').hidden = true; state.editTarget = null;
      result('address', 'Bridge-Adresse gespeichert. Shopware wurde nicht geändert.');
      message('Die geänderten Bridge-Werte werden bei passenden neuen microtech-Bestellungen verwendet.');
    } catch (error) { result('address', error.message, true); message(error.message, true); }
    finally { state.busy = false; render(); }
  });
  $('mapping-sync').addEventListener('click', async () => {
    if (!state.customerId || state.busy) return;
    state.busy = true; result('sync', 'microtech wird aktualisiert und geprüft …'); render();
    try {
      const data = await save({ action: 'sync', customer_id: state.customerId });
      result('sync', data.addresses_checked + ' zugeordnete Adressen in microtech geprüft.');
      message('Übertragung abgeschlossen. Adressen und Ansprechpartner wurden erneut geprüft.');
    } catch (error) { result('sync', error.message, true); message(error.message, true); }
    finally { state.busy = false; render(); }
  });
  render();
})();
