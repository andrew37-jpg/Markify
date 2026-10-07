(() => {
  const $ = id => document.getElementById(id);
  const toast = $('departmentToast');
  const csrf = () => window.MARKIFY?.csrf || '';
  const products = Array.from(document.querySelectorAll('[data-department-card]')).length ? null : null;
  let allProducts = [];
  let currentDepartment = null;
  let editingId = null;
  const show = m => { if(!toast)return; toast.textContent=m; toast.classList.add('show'); clearTimeout(show.t); show.t=setTimeout(()=>toast.classList.remove('show'),3000); };
  async function data(r){const t=await r.text();try{return t?JSON.parse(t):{}}catch{return {detail:`Некорректный ответ сервера (HTTP ${r.status})`}}}
  async function loadProducts(){
    const r=await fetch('/api/products'); const d=await data(r); if(!r.ok) throw Error(d.detail||'Не удалось загрузить продукты'); allProducts=d.items||[];
  }
  function renderProductList(){
    const root=$('departmentProductList'); if(!root)return;
    const q=($('departmentProductSearch')?.value||'').trim().toLowerCase();
    root.innerHTML=allProducts.filter(p=>!q||p.name.toLowerCase().includes(q)||p.category.toLowerCase().includes(q)).map(p=>{
      const checked=Number(p.department_id)===Number(currentDepartment);
      const other=p.department_id && !checked;
      return `<label class="department-product-row ${other?'assigned-other':''}"><input type="checkbox" value="${p.id}" ${checked?'checked':''}><span><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.category)} · ${escapeHtml(p.department_name||'Без цеха')}${other?' · уже назначен':''}</small></span></label>`;
    }).join('') || '<div class="empty">Продукты не найдены.</div>';
  }
  async function openProducts(id){
    currentDepartment=id; await loadProducts(); const d=(await (async()=>{const r=await fetch('/api/departments');return data(r)})()).items?.find(x=>Number(x.id)===Number(id));
    $('departmentProductsTitle').textContent=d?.name||'Цех'; $('departmentProductSearch').value=''; renderProductList(); $('departmentProductsModal').hidden=false; document.body.style.overflow='hidden';
  }
  async function saveProducts(){
    if(!currentDepartment)return;
    const ids=Array.from(document.querySelectorAll('#departmentProductList input[type=checkbox]:checked')).map(x=>Number(x.value));
    const b=$('saveDepartmentProducts'); b.disabled=true; b.textContent='Сохраняем…';
    try{const r=await fetch(`/api/departments/${currentDepartment}/products`,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},body:JSON.stringify({product_ids:ids})});const d=await data(r);if(!r.ok)throw Error(d.detail||'Ошибка');show(`Состав сохранён: ${ids.length} продуктов`);setTimeout(()=>location.reload(),450);}catch(e){show(e.message||'Ошибка')}finally{b.disabled=false;b.textContent='Сохранить состав'}
  }
  function closeProducts(){ $('departmentProductsModal').hidden=true; document.body.style.overflow=''; currentDepartment=null; }
  document.querySelectorAll('.manage-department-products').forEach(b=>b.addEventListener('click',()=>openProducts(Number(b.dataset.id)).catch(e=>show(e.message))));
  document.querySelectorAll('.assign-unassigned').forEach(b=>b.addEventListener('click',async()=>{
    const select=document.querySelector(`.unassigned-department-select[data-product-id=\"${b.dataset.productId}\"]`);
    const departmentId=Number(select?.value||0); if(!departmentId){show('Выберите цех');return;}
    try{const r=await fetch(`/api/departments/${departmentId}/products`,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},body:JSON.stringify({product_ids:[Number(b.dataset.productId)]})});const d=await data(r);if(!r.ok)throw Error(d.detail||'Ошибка');location.reload();}catch(e){show(e.message||'Ошибка')}}));
  $('departmentProductSearch')?.addEventListener('input',renderProductList);
  $('saveDepartmentProducts')?.addEventListener('click',saveProducts); $('closeDepartmentProducts')?.addEventListener('click',closeProducts); $('cancelDepartmentProducts')?.addEventListener('click',closeProducts);
  $('departmentProductsModal')?.addEventListener('click',e=>{if(e.target.id==='departmentProductsModal')closeProducts()});

  const editModal=$('departmentEditModal');
  function openEdit(id,name){editingId=id;$('departmentEditTitle').textContent=id?'Изменить цех':'Новый цех';$('departmentName').value=name||'';editModal.hidden=false;document.body.style.overflow='hidden';$('departmentName').focus()}
  function closeEdit(){if(!editModal)return;editModal.hidden=true;document.body.style.overflow='';editingId=null}
  $('addDepartmentBtn')?.addEventListener('click',()=>openEdit(null,''));
  document.querySelectorAll('.edit-department').forEach(b=>b.addEventListener('click',()=>openEdit(Number(b.dataset.id),b.dataset.name)));
  $('closeDepartmentEdit')?.addEventListener('click',closeEdit); $('cancelDepartmentEdit')?.addEventListener('click',closeEdit);
  $('saveDepartmentEdit')?.addEventListener('click',async()=>{
    const name=$('departmentName').value.trim(); if(!name){show('Введите название цеха');return}
    const url=editingId?`/api/departments/${editingId}`:'/api/departments'; const method=editingId?'PATCH':'POST'; const b=$('saveDepartmentEdit'); b.disabled=true;
    try{const r=await fetch(url,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},body:JSON.stringify({name})});const d=await data(r);if(!r.ok)throw Error(d.detail||'Ошибка');show('Сохранено');setTimeout(()=>location.reload(),400)}catch(e){show(e.message||'Ошибка')}finally{b.disabled=false}
  });
  document.querySelectorAll('.archive-department').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Убрать цех? Продукты будут переведены в «Без цеха». История печати сохранится.'))return;try{const r=await fetch(`/api/departments/${b.dataset.id}`,{method:'DELETE',headers:{'X-CSRF-Token':csrf()}});const d=await data(r);if(!r.ok)throw Error(d.detail||'Ошибка');location.reload()}catch(e){show(e.message||'Ошибка')}}));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(editModal&&!editModal.hidden)closeEdit();if($('departmentProductsModal')&&!$('departmentProductsModal').hidden)closeProducts();}});
  function escapeHtml(v){return String(v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
})();
