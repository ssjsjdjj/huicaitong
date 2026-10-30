export const IMPORT_KEY='huicaitong-online-imports-v1';
export const BACKUP_KEY='huicaitong-online-import-backups-v1';
export function canonical(value){
  if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
export class ImportManager {
  constructor(storage){this.storage=storage;this.raw=null;this.failures=[];this.restored=0;this.notice='';}
  read(){
    try{this.raw=this.storage.getItem(IMPORT_KEY);return this.raw;}
    catch{this.notice='浏览器存储不可用；本次导入仅在当前标签页使用，请下载备份。';return null;}
  }
  backup(reason){
    if(this.raw===null)return true;
    try{
      const text=this.storage.getItem(BACKUP_KEY);const history=text?JSON.parse(text):[];
      if(!Array.isArray(history))throw new Error('备份目录格式无效');
      if(!history.some(x=>x.raw===this.raw)){
        history.push({saved_at:new Date().toISOString(),reason,raw:this.raw});
        this.storage.setItem(BACKUP_KEY,JSON.stringify(history));
      }
      return true;
    }catch{this.notice='自动备份未成功，原记录仍保留。请先下载原始备份；新的导入暂不写入浏览器存储。';return false;}
  }
  async restore(catalogue,send){
    this.failures=[];this.restored=0;this.read();if(!this.raw)return this.summary();
    let payload;
    try{
      payload=JSON.parse(this.raw);
      if(payload?.city!=='杭州'||!Array.isArray(payload.policies))throw new Error('应为含 city 和 policies 的杭州政策文件');
      if(payload.policies.length>300)throw new Error('缓存超过 300 份政策，请下载后分批整理');
    }catch(error){this.failures.push({id:'原始导入记录',reason:'格式无法读取：'+error.message});this.backup('导入记录格式无法读取');return this.summary();}
    const existing=new Map(catalogue.map(p=>[p.id,p])),counted=new Set();
    for(const [index,policy] of payload.policies.entries()){
      const id=typeof policy?.id==='string'?policy.id:'第 '+(index+1)+' 条';
      if(!policy||typeof policy!=='object'||Array.isArray(policy)){this.failures.push({id,reason:'政策记录须为对象'});continue;}
      if(existing.has(policy.id)){
        if(canonical(existing.get(policy.id))===canonical(policy)){if(!counted.has(policy.id))this.restored++;counted.add(policy.id);}
        else this.failures.push({id,reason:'与当前知识库的同编号政策内容不同，请核对版本并使用新编号'});
        continue;
      }
      const result=await send('/api/import',{city:'杭州',policies:[policy]});
      if(result.status<400){this.restored++;counted.add(policy.id);existing.set(policy.id,policy);}
      else this.failures.push({id,reason:result.data?.error||'记录验证未通过'});
    }
    if(this.failures.length)this.backup('部分政策恢复失败');return this.summary();
  }
  persist(imports){
    let policies=imports.policies;
    if(this.failures.length&&this.raw!==null){
      if(!this.backup('保留恢复失败记录并保存新导入'))return this.notice;
      try{
        const old=JSON.parse(this.raw);
        if(Array.isArray(old.policies)){
          const live=new Map(policies.map(p=>[p.id,p]));
          const retained=old.policies.filter(p=>!p?.id||!live.has(p.id)||canonical(p)!==canonical(live.get(p.id)));
          policies=[...retained,...policies];
        }
      }catch{/* The original text is preserved in backup history. */}
    }
    try{this.storage.setItem(IMPORT_KEY,JSON.stringify({city:'杭州',policies}));return '';}
    catch{return '政策已在当前标签页导入，但写入浏览器存储失败。请下载备份后再关闭页面。';}
  }
  useRecovered(imports){
    if(!this.backup('用户选择仅保留已恢复政策'))throw new Error(this.notice);
    try{this.storage.setItem(IMPORT_KEY,JSON.stringify(imports));}
    catch{throw new Error('保存失败，原记录仍保留，请先下载备份。');}
    this.raw=JSON.stringify(imports);this.failures=[];this.notice='';return this.summary();
  }
  history(){try{const rows=JSON.parse(this.storage.getItem(BACKUP_KEY)||'[]');return Array.isArray(rows)?rows:[];}catch{return [];}}
  summary(){return {restored:this.restored,failures:[...this.failures],notice:this.notice,raw:this.raw};}
}
