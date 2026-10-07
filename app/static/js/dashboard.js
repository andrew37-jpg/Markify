(() => {
  const $ = id => document.getElementById(id);
  const modal = $('printModal');
  const toast = $('toast');
  const search = $('productSearch');
  const filter = $('categoryFilter');
  let selected = null;
  let printPending = false;
  const repeatPending = new Set();
  let reprintOf = null;
  let selectedDepartment = '';
  let selectedStatus = '';
  let serverNowMs = Date.now();
  const serverStamp = document.body.dataset.serverNow;
  if (serverStamp) {
    const parsed = Date.parse(serverStamp);
    if (!Number.isNaN(parsed)) serverNowMs = parsed;
  }
  let serverOffsetMs = serverNowMs - Date.now();
  const csrf = () => window.MARKIFY?.csrf || '';
  const timezone = () => window.MARKIFY?.timezone || 'Europe/Moscow';

  const show = message => {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(show.timer);
    show.timer = setTimeout(() => toast.classList.remove('show'), 3000);
  };

  const fmt = date => new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: timezone()
  }).format(date);

  const fmtLocalInput = value => {
    if (!value) return '—';
    const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : value;
  };

  const mins = value => {
    const m = Number(value);
    if (!Number.isFinite(m)) return '—';
    const h = Math.floor(m / 60), mm = m % 60;
    if (!h) return `${mm} мин.`;
    return mm ? `${h} ч. ${mm} мин.` : `${h} ч.`;
  };

  const normalizeProduct = p => ({
    id: p.id, name: p.name, category: p.category, unit: p.unit ?? p.source_unit ?? null,
    shelfLife: p.shelfLife ?? p.shelf_life_minutes ?? null,
    warning: p.warning ?? p.warning_before_minutes ?? null,
    critical: p.critical ?? p.critical_before_minutes ?? null,
    status: p.status ?? p.shelf_life_status ?? 'needs_confirmation',
    mode: p.mode ?? p.label_mode ?? 'manual_expiry',
    image: p.image || `/product-icons/${p.id}.svg`,
    storage: p.storage ?? p.storage_condition ?? ''
  });
  const productFromTile = tile => normalizeProduct(JSON.parse(tile.dataset.product));

  async function responseData(response) {
    const text = await response.text();
    if (!text) return {};
    try { return JSON.parse(text); }
    catch { return { detail: `Сервер вернул некорректный ответ (HTTP ${response.status}).` }; }
  }

  function isAuto() {
    return !!selected && selected.status === 'verified' && selected.mode === 'auto_from_shelf_life' && Number(selected.shelfLife) > 0;
  }

  function preview() {
    if (!selected) return;
    if (printPending) return;
    const qty = Math.max(1, Math.min(100, Number($('modalQuantity').value) || 1));
    $('modalQuantity').value = qty;
    const auto = isAuto();
    $('manualExpiryBlock').hidden = auto;
    const hasPrinter = !!$('printerSelect')?.value;
    $('confirmPrint').disabled = !hasPrinter || (!auto && !$('manualExpiry').value);

    if (auto) {
      const now = new Date(Date.now() + serverOffsetMs);
      const exp = new Date(now.getTime() + Number(selected.shelfLife) * 60000);
      $('modalPreview').innerHTML = `<b>Автоматический расчет</b><br>Изготовлено: ${fmt(now)}<br>Годен до: <strong>${fmt(exp)}</strong><br>${mins(selected.shelfLife)} · ${qty} шт.`;
      $('modalExpiryHelp').textContent = reprintOf ? 'Это новая маркировка на основе предыдущей.' : 'Срок рассчитан сервером по подтвержденному правилу продукта.';
    } else {
      const value = $('manualExpiry').value;
      const isValidLocal = !!value && !Number.isNaN(new Date(value).getTime());
      $('confirmPrint').disabled = !hasPrinter || !isValidLocal;
      $('modalPreview').innerHTML = isValidLocal
        ? `<b>${reprintOf ? 'Перепечатка' : 'Ручной срок'}</b><br>Годен до: <strong>${fmtLocalInput(value)}</strong><br>${qty} шт. · дата будет проверена сервером.`
        : '<b>Нужен срок</b><br>Укажите корректную дату и время в часовом поясе кухни.';
      $('modalExpiryHelp').textContent = reprintOf ? 'Введите новый срок по документу/ТК. Исходная маркировка не изменяется.' : 'Для неподтвержденного продукта Markify не придумывает срок.';
    }
  }

  function openProduct(product, labelId = null, sourceExpiry = null) {
    if (printPending) return;
    selected = product;
    reprintOf = labelId;
    $('modalProductImage').src = product.image;
    $('modalProductImage').alt = product.name;
    $('modalProductName').textContent = product.name;
    $('modalProductCategory').textContent = product.category;
    $('modalQuantity').value = 1;
    $('manualExpiry').value = '';
    const now = new Date(Date.now() + serverOffsetMs);
    const part = n => String(n).padStart(2, '0');
    const restaurantLocal = new Intl.DateTimeFormat('sv-SE', {timeZone: timezone(), year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).format(now).replace(' ', 'T');
    $('manualExpiry').min = restaurantLocal;
    $('modalReprintBadge').hidden = !labelId;
    if (labelId) $('modalSourceExpiry').textContent = sourceExpiry ? `Предыдущая маркировка: годен до ${sourceExpiry}` : `Перепечатка маркировки #${labelId}`;
    $('modalProductHint').textContent = isAuto() ? `Подтвержденный срок: ${mins(product.shelfLife)}. ${product.storage || ''}` : 'Автоматический срок не задан. Markify не придумывает срок.';
    preview();
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    $('confirmPrint')?.focus();
  }

  function close() {
    if (printPending) return;
    modal.hidden = true;
    document.body.style.overflow = '';
    selected = null;
    reprintOf = null;
  }

  document.querySelectorAll('.product-tile').forEach(tile => {
    tile.addEventListener('click', () => openProduct(productFromTile(tile)));
  });

  async function openReprint(labelId) {
    try {
      if (!confirm('Создать маркировку для НОВОЙ партии? Нельзя продлевать срок прежней просроченной продукции.')) return;
      const r = await fetch(`/api/labels/${labelId}/reprint`);
      const data = await responseData(r);
      if (!r.ok) throw new Error(data.detail || 'Не удалось открыть перепечатку');
      openProduct(normalizeProduct(data.product), data.label_id, data.source_expires_at);
      preview();
    } catch (error) {
      show(error.message || 'Не удалось открыть перепечатку');
    }
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('.close-label-btn');
    if (!button || !confirm('Продукция использована или списана? Убрать маркировку из контроля сроков, сохранив историю?')) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/labels/${button.dataset.labelId}/close`, {method:'POST', headers:{'X-CSRF-Token':csrf()}});
      const data = await responseData(response);
      if (!response.ok) throw new Error(data.detail || 'Не удалось завершить маркировку');
      await refreshState();
    } catch (error) { show(error.message); button.disabled = false; }
  });

  document.querySelectorAll('.reprint-btn').forEach(btn => btn.addEventListener('click', () => openReprint(btn.dataset.labelId)));
  $('closePrintModal')?.addEventListener('click', close);
  $('cancelModal')?.addEventListener('click', close);
  modal?.addEventListener('click', e => { if (e.target === modal) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal && !modal.hidden) close(); });
  $('qtyMinus')?.addEventListener('click', () => { $('modalQuantity').value = Math.max(1, (Number($('modalQuantity').value) || 1) - 1); preview(); });
  $('qtyPlus')?.addEventListener('click', () => { $('modalQuantity').value = Math.min(100, (Number($('modalQuantity').value) || 1) + 1); preview(); });
  $('modalQuantity')?.addEventListener('input', preview);
  $('manualExpiry')?.addEventListener('input', preview);

  function showBatchResult(data) {
    const modal=$('batchResult'); if(!modal)return;
    $('batchResultTitle').textContent=`${data.department}: создано ${data.created_count} заданий`;
    const skipped=(data.skipped||[]).map(x=>`<li><b>${escapeHtml(x.name)}</b> — ${escapeHtml(x.reason)}</li>`).join('');
    $('batchResultBody').innerHTML=`<p>Принтер: <b>${escapeHtml(data.printer_name||'—')}</b></p>${data.created_count?'<p class="batch-success">✓ Все подходящие продукты поставлены в очередь печати.</p>':''}${data.skipped_count?`<p class="batch-warning">Не напечатано: ${data.skipped_count}. Для этих продуктов нужен подтвержденный автоматический срок.</p><ul class="batch-skipped">${skipped}</ul>`:''}`;
    modal.hidden=false; document.body.style.overflow='hidden';
  }
  async function batchPrintAll(){
    if(!selectedDepartment || selectedDepartment==='none'){show('Выберите конкретный цех для массовой печати.');return;}
    const printer=$('batchPrinterSelect')?.value; if(!printer){show('Подключите Xprinter.');return;}
    const tab=document.querySelector(`.department-tab[data-department="${selectedDepartment}"]`); const name=tab?.firstChild?.textContent?.trim()||'выбранного цеха';
    if(!confirm(`Распечатать все подходящие продукты цеха «${name}»?

Будут напечатаны только продукты с подтвержденным автоматическим сроком.`))return;
    const b=$('batchPrintBtn'); b.disabled=true; b.textContent='Создаём очередь…';
    try{const d=await window.MARKIFY.printRequest('/api/print-jobs/batch',{department_id:Number(selectedDepartment),printer_id:Number(printer)});showBatchResult(d);if(d.created_count)show(`✓ В очередь добавлено ${d.created_count} заданий`);}catch(e){show(e.message||'Ошибка массовой печати')}finally{b.disabled=false;b.textContent='🖨 Распечатать всё'}
  }

  async function waitForJob(jobId, printerName) {
    const started = Date.now();
    show(`Задание #${jobId} отправлено на ${printerName}.`);
    while (Date.now() - started < 30000) {
      await new Promise(r => setTimeout(r, 700));
      try {
        const r = await fetch(`/api/print-jobs/${jobId}/status`);
        const d = await responseData(r);
        if (!r.ok) return;
        if (d.status === 'completed') { show(`✓ Передано принтеру: ${d.product} × ${d.quantity}`); await refreshState(); return; }
        if (d.status === 'failed' || d.status === 'attention') { show(`⚠ Печать #${jobId}: ${d.error || 'нужна проверка'}`); await refreshState(); return; }
      } catch (_) {}
    }
    show(`Задание #${jobId} всё ещё выполняется. Проверьте статус принтера.`);
  }

  async function submitPrint() {
    if (!selected || printPending) return;
    const button = $('confirmPrint');
    if (!button || button.disabled) return;
    if (!$('printerSelect')?.value) { show('Сначала подключите Xprinter в разделе «Принтеры».'); return; }
    button.disabled = true;
    printPending = true;
    button.textContent = 'Отправляем…';
    try {
      const body = {
        product_id: selected.id,
        quantity: Number($('modalQuantity').value) || 1,
        printer_id: Number($('printerSelect').value),
        reprint_of_label_id: reprintOf
      };
      if (!isAuto()) body.expires_at = $('manualExpiry').value || null;
      const data = await window.MARKIFY.printRequest('/api/print-jobs', body);
      printPending = false;
      close();
      show(`Задание #${data.job_id} отправлено…`);
      waitForJob(data.job_id, data.printer_name || 'термопринтер');
    } catch (error) {
      show(error.message || 'Ошибка печати');
    } finally {
      printPending = false;
      button.disabled = false;
      button.textContent = 'Печать';
    }
  }
  $('confirmPrint')?.addEventListener('click', submitPrint);

  async function repeatJob(jobId) {
    if (repeatPending.has(jobId)) return;
    if (!confirm('Отправить точную копию этой маркировки на тот же принтер?')) return;
    repeatPending.add(jobId);
    try {
      const d = await window.MARKIFY.printRequest(`/api/print-jobs/${jobId}/repeat`);
      show(`Повторная печать #${d.job_id} отправлена…`);
      waitForJob(d.job_id, d.printer_name || 'термопринтер');
    } catch(e) { show(e.message || 'Ошибка повторной печати'); }
    finally { repeatPending.delete(jobId); }
  }
  document.querySelectorAll('.repeat-label-btn').forEach(b => b.addEventListener('click', () => repeatJob(b.dataset.jobId)));
  document.querySelectorAll('.quick-product').forEach(b => b.addEventListener('click', () => openProduct(normalizeProduct(JSON.parse(b.dataset.quickProduct)))));

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && modal && !modal.hidden) { close(); return; }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); search?.focus(); return; }
    if (modal && !modal.hidden && e.key === 'Enter' && !e.shiftKey && document.activeElement?.tagName !== 'TEXTAREA') { e.preventDefault(); submitPrint(); return; }
    if (modal && !modal.hidden && e.key === '+' ) { e.preventDefault(); $('qtyPlus')?.click(); }
    if (modal && !modal.hidden && e.key === '-' ) { e.preventDefault(); $('qtyMinus')?.click(); }
  });

  function applyFilter() {
    const q = (search?.value || '').trim().toLowerCase();
    const c = filter?.value || '';
    document.querySelectorAll('.product-tile').forEach(tile => {
      const p = productFromTile(tile);
      tile.hidden = !!((q && !p.name.toLowerCase().includes(q)) || (c && p.category !== c));
    });
    document.querySelectorAll('.chip').forEach(chip => chip.classList.toggle('active', (chip.dataset.category || '') === c));
    applyDepartmentAndStatusFilters();
  }
  search?.addEventListener('input', applyFilter);
  filter?.addEventListener('change', applyFilter);
  document.querySelectorAll('.chip').forEach(chip => chip.addEventListener('click', () => { if (filter) filter.value = chip.dataset.category || ''; applyFilter(); }));
  $('refreshBtn')?.addEventListener('click', refreshState);
  $('batchPrintBtn')?.addEventListener('click', batchPrintAll);
  $('closeBatchResult')?.addEventListener('click',()=>{ $('batchResult').hidden=true; document.body.style.overflow=''; });
  $('batchResultOk')?.addEventListener('click',()=>{ $('batchResult').hidden=true; document.body.style.overflow=''; });
  $('batchResult')?.addEventListener('click',e=>{if(e.target.id==='batchResult'){ $('batchResult').hidden=true; document.body.style.overflow=''; }});

  function applyDepartmentAndStatusFilters(){
    document.querySelectorAll('.product-tile').forEach(tile=>{
      const dept=tile.dataset.departmentId||'none';
      const q=(search?.value||'').trim().toLowerCase();
      const c=filter?.value||''; const p=productFromTile(tile);
      tile.hidden=!!((selectedDepartment && dept!==selectedDepartment)||(q&&!p.name.toLowerCase().includes(q))||(c&&p.category!==c));
    });
    document.querySelectorAll('.quick-product').forEach(tile=>{tile.hidden=!!(selectedDepartment && (tile.dataset.departmentId||'none')!==selectedDepartment);});
    document.querySelectorAll('#labelsBody tr[data-department-id]').forEach(row=>{const dept=row.dataset.departmentId||'none';const st=row.dataset.status||'';row.hidden=!!((selectedDepartment&&dept!==selectedDepartment)||(selectedStatus&&st!==selectedStatus));});
  }
  document.querySelectorAll('.department-tab').forEach(tab=>tab.addEventListener('click',()=>{selectedDepartment=tab.dataset.department||'';document.querySelectorAll('.department-tab').forEach(x=>x.classList.toggle('active',x===tab));applyDepartmentAndStatusFilters();const hint=$('departmentHint');if(hint){hint.textContent=selectedDepartment&&selectedDepartment!=='none'?`Выбран цех «${tab.textContent.replace(/\s+\d+$/,'').trim()}». Здесь отображаются только его продукты и маркировки.`:'Показаны продукты и маркировки всех цехов.';}}));
  document.querySelectorAll('.stat-clickable').forEach(stat=>stat.addEventListener('click',()=>{selectedStatus=stat.dataset.statusFilter||'';document.querySelectorAll('.stat-clickable').forEach(x=>x.classList.toggle('selected',x===stat));document.querySelector('#control')?.scrollIntoView({behavior:'smooth',block:'start'});applyDepartmentAndStatusFilters();}));


  async function refreshState() {
    try {
      const r = await fetch('/api/dashboard/state', {headers: {'Accept': 'application/json'}});
      const data = await responseData(r);
      if (!r.ok) return;
      Object.entries(data.counts || {}).forEach(([key, value]) => {
        const el = document.querySelector(`[data-count="${key}"]`);
        if (el) el.textContent = value;
      });
      if (data.server_now_utc) {
        const parsed = Date.parse(data.server_now_utc);
        if (!Number.isNaN(parsed)) serverOffsetMs = parsed - Date.now();
      }
      const printerStatus = $('printerStatus');
      if (printerStatus) {
        const online = (data.printers || []).find(p => p.online);
        printerStatus.textContent = online ? `🟢 ${online.name} · агент онлайн` : ((data.printers || []).length ? '🟡 Принтер подключен, но агент не отвечает' : '🔴 Xprinter не подключен');
      }
      const body = $('labelsBody');
      if (!body) return;
      const labels = data.labels || [];
      const titles = {active:'Активна', warning:'Скоро заменить', critical:'Пора менять', expired:'Просрочено'};
      body.innerHTML = labels.length ? labels.map(l => {
        const action = l.print_job_id && l.print_status === 'completed' ? `<button class="btn small repeat-label-btn" type="button" data-job-id="${l.print_job_id}">Повторить</button>` : '';
        const re = l.status === 'expired' ? ` <button class="btn small danger reprint-btn" type="button" data-label-id="${l.id}">Новая партия</button>` : '';
        return `<tr class="row-${l.status}" data-department-id="${l.department_id || 'none'}" data-status="${l.status}"><td><span class="status ${l.status}">${titles[l.status] || l.status}</span></td><td><b>${escapeHtml(l.product)}</b><small>${escapeHtml(l.category)}</small></td><td><strong>${escapeHtml(l.department_name || 'Без цеха')}</strong></td><td>${l.created_at}</td><td>${l.expires_at}</td><td>${escapeHtml(l.mode)}</td><td class="actions-cell">${action}${re} <button class="btn small close-label-btn" type="button" data-label-id="${l.id}">Завершить</button></td></tr>`;
      }).join('') : '<tr><td colspan="7" class="empty">Пока нет маркировок.</td></tr>';
      body.querySelectorAll('.reprint-btn').forEach(btn => btn.addEventListener('click', () => openReprint(btn.dataset.labelId))); body.querySelectorAll('.repeat-label-btn').forEach(btn => btn.addEventListener('click', () => repeatJob(btn.dataset.jobId)));
      applyDepartmentAndStatusFilters();
    } catch (error) {
      // Keep the kitchen UI usable even if the background refresh temporarily fails.
      // Do not replace the current label table with an error page.
    }
  }
  function escapeHtml(v) { return String(v).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
  setInterval(refreshState, Number(document.body.dataset.refresh || 10) * 1000);
})();
