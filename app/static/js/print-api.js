(() => {
  const pending = new Map();
  window.MARKIFY.printRequest = async (path, body) => {
    const signature = JSON.stringify([path, body ?? null]);
    const storageKey = 'markify-print:' + signature;
    let key = pending.get(signature);
    try { key ||= sessionStorage.getItem(storageKey); } catch (_) {}
    if (!key) {
      key = Array.from(crypto.getRandomValues(new Uint8Array(24)), x => x.toString(16).padStart(2, '0')).join('');
    }
    pending.set(signature, key);
    try { sessionStorage.setItem(storageKey, key); } catch (_) {}
    // Retain the key on network errors/5xx: the server may already have committed.
    const response = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': window.MARKIFY.csrf, 'Idempotency-Key': key},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    const data = await response.json();
    if (response.status < 500) {
      pending.delete(signature);
      try { sessionStorage.removeItem(storageKey); } catch (_) {}
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Ошибка печати (HTTP ${response.status})`);
    return data;
  };
})();
