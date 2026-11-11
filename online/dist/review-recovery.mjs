const emptyAnnotation={conclusion:'',evidence_ids:[],missing_fields:[],materials:[],explanation:'',reviewer:''};
function canonical(value){
  if(Array.isArray(value))return value.map(canonical);
  if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])]));
  return value;
}
function normalized(row){
  const copy=structuredClone(row);
  copy.draft_annotation={...emptyAnnotation,...(copy.expected||{}),...(copy.draft_annotation||{})};
  delete copy.draft_annotation.policy_id;
  return JSON.stringify(canonical(copy));
}
export function hasReviewWork(row){
  if(row.review?.status==='reviewed'||!row.case_id.startsWith('review-draft-'))return true;
  const a=row.draft_annotation||{};
  return !!(a.conclusion||a.explanation?.trim()||a.reviewer?.trim()||['evidence_ids','missing_fields','materials'].some(k=>a[k]?.length));
}
export function planReviewRestore(current,incoming){
  const existing=new Map(current.map(r=>[r.case_id,r]));
  const conflicts=incoming.filter(r=>existing.has(r.case_id)&&hasReviewWork(existing.get(r.case_id))&&normalized(r)!==normalized(existing.get(r.case_id))).map(r=>r.case_id);
  return {conflicts,added:incoming.filter(r=>!existing.has(r.case_id)).length,total:incoming.length};
}
export function preserveReviewSnapshot(storage,key,snapshot){
  const raw=storage.getItem(key);
  const history=raw===null?[]:JSON.parse(raw);
  if(!Array.isArray(history))throw new Error('恢复前备份格式异常，请先下载备份，原记录未覆盖。');
  if(history.some(item=>JSON.stringify(item.cases)===JSON.stringify(snapshot.cases)))return history;
  const next=[...history,structuredClone(snapshot)];
  // Write the full history before any case replacement. Quota errors leave it unchanged.
  storage.setItem(key,JSON.stringify(next));
  return next;
}
