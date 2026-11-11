import {makeAssetFetcher} from './asset-cache.mjs?v=a6f3b90eedd78575';
let runtimePromise,pdfReady=false,reviewReady=false,manifest,dispatch,py;
const nativeFetch=self.fetch.bind(self);
let lastProgress=0;
function progress(value){const now=Date.now();if(value.total&&value.loaded<value.total&&now-lastProgress<100)return;lastProgress=now;postMessage({type:'progress',...value});}
async function start(value){
  manifest=value;
  const allowed=manifest.cached_assets.map(a=>({...a,url:new URL(a.url,self.location.href).href}));
  let cacheStorage;try{cacheStorage=self.caches;}catch{}
  self.fetch=makeAssetFetcher({nativeFetch,cacheStorage,allowed,onProgress:progress,bypass:manifest.force_network});
  progress({label:'正在初始化核验引擎…'});
  const {loadPyodide}=await import(manifest.runtime_base+'pyodide.mjs');
  py=await loadPyodide({indexURL:new URL(manifest.runtime_base,self.location.href).href});
  const response=await self.fetch(new URL(manifest.core.url,self.location.href).href);
  if(!response.ok)throw new Error('政策核验程序下载失败');
  py.unpackArchive(await response.arrayBuffer(),'zip',{extractDir:'/app'});
  py.runPython("import sys; sys.path.insert(0,'/app'); from browser_backend import request_json");
  dispatch=py.globals.get('request_json');postMessage({type:'ready'});
}
let queue=Promise.resolve();
self.onmessage=event=>{
  if(event.data.type==='init'){
    runtimePromise=start(event.data.manifest).catch(()=>{postMessage({type:'startup-error',message:'核验引擎加载未完成，已填写内容仍保留，请重试。'});throw new Error('引擎加载失败');});
    runtimePromise.catch(()=>{});return;
  }
  const {id,url,body}=event.data;
  queue=queue.then(async()=>{
    try{
      await runtimePromise;
      if(url.startsWith('/api/v08/')&&!reviewReady){
        progress({label:'首次进入v0.8复核，正在准备冻结任务快照…'});
        const response=await self.fetch(new URL(manifest.review.url,self.location.href).href);
        if(!response.ok)throw new Error('v0.8任务快照下载失败，请重试');
        py.unpackArchive(await response.arrayBuffer(),'zip',{extractDir:'/app'});reviewReady=true;
      }
      if(url==='/api/materials/extract'&&body?.filename?.toLowerCase().endsWith('.pdf')&&!pdfReady){
        progress({label:'首次读取 PDF，正在准备阅读组件…'});
        const response=await self.fetch(new URL(manifest.pdf.url,self.location.href).href);
        if(!response.ok)throw new Error('PDF 阅读组件下载失败，请重试');
        py.unpackArchive(await response.arrayBuffer(),'zip',{extractDir:'/app'});pdfReady=true;
      }
      const result=JSON.parse(dispatch(url,JSON.stringify(body??null)));
      postMessage({id,...result});
    }catch(error){postMessage({id,status:500,data:{error:error.message||'处理未完成，请重试。'}});}
  });
};
