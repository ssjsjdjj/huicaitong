import test from 'node:test';import assert from 'node:assert/strict';
import {DRAFT_KEY,BACKUP_KEY,preserve,save,history,hasWork} from '../v08-review-storage.mjs';
function store(data={}){const m=new Map(Object.entries(data));return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
test('only v08 namespace changes and exact original is backed up',()=>{const s=store({[DRAFT_KEY]:'broken old draft',old54:'keep'});save(s,'new');assert.equal(s.getItem('old54'),'keep');assert.equal(history(s)[0].raw,'broken old draft');});
test('quota failure blocks overwriting',()=>{const s=store({[DRAFT_KEY]:'old'});s.setItem=()=>{throw Error('quota');};assert.throws(()=>save(s,'new'));assert.equal(s.getItem(DRAFT_KEY),'old');});
test('malformed backup history blocks replacement',()=>{const s=store({[DRAFT_KEY]:'old',[BACKUP_KEY]:'broken'});assert.throws(()=>save(s,'new'));assert.equal(s.getItem(DRAFT_KEY),'old');});
test('all earlier backup snapshots retained and deduplicated',()=>{const s=store();preserve(s,'one','a');preserve(s,'two','b');preserve(s,'one','c');assert.deepEqual(history(s).map(x=>x.raw),['one','two']);});
test('partial unconfirmed notes count as work',()=>{assert.equal(hasWork([{confirmed:false,answer:{explanation:'note',missing_fields:[]}}]),true);assert.equal(hasWork([{confirmed:false,answer:null}]),false);});
