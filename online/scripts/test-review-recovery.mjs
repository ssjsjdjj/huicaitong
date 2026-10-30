import test from 'node:test';
import assert from 'node:assert/strict';
import {planReviewRestore,preserveReviewSnapshot} from '../review-recovery.mjs';
const row=(id='review-draft-001',explanation='')=>({case_id:id,profile:{city:'杭州'},expected:null,review:{status:'pending',reviewer:null,reviewed_at:null},...(explanation?{draft_annotation:{explanation}}:{})});
function memory(initial={}){const values=new Map(Object.entries(initial));return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};}
test('untouched built-in practice can restore a saved annotation',()=>{
  assert.deepEqual(planReviewRestore([row()],[row(undefined,'已有备注')]),{conflicts:[],added:0,total:1});
});
test('restoring an old draft cannot silently erase current notes',()=>{
  const current=[row(undefined,'尚未备份的备注')],before=structuredClone(current);
  assert.deepEqual(planReviewRestore(current,[row()]).conflicts,['review-draft-001']);assert.deepEqual(current,before);
});
test('identical records do not create a conflict',()=>{
  const a=row(undefined,'备注');assert.equal(planReviewRestore([a],[structuredClone(a)]).conflicts.length,0);
});
test('custom case profile changes are protected even before annotation',()=>{
  const a=row('new-case-1'),b=structuredClone(a);b.profile.degree='master';
  assert.deepEqual(planReviewRestore([a],[b]).conflicts,['new-case-1']);
});
test('new cases and conflicts are counted separately',()=>{
  assert.deepEqual(planReviewRestore([row(undefined,'备注')],[row(),row('new-case-1')]),{conflicts:['review-draft-001'],added:1,total:2});
});
test('replacement snapshots retain every earlier backup and are detached from editing',()=>{
  const store=memory(),first={cases:[row(undefined,'最初备注')],saved_at:'2026-10-30T00:00:00Z'};
  preserveReviewSnapshot(store,'backup',first);first.cases[0].draft_annotation.explanation='修改';
  preserveReviewSnapshot(store,'backup',{cases:[row(undefined,'第二次备注')]});
  const history=JSON.parse(store.getItem('backup'));assert.equal(history.length,2);assert.equal(history[0].cases[0].draft_annotation.explanation,'最初备注');
});
test('quota failure and malformed prior backups block replacement without deleting originals',()=>{
  const store=memory({backup:'[{"cases":[]}]'}),raw=store.getItem('backup');store.setItem=()=>{throw Error('quota');};
  assert.throws(()=>preserveReviewSnapshot(store,'backup',{cases:[row()]}),/quota/);assert.equal(store.getItem('backup'),raw);
  const bad=memory({backup:'broken'});assert.throws(()=>preserveReviewSnapshot(bad,'backup',{cases:[row()]}));assert.equal(bad.getItem('backup'),'broken');
});
test('repeated restore of the same current work does not grow duplicate backups',()=>{
  const store=memory(),snapshot={cases:[row(undefined,'备注')]};preserveReviewSnapshot(store,'backup',snapshot);preserveReviewSnapshot(store,'backup',{...snapshot,saved_at:'later'});assert.equal(JSON.parse(store.getItem('backup')).length,1);
});
