'use strict';
(() => {
  const nativeFetch=window.fetch.bind(window),pending=new Map();
  let sequence=0,worker,engineReady=false,runtimePromise=null,bootstrap,manifest,manager,bootPromise;
  let currentImports={city:'杭州',policies:[]},restoring=false;
  const cacheHits=new Set();
  const text=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
  function status(message,progress){
    text('engine-message',message);
    const bar=document.getElementById('engine-progress');
    if(progress===undefined)bar.removeAttribute('value');else bar.value=progress;
    document.getElementById('engine-status').dataset.state=engineReady?'ready':'loading';
  }
  function saveFile(name,value,type='application/json'){
    const url=URL.createObjectURL(new Blob([value],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function renderRecovery(){
    if(!manager)return;
    const info=manager.summary(),banner=document.getElementById('import-recovery-banner');
    banner.hidden=!info.failures.length&&!info.notice;
    text('import-recovery-summary',info.failures.length?`已恢复 ${info.restored} 份，另有 ${info.failures.length} 条需要处理。原始记录仍保留，不会自动删除。`:info.notice);
    text('import-recovery-notice',info.notice);
    const list=document.getElementById('import-recovery-errors');list.replaceChildren();
    for(const row of info.failures.slice(0,10)){const li=document.createElement('li');li.textContent=row.id+'：'+row.reason;list.append(li);}
    if(info.failures.length>10){const li=document.createElement('li');li.textContent='其余记录请下载原始备份核对。';list.append(li);}
    document.getElementById('import-original-backup').disabled=info.raw===null;
    document.getElementById('import-live-backup').disabled=currentImports.policies.length===0;
    const history=document.getElementById('import-backup-history');history.replaceChildren();
    manager.history().forEach((row,index)=>{
      const item=document.createElement('div');item.className='backup-row';
      const label=document.createElement('span');label.textContent=`${row.saved_at||'时间未知'} · ${row.reason||'恢复备份'}`;
      const button=document.createElement('button');button.className='btn btn-quiet small';button.textContent='下载原始记录';button.type='button';
      button.addEventListener('click',()=>saveFile('惠才通-政策恢复备份-'+(index+1)+'.txt',row.raw,'text/plain;charset=utf-8'));
      item.append(label,button);history.append(item);
    });
    if(!history.children.length){const p=document.createElement('p');p.textContent='暂无恢复备份。只有恢复失败或你选择整理记录时，才会保留原始快照。';history.append(p);}
  }
  function rawRequest(url,body){
    return new Promise((resolve,reject)=>{
      const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(new Error('本次处理超时，输入仍保留，请重试。'));},45000);
      pending.set(id,{resolve,reject,timer});worker.postMessage({id,url,body:body??null});
    });
  }
  function signalUpdate(){window.dispatchEvent(new Event('hct:policies-updated'));}
  async function boot(){
    const [response,module]=await Promise.all([nativeFetch('/assets.json',{cache:'no-store'}),import('/import-recovery.mjs?v=16678c564b31ecf5')]);
    if(!response.ok)throw new Error('页面资源清单无法加载，请重试。');
    manifest=await response.json();
    const data=await nativeFetch(manifest.bootstrap.url);if(!data.ok)throw new Error('政策资料无法加载，请重试。');
    bootstrap=await data.json();
    manager=new module.ImportManager({getItem:key=>localStorage.getItem(key),setItem:(key,value)=>localStorage.setItem(key,value)});
    document.querySelectorAll('[data-example]').forEach(button=>button.disabled=false);
    status('页面已就绪，可先填写情况；核验引擎将在后台准备。');
    const background=()=>ensureRuntime().catch(()=>{});
    if(window.requestIdleCallback)requestIdleCallback(background,{timeout:1800});else setTimeout(background,700);
    return bootstrap;
  }
  async function ensureRuntime(forceNetwork=false){
    await bootPromise;
    if(engineReady)return;
    if(runtimePromise&&!forceNetwork)return runtimePromise;
    worker?.terminate();engineReady=false;
    document.getElementById('engine-retry').hidden=true;status('正在准备核验引擎，页面可继续填写…');
    runtimePromise=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>fail('组件加载时间较长，已填写内容仍保留，请检查网络后重试。'),90000);
      function fail(message){
        clearTimeout(timer);worker?.terminate();engineReady=false;runtimePromise=null;
        status(message,0);document.getElementById('engine-status').dataset.state='error';document.getElementById('engine-retry').hidden=false;
        for(const job of pending.values()){clearTimeout(job.timer);job.reject(new Error(message));}pending.clear();reject(new Error(message));
      }
      try{worker=new Worker('/runtime-worker.mjs?v='+manifest.build_id,{type:'module'});}catch{fail('当前浏览器未能启动核验引擎，请使用较新的浏览器重试。');return;}
      worker.onerror=()=>fail('核验引擎加载未完成，填写内容仍保留，请重试。');
      worker.onmessage=async({data})=>{
        if(data.type==='progress'){
          if(data.cached&&data.asset)cacheHits.add(data.asset);
          const bytes=data.total?` · ${(data.loaded/1048576).toFixed(1)} / ${(data.total/1048576).toFixed(1)} MB`:'';
          status((data.cached?'正在复用缓存：':'')+data.label+bytes,data.total?Math.min(100,Math.round(data.loaded/data.total*100)):undefined);return;
        }
        if(data.type==='startup-error'){fail(data.message);return;}
        if(data.type==='ready'){
          try{
            const catalogue=await rawRequest('/api/policies');
            await manager.restore(catalogue.data.policies,rawRequest);
            clearTimeout(timer);engineReady=true;status('核验引擎已就绪'+(cacheHits.size?` · 已复用 ${cacheHits.size} 项缓存组件`:'')+' · PDF 阅读组件按需加载。',100);
            document.getElementById('engine-status').dataset.state='ready';renderRecovery();resolve();signalUpdate();
          }catch{fail('导入记录恢复未完成，原始记录仍保留，请重试。');}
          return;
        }
        const job=pending.get(data.id);if(!job)return;clearTimeout(job.timer);pending.delete(data.id);
        if(data.imports)currentImports=data.imports;
        if(data.id)job.resolve(data);
        if(engineReady)status('核验引擎已就绪'+(cacheHits.size?` · 已复用 ${cacheHits.size} 项缓存组件`:'')+' · 申请资料只在浏览器内处理。',100);
      };
      worker.postMessage({type:'init',manifest:{...manifest,force_network:forceNetwork}});
    });
    runtimePromise.catch(()=>{});return runtimePromise;
  }
  window.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/api/'))return nativeFetch(input,options);
    await bootPromise;
    const method=options.method||'GET',key=url.pathname+url.search;
    if(method==='GET'&&!engineReady&&Object.hasOwn(bootstrap,key))return new Response(JSON.stringify(bootstrap[key]),{headers:{'Content-Type':'application/json'}});
    await ensureRuntime();
    const body=options.body===undefined?null:JSON.parse(options.body),result=await rawRequest(key,body);
    if(key==='/api/import'&&result.status<400){const warning=manager.persist(result.imports);if(warning)result.data.storage_notice=warning;renderRecovery();}
    return new Response(JSON.stringify(result.data),{status:result.status,headers:{'Content-Type':'application/json'}});
  };
  document.querySelectorAll('[data-example]').forEach(button=>button.disabled=true);
  document.getElementById('engine-retry').addEventListener('click',async()=>{
    try{
      if(!bootstrap){bootPromise=boot();await bootPromise;signalUpdate();}
      await ensureRuntime(true);
    }catch{}
  });
  document.getElementById('import-original-backup').addEventListener('click',()=>saveFile('惠才通-政策原始恢复记录.txt',manager.raw||'','text/plain;charset=utf-8'));
  document.getElementById('import-live-backup').addEventListener('click',()=>saveFile('惠才通-当前可用政策.json',JSON.stringify(currentImports,null,2)));
  document.getElementById('import-retry').addEventListener('click',async()=>{
    if(restoring)return;restoring=true;const button=document.getElementById('import-retry');button.disabled=true;
    try{await ensureRuntime();const catalogue=await rawRequest('/api/policies');await manager.restore(catalogue.data.policies,rawRequest);renderRecovery();signalUpdate();}
    catch(error){text('import-recovery-notice',error.message);}finally{restoring=false;button.disabled=false;}
  });
  document.getElementById('import-use-recovered').addEventListener('click',()=>{
    try{manager.useRecovered(currentImports);renderRecovery();text('import-backup-status','原始记录已保存到下方恢复备份。当前仅保留可用政策。');}
    catch(error){text('import-recovery-notice',error.message);}
  });
  window.addEventListener('hct:policies-updated',()=>{if(typeof window.refresh==='function')window.refresh().catch(()=>{});});
  bootPromise=boot();
  bootPromise.catch(error=>{status(error.message,0);document.getElementById('engine-retry').hidden=false;});
})();
