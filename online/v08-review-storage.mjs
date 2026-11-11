export const DRAFT_KEY='huicaitong.v08-review.draft.v1';
export const BACKUP_KEY='huicaitong.v08-review.backups.v1';
export function history(store){const raw=store.getItem(BACKUP_KEY);const rows=raw===null?[]:JSON.parse(raw);if(!Array.isArray(rows)||rows.some(r=>!r||typeof r.raw!=='string'))throw Error('既有备份无法读取');return rows;}
export function preserve(store,raw,reason){const rows=history(store);if(rows.some(r=>r.raw===raw))return;rows.push({raw,reason,saved_at:new Date().toISOString()});store.setItem(BACKUP_KEY,JSON.stringify(rows));}
export function save(store,raw){const old=store.getItem(DRAFT_KEY);if(old!==null&&old!==raw)preserve(store,old,'覆盖已保存草稿前');store.setItem(DRAFT_KEY,raw);}
export function hasWork(records){return records.some(r=>r.confirmed||r.answer&&Object.values(r.answer).some(v=>Array.isArray(v)?v.length:!!v));}
