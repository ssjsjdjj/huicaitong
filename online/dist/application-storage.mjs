export const DRAFT_KEY='huicaitong.application-draft.v1';
export const BACKUP_KEY='huicaitong.application-backups.v1';
export function preserveRaw(storage,raw,reason,now=new Date().toISOString()){
  const prior=storage.getItem(BACKUP_KEY),rows=prior===null?[]:JSON.parse(prior);
  if(!Array.isArray(rows))throw new Error('恢复前备份格式异常，请先下载备份；当前记录未覆盖。');
  if(rows.some(r=>r.raw===raw))return rows;
  const next=[...rows,{saved_at:now,reason,raw}];storage.setItem(BACKUP_KEY,JSON.stringify(next));return next;
}
export function saveExplicit(local,session,packet){
  const raw=JSON.stringify(packet),previous=local.getItem(DRAFT_KEY);
  if(previous!==null&&previous!==raw)preserveRaw(session,previous,'保存前的本浏览器草稿');
  local.setItem(DRAFT_KEY,raw);return raw;
}
export function clearSaved(local,session){
  const raw=local.getItem(DRAFT_KEY);if(raw===null)return false;
  preserveRaw(session,raw,'清除本浏览器草稿前');local.removeItem(DRAFT_KEY);return true;
}
export function hasWork(value){
  return Object.entries(value.profile||{}).some(([k,v])=>!['city','application_date'].includes(k)&&v!==null&&v!=='')||Object.values(value.supplementary||{}).some(v=>v!==null&&v!=='')||Object.keys(value.preparation?.items||{}).length>0||(value.deferred||[]).length>0||value.intent!=='all';
}
function stable(value){
  if(Array.isArray(value))return value.map(stable);
  if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])]));
  return value;
}
export function restoreConflicts(current,incoming){
  const fields=x=>({profile:x.profile,supplementary:x.supplementary,intent:x.intent,deferred:x.deferred,preparation:x.preparation});
  return hasWork(current)&&JSON.stringify(stable(fields(current)))!==JSON.stringify(stable(fields(incoming)));
}
