export function makeAssetFetcher({nativeFetch,cacheStorage,allowed,onProgress=()=>{},bypass=false}){
  const entries=new Map(allowed.map(item=>[item.url,item]));
  return async function cachedFetch(input,options={}){
    const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
    const item=entries.get(url);const method=options.method||(typeof input==='object'?input.method:'GET')||'GET';
    if(!item||method!=='GET')return nativeFetch(input,options);
    let cache;try{cache=await cacheStorage?.open('huicaitong-static-assets-v2');}catch{}
    const hit=bypass?null:await cache?.match(url).catch(()=>null);
    if(hit){onProgress({asset:item.url,label:item.label,loaded:item.bytes,total:item.bytes,cached:true});return hit;}
    const response=await nativeFetch(input,options);if(!response.ok)return response;
    if(!response.body){try{await cache?.put(url,response.clone());}catch{}return response;}
    const reader=response.body.getReader();let loaded=0;const chunks=[];
    for(;;){const {done,value}=await reader.read();if(done)break;chunks.push(value);loaded+=value.byteLength;onProgress({asset:item.url,label:item.label,loaded,total:item.bytes,cached:false});}
    const output=new Uint8Array(loaded);let offset=0;
    for(const chunk of chunks){output.set(chunk,offset);offset+=chunk.byteLength;}
    if(item.bytes&&loaded!==item.bytes)throw new Error('组件文件不完整，请重新加载。');
    const headers=new Headers(response.headers);headers.delete('content-encoding');headers.delete('content-length');
    const result=new Response(output,{status:response.status,headers});
    try{await cache?.put(url,result.clone());}catch{}
    return result;
  };
}
