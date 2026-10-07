(() => {
  const $ = id => document.getElementById(id);
  const modal = $('editModal'), newModal = $('newModal'), toast = $('catalogToast');
  let selected = null;
  const show = message => { if (!toast) return; toast.textContent = message; toast.classList.add('show'); clearTimeout(show.t); show.t = setTimeout(() => toast.classList.remove('show'), 3200); };
  async function responseData(r) { const text = await r.text(); try { return text ? JSON.parse(text) : {}; } catch { return {detail:`Сервер вернул некорректный ответ (HTTP ${r.status}).`}; } }
  function open(p) {
    selected = p;
    $('editName').textContent = p.name;
    $('editNameInput').value = p.name || '';
    $('editCategory').value = p.category || '';
    $('editDepartment').value = p.department_id || '';
    $('editUnit').value = p.unit || '';
    $('editShelfLife').value = p.shelf_life_minutes ?? '';
    $('editWarning').value = p.warning_before_minutes ?? '';
    $('editCritical').value = p.critical_before_minutes ?? '';
    $('editStorage').value = p.storage_condition || '';
    $('editStatus').value = p.shelf_life_status || 'needs_confirmation';
    $('editMode').value = p.label_mode || 'manual_expiry';
    $('editBasis').value = p.shelf_life_basis || '';
    $('editSource').value = p.shelf_life_source_url || '';
    $('editNote').value = p.verification_note || '';
    modal.hidden = false; document.body.style.overflow = 'hidden';
  }
  function close() { modal.hidden = true; document.body.style.overflow = ''; selected = null; }
  function closeNew() { newModal.hidden = true; document.body.style.overflow = ''; }
  document.querySelectorAll('.edit-product').forEach(b => b.addEventListener('click', () => open(JSON.parse(b.dataset.product))));
  $('closeEdit')?.addEventListener('click', close); $('cancelEdit')?.addEventListener('click', close); modal?.addEventListener('click', e => { if (e.target === modal) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (modal && !modal.hidden) close(); if (newModal && !newModal.hidden) closeNew(); } });
  $('catalogSearch')?.addEventListener('input', e => { const q = e.target.value.toLowerCase().trim(); document.querySelectorAll('#catalogBody tr').forEach(r => r.hidden = !!q && !r.dataset.name.includes(q)); });

  $('saveEdit')?.addEventListener('click', async () => {
    if (!selected) return;
    const body = {
      name: $('editNameInput').value.trim(), category: $('editCategory').value.trim(), source_unit: $('editUnit').value.trim() || null,
      shelf_life_minutes: $('editShelfLife').value ? Number($('editShelfLife').value) : null,
      warning_before_minutes: $('editWarning').value ? Number($('editWarning').value) : null,
      critical_before_minutes: $('editCritical').value ? Number($('editCritical').value) : null,
      department_id: $('editDepartment').value ? Number($('editDepartment').value) : null,
      storage_condition: $('editStorage').value, shelf_life_status: $('editStatus').value, label_mode: $('editMode').value,
      shelf_life_basis: $('editBasis').value, shelf_life_source_url: $('editSource').value, verification_note: $('editNote').value
    };
    const b=$('saveEdit'); b.disabled=true; b.textContent='Сохраняем…';
    try { const r=await fetch('/api/products/'+selected.id,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':window.MARKIFY.csrf},body:JSON.stringify(body)}); const d=await responseData(r); if(!r.ok) throw Error(d.detail||'Ошибка'); show('Сохранено'); setTimeout(()=>location.reload(),350); } catch(e) { show(e.message||'Ошибка'); } finally { b.disabled=false; b.textContent='Сохранить'; }
  });

  $('addProductBtn')?.addEventListener('click',()=>{newModal.hidden=false;document.body.style.overflow='hidden';$('newName').focus();});
  $('closeNew')?.addEventListener('click',closeNew); $('cancelNew')?.addEventListener('click',closeNew); newModal?.addEventListener('click',e=>{if(e.target===newModal)closeNew();});
  $('saveNew')?.addEventListener('click',async()=>{
    const name=$('newName').value.trim(); if(!name){show('Введите название');$('newName').focus();return}
    const body={name,category:$('newCategory').value.trim()||'Без категории',department_id:$('newDepartment').value?Number($('newDepartment').value):null,source_unit:$('newUnit').value.trim()||null,shelf_life_minutes:$('newShelfLife').value?Number($('newShelfLife').value):null,warning_before_minutes:$('newWarning').value?Number($('newWarning').value):null,critical_before_minutes:$('newCritical').value?Number($('newCritical').value):null,storage_condition:$('newStorage').value,shelf_life_status:$('newStatus').value,label_mode:$('newMode').value,shelf_life_basis:$('newBasis').value,shelf_life_source_url:$('newSource').value,verification_note:'Создан вручную в каталоге'};
    const b=$('saveNew'); b.disabled=true;b.textContent='Создаём…';
    try{const r=await fetch('/api/products',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':window.MARKIFY.csrf},body:JSON.stringify(body)});const d=await responseData(r);if(!r.ok)throw Error(d.detail||'Ошибка');show('Продукт создан');setTimeout(()=>location.reload(),350)}catch(e){show(e.message||'Ошибка')}finally{b.disabled=false;b.textContent='Создать'}
  });
  document.querySelectorAll('.archive-product').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Архивировать продукт? Он исчезнет из быстрой печати, история сохранится.'))return;try{const r=await fetch('/api/products/'+b.dataset.id,{method:'DELETE',headers:{'X-CSRF-Token':window.MARKIFY.csrf}});const d=await responseData(r);if(!r.ok){show(d.detail||'Ошибка');return}show('Продукт архивирован');setTimeout(()=>location.reload(),350)}catch(e){show(e.message||'Ошибка')}}));
})();
