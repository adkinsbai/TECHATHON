type SavedAsset = { bytes: ArrayBuffer; name: string; source: 'import' | 'rodin' };
function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('mori-workbench', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('assets');
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
}
export async function loadSavedAsset(): Promise<SavedAsset | undefined> {
  const db = await openDB();
  try { return await new Promise((resolve, reject) => { const tx = db.transaction('assets'); const request = tx.objectStore('assets').get('current'); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); }); }
  finally { db.close(); }
}
export async function saveAsset(asset: SavedAsset | null) {
  const db = await openDB();
  try { await new Promise<void>((resolve, reject) => { const tx = db.transaction('assets', 'readwrite'); if (asset) tx.objectStore('assets').put(asset, 'current'); else tx.objectStore('assets').delete('current'); tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); }); }
  finally { db.close(); }
}
