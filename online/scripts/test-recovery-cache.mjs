import test from 'node:test';
import assert from 'node:assert/strict';
import {ImportManager,IMPORT_KEY,BACKUP_KEY} from '../import-recovery.mjs';
import {makeAssetFetcher} from '../asset-cache.mjs';
class Storage {
  constructor(raw){this.values=new Map(raw===undefined?[]:[[IMPORT_KEY,raw]]);this.blocked=false;}
  getItem(key){return this.values.get(key)??null;}
  setItem(key,value){if(this.blocked)throw new Error('quota');this.values.set(key,value);}
}
const bundle=policies=>JSON.stringify({city:'杭州',policies});
const sender=async(url,body)=>body.policies[0].bad?{status:400,data:{error:'测试：版本不兼容'}}:{status:200,data:{imported:1}};
test('unreadable original is retained verbatim and backed up',async()=>{
  const raw='{broken policy JSON',storage=new Storage(raw),manager=new ImportManager(storage);
  const result=await manager.restore([],sender);
  assert.equal(storage.getItem(IMPORT_KEY),raw);assert.equal(result.failures.length,1);assert.equal(manager.history()[0].raw,raw);
});
test('partial recovery restores valid policies after a failed record',async()=>{
  const raw=bundle([{id:'one'},{id:'bad',bad:true},{id:'three'}]),storage=new Storage(raw),manager=new ImportManager(storage);
  const result=await manager.restore([],sender);assert.equal(result.restored,2);assert.equal(result.failures[0].id,'bad');assert.equal(storage.getItem(IMPORT_KEY),raw);
});
test('more than thirty cached policies are restored in valid small requests',async()=>{
  const manager=new ImportManager(new Storage(bundle(Array.from({length:35},(_,i)=>({id:'p'+i})))));let calls=0;
  const result=await manager.restore([],async(url,body)=>{assert.equal(body.policies.length,1);calls++;return {status:200,data:{}};});
  assert.equal(calls,35);assert.equal(result.restored,35);
});
test('an identical built-in version is reused but conflicting content is preserved',async()=>{
  const manager=new ImportManager(new Storage(bundle([{id:'same',value:1},{id:'conflict',value:2}])));
  const result=await manager.restore([{value:1,id:'same'},{id:'conflict',value:9}],()=>{throw Error('should not import');});
  assert.equal(result.restored,1);assert.equal(result.failures[0].id,'conflict');assert.equal(manager.history().length,1);
});
test('duplicates do not inflate recovered policy count',async()=>{
  const manager=new ImportManager(new Storage(bundle([{id:'one'},{id:'one'}])));
  assert.equal((await manager.restore([],sender)).restored,1);
});
test('backup failure prevents overwriting the original on later imports',async()=>{
  const raw='broken',storage=new Storage(raw);storage.blocked=true;const manager=new ImportManager(storage);
  await manager.restore([],sender);assert.match(manager.persist({city:'杭州',policies:[{id:'new'}]}),/原记录仍保留/);
  assert.equal(storage.getItem(IMPORT_KEY),raw);assert.throws(()=>manager.useRecovered({city:'杭州',policies:[]}),/原记录仍保留/);
});
test('new imports retain failed records and a verbatim recovery snapshot',async()=>{
  const storage=new Storage(bundle([{id:'bad',bad:true}])),manager=new ImportManager(storage);await manager.restore([],sender);
  assert.equal(manager.persist({city:'杭州',policies:[{id:'new'}]}),'');
  assert.deepEqual(JSON.parse(storage.getItem(IMPORT_KEY)).policies.map(p=>p.id),['bad','new']);assert.ok(storage.getItem(BACKUP_KEY));
});
test('explicit cleanup leaves the original accessible in recovery history',async()=>{
  const raw='broken',storage=new Storage(raw),manager=new ImportManager(storage);await manager.restore([],sender);
  manager.useRecovered({city:'杭州',policies:[]});assert.equal(manager.history()[0].raw,raw);assert.deepEqual(JSON.parse(storage.getItem(IMPORT_KEY)).policies,[]);
});
function fakeCache(){const rows=new Map();return {open:async()=>({match:async key=>rows.get(key)?.clone(),put:async(key,response)=>{rows.set(key,response.clone());}})};}
test('versioned runtime files use cache on repeat visits',async()=>{
  let calls=0;const progress=[];const url='https://example.test/assets/core-v1.zip';
  const fetcher=makeAssetFetcher({nativeFetch:async()=>{calls++;return new Response('hello')},cacheStorage:fakeCache(),allowed:[{url,bytes:5,label:'core'}],onProgress:x=>progress.push(x)});
  assert.equal(await (await fetcher(url)).text(),'hello');assert.equal(await (await fetcher(url)).text(),'hello');assert.equal(calls,1);assert.ok(progress.some(x=>x.cached));
});
test('API bodies and POST requests never enter the static cache',async()=>{
  let calls=0,opens=0;const fetcher=makeAssetFetcher({nativeFetch:async()=>{calls++;return new Response('ok')},cacheStorage:{open:async()=>{opens++;throw Error()}},allowed:[{url:'https://x.test/core.zip',bytes:2}]});
  await fetcher('https://x.test/api/assess',{method:'POST',body:'private profile'});await fetcher('https://x.test/core.zip',{method:'POST'});assert.equal(calls,2);assert.equal(opens,0);
});
test('cache unavailable still permits successful runtime downloads',async()=>{
  const fetcher=makeAssetFetcher({nativeFetch:async()=>new Response('hello'),cacheStorage:{open:async()=>{throw Error('blocked')}},allowed:[{url:'https://x.test/a',bytes:5}]});
  assert.equal(await(await fetcher('https://x.test/a')).text(),'hello');
});
test('truncated components are rejected and never retained as valid cache',async()=>{
  const cache=fakeCache(),fetcher=makeAssetFetcher({nativeFetch:async()=>new Response('bad'),cacheStorage:cache,allowed:[{url:'https://x.test/a',bytes:5}]});
  await assert.rejects(fetcher('https://x.test/a'),/文件不完整/);assert.equal(await(await cache.open()).match('https://x.test/a'),undefined);
});
test('retry can bypass an old component cache without touching user storage',async()=>{
  const cache=fakeCache();await(await cache.open()).put('https://x.test/a',new Response('old'));
  const fetcher=makeAssetFetcher({nativeFetch:async()=>new Response('new'),cacheStorage:cache,allowed:[{url:'https://x.test/a',bytes:3}],bypass:true});
  assert.equal(await(await fetcher('https://x.test/a')).text(),'new');
});
