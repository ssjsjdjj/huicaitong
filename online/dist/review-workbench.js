'use strict';
const REVIEW_SESSION_KEY='huicaitong.review-progress.v1';
const REVIEW_BACKUP_KEY='huicaitong.review-recovery.v1';
const REVIEW_IMPORT_BACKUP_KEY='huicaitong.review-import-backups.v1';
let reviewCacheBlocked=false,reviewRawBackup=null,frozenDataset=null,benchmarkRuns=[];
let pendingReviewRestore=null,frozenUnsaved=false;
const backedUpRuns=new Set();
let reviewSaveTimer;
let reviewInitialized=false,benchmarkUnsaved=false;
const benchmarkSessionRuns=[];
const labelName={eligible:'初筛通过',ineligible:'暂不满足',insufficient:'信息不足 / 核验'};
const purposeName={development:'开发检查',test:'测试用途（复核者声明）'};
document.addEventListener('click',event=>{const button=event.target.closest('[data-review-stage]');if(button&&['review-case-content','benchmark-freeze-panel','benchmark-evaluation-panel'].includes(button.dataset.reviewStage))document.getElementById(button.dataset.reviewStage)?.scrollIntoView({behavior:'smooth',block:'start'});});
function filteredReviewIndexes(){
  const filter=$('#review-status-filter').value,family=$('#review-family-filter').value,batch=$('#review-batch-filter').value;
  return state.reviewCases.map((row,index)=>({row,index})).filter(({row})=>(batch==='all'||(batch==='practice'&&row.case_id.startsWith('review-draft-'))||(batch==='custom'&&!row.campaign&&!row.case_id.startsWith('review-draft-'))||row.campaign?.slot===batch)&&(filter==='all'||row.review.status===filter)&&(family==='all'||state.policies.find(p=>p.id===row.policy_id)?.family===family)).map(x=>x.index);
}
function visibleConfirmed(){return filteredReviewIndexes().map(i=>state.reviewCases[i]).filter(row=>row.review.status==='reviewed');}
function updateReviewProgress(){
  const reviewed=state.reviewCases.filter(r=>r.review.status==='reviewed'),counts={eligible:0,ineligible:0,insufficient:0};
  reviewed.forEach(row=>counts[row.expected.conclusion]++);
  $('#review-progress').textContent=`${reviewed.length} / ${state.reviewCases.length} 已确认`;
  $('#review-export').disabled=!reviewed.length;
  $('#review-summary').innerHTML=`<strong>${state.reviewCases.length-reviewed.length} 条待复核 · ${reviewed.length} 条已确认</strong><span>已确认结论：通过 ${counts.eligible} · 不满足 ${counts.ineligible} · 信息不足 ${counts.insufficient}</span><small>结论分布只描述人工记录，不是模型准确率。未确认草稿不会导出为标注。</small>`;
  $('#benchmark-selection').textContent=`当前筛选范围有 ${visibleConfirmed().length} 条已确认记录；待复核记录不会进入冻结集。`;
}
function renderReviewList(){
  const indexes=filteredReviewIndexes();
  $('#review-case-list').innerHTML=indexes.map(index=>{const row=state.reviewCases[index],practice=row.case_id.startsWith('review-draft-');return `<button class="review-case-button ${index===state.reviewIndex?'active':''}" data-review-index="${index}">${row.review.status==='reviewed'?'✓ ':''}${esc(row.title||row.case_id)}<small>${esc(row.case_id)} · ${practice?'内置练习':'新建案例'} · ${row.review.status==='reviewed'?'已确认':'待复核'}</small></button>`;}).join('')||'<p class="field-note">当前筛选没有案例。</p>';
  updateReviewProgress();
}
function reviewAnnotation(){return {conclusion:$('#review-conclusion').value,evidence_ids:$$('[data-review-evidence]:checked').map(e=>e.value),missing_fields:$$('[data-review-missing]:checked').map(e=>e.value),materials:$$('[data-review-material]:checked').map(e=>e.value),explanation:$('#review-explanation').value,reviewer:$('#reviewer-name').value};}
function saveReviewSession(){
  if(!reviewInitialized)return;
  const value={schema_version:1,cases:state.reviewCases,index:state.reviewIndex,unsaved:state.reviewUnsaved};
  try{
    if(reviewCacheBlocked){$('#review-storage-status').textContent='旧暂存未覆盖；请先下载恢复备份与当前草稿。';return;}
    sessionStorage.setItem(REVIEW_SESSION_KEY,JSON.stringify(value));state.reviewStored=true;
    $('#review-storage-status').textContent='已暂存本标签页 · '+new Date().toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间） · 长期保留请下载备份';
  }catch{state.reviewStored=false;$('#review-storage-status').textContent='标签页暂存不可用，请下载草稿备份后再关闭。';}
}
function stashReview(markPending=false){
  const row=state.reviewCases[state.reviewIndex];if(!row||!$('#review-form'))return;
  const wasReviewed=row.review.status==='reviewed';
  row.draft_annotation=reviewAnnotation();
  if(markPending){row.review={status:'pending',reviewer:null,reviewed_at:null};row.expected=null;state.reviewUnsaved=true;}
  clearTimeout(reviewSaveTimer);
  if(markPending)reviewSaveTimer=setTimeout(saveReviewSession,250);else saveReviewSession();
  if(markPending&&wasReviewed){
    if($('#review-status-filter').value==='reviewed'){$('#review-status-filter').value='pending';toast('本条已修改，已转为待复核；请重新确认后保存。');}
    renderReviewList();
  }
}
function renderReviewCase(){
  const indexes=filteredReviewIndexes();
  if(!indexes.includes(state.reviewIndex))state.reviewIndex=indexes[0]??-1;
  renderReviewList();const row=state.reviewCases[state.reviewIndex];
  if(!row){$('#review-case-content').innerHTML='<div class="simple-empty"><h2>当前筛选没有案例</h2><p>请切换复核状态或政策来源，或新增评测案例。这里没有可编辑的记录。</p></div>';return;}
  const policy=state.policies.find(p=>p.id===row.policy_id);
  if(!policy){$('#review-case-content').innerHTML='<p class="form-error">未找到对应政策，请保留备份并核对政策版本。</p>';return;}
  const annotation=row.draft_annotation||row.expected||{},checked=(field,value)=>(annotation[field]||[]).includes(value)?'checked':'';
  const practice=row.case_id.startsWith('review-draft-')||row.provenance?.kind==='built_in_practice';
  $('#review-case-content').innerHTML=`<div class="review-case-heading"><span class="method-tag">${esc(row.case_id)} · ${practice?'内置开发练习':'待人工核对的新案例'}</span><h2>${esc(row.title||policy.title)}</h2><a href="${esc(safeURL(policy.source_url))}" target="_blank" rel="noopener noreferrer">阅读官方原文 ↗</a><p>来源 ${esc(policy.published_on)} · ${esc(policy.legal_status||'现行效力待核验')}</p><p class="field-note">${practice?'本条不能冻结为独立测试。':'来源与未参与开发的情况为填写者声明，程序只做重复与格式检查。'}</p></div><div class="review-profile">${Object.entries(row.profile).map(([key,value])=>`<div><span>${esc(state.reviewLabels[key]||(key==='city'?'城市':key))}</span><strong>${esc(readableValue(value))}</strong></div>`).join('')}</div><form id="review-form" class="review-form"><label>你的初筛结论<select id="review-conclusion" required><option value="">阅读原文后选择</option><option value="eligible">所列条件初筛通过</option><option value="ineligible">存在明确不满足条件</option><option value="insufficient">信息不足或超出覆盖</option></select></label><fieldset><legend>支持这一结论的条款</legend>${policy.clauses.map(c=>`<label class="review-option"><input type="checkbox" data-review-evidence value="${esc(c.id)}" ${checked('evidence_ids',c.id)}><span>${esc(c.section)}<br><small>${esc(c.text)}</small></span></label>`).join('')}</fieldset><fieldset><legend>还缺哪些申请人信息</legend>${Object.keys(state.reviewLabels).filter(k=>k!=='city').map(key=>`<label class="review-option"><input type="checkbox" data-review-missing value="${esc(key)}" ${checked('missing_fields',key)}><span>${esc(state.reviewLabels[key])}</span></label>`).join('')}</fieldset><fieldset><legend>应提示的准备信息</legend>${policy.materials.map(m=>`<label class="review-option"><input type="checkbox" data-review-material value="${esc(m.id)}" ${checked('materials',m.id)}><span>${esc(m.label)} · ${esc(m.kind)}</span></label>`).join('')}</fieldset><label>判断依据与不确定处<textarea id="review-explanation" required maxlength="3000">${esc(annotation.explanation||'')}</textarea></label><label>复核者标识<input id="reviewer-name" required maxlength="80" value="${esc(annotation.reviewer||row.review.reviewer||'')}" placeholder="用于追溯的标识"></label><label class="review-option"><input id="review-source-checked" type="checkbox" required ${row.review.status==='reviewed'?'checked':''}><span>我已阅读对应原文并核对本条依据；程序未替我确认标注正确。</span></label><div id="review-form-error" class="form-error" role="alert" hidden></div><div class="review-actions"><button type="button" class="btn btn-quiet small" id="review-prev">← 上一条</button><button type="submit" class="btn btn-primary" id="review-save">确认并保存本条</button><button type="button" class="btn btn-quiet small" id="review-next">下一条 →</button></div></form>`;
  $('#review-conclusion').value=annotation.conclusion||'';
  const sourceBox=document.createElement('div');sourceBox.dataset.policySource=policy.id;sourceBox.className='primary-source-context';$('#review-form').before(sourceBox);window.renderPrimarySources?.();
  if(row.campaign){const note=document.createElement('p');note.className='field-note';note.textContent='保留批次 '+row.campaign.slot+'：评测目标是所列条件的初筛，不是完整审批资格。原文的额外条件或快照缺口请在“不确定处”注明；超出覆盖转人工核验。请先核对下方原始依据，不参考规则或模型答案。';sourceBox.before(note);}
  const position=indexes.indexOf(state.reviewIndex);
  $('#review-prev').disabled=position<=0;$('#review-next').disabled=position>=indexes.length-1;
}
function mergeReviewRows(rows){for(const row of rows){const index=state.reviewCases.findIndex(r=>r.case_id===row.case_id);if(index<0)state.reviewCases.push(row);else state.reviewCases[index]=row;}}
function updateFamilyFilter(){
  const current=$('#review-family-filter').value;
  $('#review-family-filter').innerHTML='<option value="all">全部来源</option>'+[...new Set(state.policies.map(p=>p.family))].map(f=>{const p=state.policies.find(p=>p.family===f&&p.status==='included')||state.policies.find(p=>p.family===f);return `<option value="${esc(f)}">${esc(p.category||p.title)} · ${esc(p.published_on)}</option>`;}).join('');
  if([...$('#review-family-filter').options].some(o=>o.value===current))$('#review-family-filter').value=current;
}
function moveReview(delta){stashReview();const indexes=filteredReviewIndexes(),position=indexes.indexOf(state.reviewIndex);if(indexes.length)state.reviewIndex=indexes[Math.max(0,Math.min(indexes.length-1,position+delta))];renderReviewCase();saveReviewSession();}
$('#review-case-list').addEventListener('click',event=>{const button=event.target.closest('[data-review-index]');if(button){stashReview();state.reviewIndex=Number(button.dataset.reviewIndex);renderReviewCase();saveReviewSession();}});
$('#review-case-content').addEventListener('input',event=>{if(event.target.id!=='review-source-checked')$('#review-source-checked').checked=false;stashReview(true);});
$('#review-case-content').addEventListener('change',event=>{if(event.target.id!=='review-source-checked')$('#review-source-checked').checked=false;stashReview(true);});
$('#review-case-content').addEventListener('click',event=>{if(event.target.closest('#review-prev'))moveReview(-1);if(event.target.closest('#review-next'))moveReview(1);});
$('#review-case-content').addEventListener('submit',async event=>{
  if(event.target.id!=='review-form')return;event.preventDefault();const index=state.reviewIndex,row=state.reviewCases[index],annotation=reviewAnnotation();
  const reviewed={...row,draft_annotation:annotation,expected:{policy_id:row.policy_id,...Object.fromEntries(Object.entries(annotation).filter(([key])=>key!=='reviewer'))},review:{status:'reviewed',reviewer:annotation.reviewer.trim(),reviewed_at:new Date().toISOString(),source_checked:true}};
  $('#review-save').disabled=true;$('#review-form-error').hidden=true;
  try{await api('/api/review/validate',{cases:[reviewed]});state.reviewCases[index]=reviewed;state.reviewUnsaved=true;saveReviewSession();renderReviewCase();toast('已确认 '+row.case_id+'；请下载备份或冻结评测集。');}
  catch(error){if($('#review-form-error')){$('#review-form-error').textContent=error.message.replaceAll('模型输出','标注');$('#review-form-error').hidden=false;}}
  finally{if($('#review-save'))$('#review-save').disabled=false;}
});
for(const id of ['review-status-filter','review-family-filter','review-batch-filter'])$('#'+id).addEventListener('change',()=>{stashReview();const indexes=filteredReviewIndexes();if(!indexes.includes(state.reviewIndex)&&indexes.length)state.reviewIndex=indexes[0];renderReviewCase();});
$('#review-next-pending').addEventListener('click',()=>{stashReview();const rows=state.reviewCases;$('#review-status-filter').value='pending';const indexes=filteredReviewIndexes();let next=indexes.find(i=>i>state.reviewIndex)??indexes[0]??-1;if(next<0){renderReviewCase();toast('当前筛选范围没有待复核案例。');return;}state.reviewIndex=next;renderReviewCase();saveReviewSession();});
$('#review-download-draft').addEventListener('click',()=>{stashReview();download('惠才通-复核草稿备份.json',{schema_version:1,cases:state.reviewCases,notice:'包含未确认草稿，不能整体作为人工标注基准。'});state.reviewUnsaved=false;saveReviewSession();});
$('#review-export').addEventListener('click',async()=>{stashReview();const cases=state.reviewCases.filter(r=>r.review.status==='reviewed');try{await api('/api/review/validate',{cases});download('惠才通-已确认人工标注.json',{schema_version:1,annotation_source:'reviewer_declared',cases});}catch(error){toast(error.message,true);}});
$('#review-import').addEventListener('click',()=>$('#review-file').click());$('#review-restore').addEventListener('click',()=>$('#review-restore-file').click());
async function restoreReviewFile(file,confirmedOnly){
  pendingReviewRestore=null;$('#review-restore-conflicts').hidden=true;
  if(file.size>1_000_000)throw new Error('复核文件不超过 1MB');const payload=parseJSONInput(await file.text(),'复核文件');
  if(confirmedOnly)await api('/api/review/validate',{cases:payload.cases});
  const result=await api('/api/review/restore',{schema_version:payload.schema_version,cases:payload.cases});
  pendingReviewRestore={cases:result.cases,notice:result.notice};await applyReviewRestore(false);
}
async function renderRestoreBackups(){
  const panel=$('#review-restore-backups'),list=$('#review-restore-backup-list');
  try{
    const history=JSON.parse(sessionStorage.getItem(REVIEW_IMPORT_BACKUP_KEY)||'[]');
    if(!Array.isArray(history))throw new Error('备份格式异常');
    list.replaceChildren();panel.hidden=!history.length;
    history.forEach((snapshot,index)=>{const row=document.createElement('div');row.className='backup-row';const label=document.createElement('span');label.textContent=new Date(snapshot.saved_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间） · '+snapshot.cases.length+' 条';const button=document.createElement('button');button.className='btn btn-quiet small';button.textContent='下载恢复前备份 '+(index+1);button.addEventListener('click',()=>download('惠才通-恢复前草稿备份-'+(index+1)+'.json',snapshot));row.append(label,button);list.append(row);});
  }catch{panel.hidden=false;list.textContent='备份暂不可读取，当前记录不会因此被替换。请先备份全部复核进度。';}
}
async function applyReviewRestore(allowConflicts){
  if(!pendingReviewRestore)return;
  stashReview();
  const module=await import('/review-recovery.mjs?v=a6f3b90eedd78575');
  const plan=module.planReviewRestore(state.reviewCases,pendingReviewRestore.cases);
  if(plan.conflicts.length&&!allowConflicts){
    $('#review-restore-conflict-summary').textContent=`文件含 ${plan.total} 条案例，其中 ${plan.conflicts.length} 条会替换当前已有填写：${plan.conflicts.join('、')}。`;
    $('#review-restore-conflicts').hidden=false;$('#review-restore-conflicts').scrollIntoView({behavior:'smooth',block:'start'});return;
  }
  if(plan.conflicts.length){
    try{module.preserveReviewSnapshot(sessionStorage,REVIEW_IMPORT_BACKUP_KEY,{schema_version:1,cases:state.reviewCases,index:state.reviewIndex,saved_at:new Date().toISOString(),notice:'恢复文件前的完整草稿；未确认记录不属于人工标注。'});}
    catch{throw new Error('未能保存恢复前备份，已停止替换。当前内容保留，请先下载全部复核进度并检查浏览器存储空间。');}
  }
  const incoming=pendingReviewRestore;pendingReviewRestore=null;
  mergeReviewRows(incoming.cases);state.reviewUnsaved=state.reviewUnsaved||plan.conflicts.length>0;
  const slots=[...new Set(incoming.cases.map(r=>r.campaign?.slot))];if(slots.length===1&&['A','B'].includes(slots[0])){$('#review-batch-filter').value=slots[0];$('#campaign-submit-slot').value=slots[0];$('#review-status-filter').value='all';$('#review-family-filter').value='all';state.reviewIndex=state.reviewCases.findIndex(r=>r.case_id===incoming.cases[0].case_id);}
  $('#review-restore-conflicts').hidden=true;renderReviewCase();saveReviewSession();renderRestoreBackups();toast(incoming.notice);
}
$('#review-restore-cancel').addEventListener('click',()=>{pendingReviewRestore=null;$('#review-restore-conflicts').hidden=true;toast('已取消恢复，当前填写保持不变。');});
$('#review-restore-replace').addEventListener('click',async()=>{const button=$('#review-restore-replace');button.disabled=true;try{await applyReviewRestore(true);}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
for(const [id,only] of [['review-file',true],['review-restore-file',false]])$('#'+id).addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{await restoreReviewFile(file,only);}catch(error){toast(error.message,true);}event.target.value='';});
$('#review-add-case').addEventListener('click',()=>{
  $('#new-case-policy').innerHTML=state.policies.filter(p=>p.status==='included').map(p=>`<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
  const template=Object.fromEntries(Object.keys(state.reviewLabels).map(key=>[key,null]));template.city='杭州';template.application_date=todayInput();
  $('#new-case-profile').value=JSON.stringify(template,null,2);$('#new-case-error').hidden=true;$('#review-new-dialog').showModal();
});
$('#review-new-form').addEventListener('submit',async event=>{
  event.preventDefault();$('#new-case-error').hidden=true;
  try{
    const body={case_id:$('#new-case-id').value.trim(),title:$('#new-case-title').value.trim(),policy_id:$('#new-case-policy').value,profile:parseJSONInput($('#new-case-profile').value,'申请字段'),provenance:{kind:$('#new-case-origin').value,training_use:$('#new-case-training').value}};
    if(state.reviewCases.some(r=>r.case_id===body.case_id))throw new Error('案例编号已存在，请使用新编号。');
    const result=await api('/api/review/new-case',body);stashReview();state.reviewCases.push(result.case);state.reviewIndex=state.reviewCases.length-1;state.reviewUnsaved=true;
    $('#review-status-filter').value='all';$('#review-family-filter').value='all';$('#review-batch-filter').value='custom';renderReviewCase();saveReviewSession();$('#review-new-dialog').close();toast('已建立空白标签草稿，请阅读原文后逐项复核。');
  }catch(error){$('#new-case-error').textContent=error.message;$('#new-case-error').hidden=false;}
});
function showDataset(dataset,created=false){
  frozenUnsaved=created;
  frozenDataset=dataset;benchmarkRuns=benchmarkSessionRuns.filter(run=>run.dataset_sha256===dataset.sha256);renderBenchmarkRuns();$('#benchmark-export-results').disabled=!benchmarkRuns.length;
  $('#benchmark-binding').checked=false;$('#benchmark-predictions').value='';$('#benchmark-prediction-text').value='';
  $('#benchmark-download').disabled=false;$('#benchmark-template').disabled=false;
  $('#benchmark-current').textContent=`当前冻结集「${dataset.name}」 · ${purposeName[dataset.purpose]||dataset.purpose} · ${dataset.cases.length} 条 · SHA-256：${dataset.sha256}`;
  $('#benchmark-current').textContent+=' · '+(dataset.review_protocol?.version===2?'双人独立初审＋第三人终审':'单次标注声明；未记录双人复核');
  $('#benchmark-message').textContent='文件检查已通过。切换评测集时不会混合指标，其他对照记录仍可从本标签页全部备份下载。';
  $('#benchmark-evaluation-message').textContent='已准备好冻结集。当前仅保留在本标签页，请下载冻结集后再刷新或关闭；工作台后续编辑不会改变它。';
}
$('#benchmark-purpose').addEventListener('change',()=>{$('#benchmark-independence-label').hidden=$('#benchmark-purpose').value!=='test';$('#benchmark-independence').checked=false;});
$('#benchmark-freeze-form').addEventListener('submit',async event=>{
  event.preventDefault();stashReview();$('#benchmark-message').textContent='正在检查人工记录、来源版本和重复情况…';
  if(frozenUnsaved){$('#benchmark-message').textContent='请先下载当前冻结评测集，再创建另一份。当前冻结集已保留。';return;}
  try{const result=await api('/api/benchmark/freeze',{cases:visibleConfirmed(),name:$('#benchmark-name').value,dataset_id:$('#benchmark-id').value,purpose:$('#benchmark-purpose').value,independence_confirmed:$('#benchmark-independence').checked});showDataset(result.dataset,true);}
  catch(error){$('#benchmark-message').textContent='未冻结：'+error.message;}
});
$('#benchmark-download').addEventListener('click',()=>{if(frozenDataset){download(frozenDataset.dataset_id+'-frozen.json',frozenDataset);frozenUnsaved=false;}});
$('#benchmark-template').addEventListener('click',()=>{
  if(!frozenDataset)return;
  const policies=new Map(frozenDataset.policies.map(p=>[p.id,p]));
  download(frozenDataset.dataset_id+'-prediction-template.json',{schema_version:1,dataset_sha256:frozenDataset.sha256,notice:'completion 为空，必须用实际模型输出替换；输入中不提供人工结论。',requests:frozenDataset.cases.map(row=>({case_id:row.case_id,policy_id:row.policy_id,profile:row.profile,clauses:policies.get(row.policy_id).clauses,allowed_materials:policies.get(row.policy_id).materials})),predictions:frozenDataset.cases.map(row=>({case_id:row.case_id,completion:''}))});
});
$('#benchmark-load').addEventListener('click',()=>$('#benchmark-dataset-file').click());
$('#benchmark-dataset-file').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(frozenUnsaved)throw new Error('请先下载当前冻结评测集，再载入另一份。当前冻结集已保留。');if(file.size>2_000_000)throw new Error('冻结集不超过 2MB');const dataset=parseJSONInput(await file.text(),'冻结评测集');await api('/api/benchmark/verify',{dataset});showDataset(dataset);}catch(error){$('#benchmark-message').textContent='载入失败：'+error.message;}event.target.value='';});
function renderBenchmarkRuns(){
  const pct=value=>typeof value==='number'?(value*100).toFixed(1)+'%':'—';
  $('#benchmark-results').innerHTML='<div class="benchmark-table-wrap"><table><thead><tr><th>实际预测名称</th><th>结论一致率</th><th>有效输出</th><th>引用编号 F1</th><th>缺失预测</th></tr></thead><tbody>'+benchmarkRuns.map(run=>{const m=run.metrics;return `<tr><td>${esc(m.model_name)}</td><td>${pct(m.conclusion_accuracy)}</td><td>${pct(m.valid_output_rate)}</td><td>${pct(m.mean_evidence_f1)}</td><td>${m.missing_predictions} / ${m.cases}</td></tr>`;}).join('')+'</tbody></table></div>'+benchmarkRuns.map(run=>`<details><summary>${esc(run.metrics.model_name)} · 逐条错误与分类指标</summary><p>${esc(run.metrics.warning)}</p><p>预测绑定：${run.metrics.prediction_binding==='artifact_sha256'?'文件指纹匹配':'由使用者声明对应当前集'}</p><div class="benchmark-table-wrap"><table><thead><tr><th>类别</th><th>样本数</th><th>精确率</th><th>召回率</th></tr></thead><tbody>${Object.entries(run.metrics.per_class).map(([key,value])=>`<tr><td>${labelName[key]}</td><td>${value.support}</td><td>${pct(value.precision)}</td><td>${pct(value.recall)}</td></tr>`).join('')}</tbody></table></div><ul>${run.details.filter(d=>d.errors.length).map(d=>`<li>${esc(d.case_id)}：参考 ${labelName[d.expected]} / 预测 ${labelName[d.predicted]||'无有效输出'}；${d.missing_prediction?'缺失预测':esc(d.errors.join('、'))}</li>`).join('')||'<li>在已计算的结构化字段上未发现差异；这不评价解释文字或标注质量。</li>'}</ul></details>`).join('');
  benchmarkRuns.forEach((run,index)=>{const panel=document.createElement('details');panel.innerHTML=`<summary>${esc(run.metrics.model_name)} · 错误归因与规则对照线索</summary>`+(window.renderDiagnosticBoard?.('benchmark-'+run.dataset_sha256+'-'+index,run.diagnostics)||'<p class="field-note">错误分析组件尚未准备。</p>');$('#benchmark-results').append(panel);});
}
$('#benchmark-evaluate-form').addEventListener('submit',async event=>{
  event.preventDefault();const message=$('#benchmark-evaluation-message');message.textContent='正在检查预测文件…';
  try{
    if(!frozenDataset)throw new Error('请先冻结或载入人工评测集。');const file=$('#benchmark-predictions').files[0],pasted=$('#benchmark-prediction-text').value.trim();
    if(file&&pasted)throw new Error('请选择文件或粘贴内容中的一种，避免混用。');
    if(!file&&!pasted)throw new Error('请选择预测文件，或粘贴预测内容。');if(file&&file.size>1_000_000)throw new Error('预测文件不超过 1MB');
    const content=pasted||await file.text();if(new TextEncoder().encode(content).length>1_000_000)throw new Error('预测内容不超过 1MB');let parsed,predictions,binding;
    try{parsed=JSON.parse(content);predictions=Array.isArray(parsed)?parsed:parsed.predictions;binding=parsed.dataset_sha256;}
    catch{try{predictions=content.split(/\r?\n/).filter(line=>line.trim()).map(line=>JSON.parse(line));}catch{throw new Error('预测内容不是有效的 JSON 或逐行 JSON。');}}
    const result=await api('/api/benchmark/evaluate',{dataset:frozenDataset,predictions,model_name:$('#benchmark-model').value,prediction_dataset_sha256:binding,binding_confirmed:$('#benchmark-binding').checked});
    const run={...result,source_filename:file?.name||'粘贴预测内容',evaluated_at:new Date().toISOString()};benchmarkRuns.push(run);benchmarkSessionRuns.push(run);benchmarkUnsaved=true;renderBenchmarkRuns();$('#benchmark-export-results').disabled=false;$('#benchmark-export-all').disabled=false;
    message.textContent=`已计算 ${result.metrics.cases} 条。所有对照使用当前冻结集；缺失预测已计入分母。`;
  }catch(error){message.textContent='未计算：'+error.message;}
});
$('#benchmark-export-results').addEventListener('click',()=>{if(frozenDataset){download(frozenDataset.dataset_id+'-comparison.json',{schema_version:1,dataset_sha256:frozenDataset.sha256,dataset_name:frozenDataset.name,notice:'只比较提供的实际预测；不验证模型来源，不自动评价解释语义。',runs:benchmarkRuns});benchmarkRuns.forEach(run=>backedUpRuns.add(run));benchmarkUnsaved=benchmarkSessionRuns.some(run=>!backedUpRuns.has(run));}});
$('#benchmark-export-all').addEventListener('click',()=>{download('惠才通-本标签页全部评测对照.json',{schema_version:1,notice:'按各条 dataset_sha256 区分评测集，不能跨集比较数字。',runs:benchmarkSessionRuns});benchmarkSessionRuns.forEach(run=>backedUpRuns.add(run));benchmarkUnsaved=false;});
for(const id of ['benchmark-predictions','benchmark-prediction-text'])$('#'+id).addEventListener('input',()=>{$('#benchmark-binding').checked=false;});
window.addEventListener('beforeunload',event=>{clearTimeout(reviewSaveTimer);saveReviewSession();if(state.reviewUnsaved||benchmarkUnsaved||frozenUnsaved){event.preventDefault();event.returnValue='';}});
window.addEventListener('hct:policies-updated',()=>{updateFamilyFilter();renderReviewList();});
Promise.all([api('/api/review/draft'),api('/api/policies')]).then(async([draft,catalogue])=>{
  state.reviewCases=draft.cases;state.reviewLabels=draft.field_labels;state.policies=catalogue.policies;updateFamilyFilter();
  let pendingRaw=null;
  try{
    if(sessionStorage.getItem(REVIEW_BACKUP_KEY))$('#review-recovery-saved').hidden=false;
    const raw=sessionStorage.getItem(REVIEW_SESSION_KEY);
    if(raw){pendingRaw=raw;const saved=JSON.parse(raw),restored=await api('/api/review/restore',saved);mergeReviewRows(restored.cases);state.reviewIndex=Math.max(0,Math.min(state.reviewCases.length-1,Number(saved.index)||0));state.reviewUnsaved=saved.unsaved===true;state.reviewStored=true;$('#review-storage-status').textContent='已恢复本标签页复核进度';}
  }catch(error){
    reviewCacheBlocked=true;reviewRawBackup=pendingRaw;
    try{if(reviewRawBackup){const existing=sessionStorage.getItem(REVIEW_BACKUP_KEY);if(existing===null||existing===reviewRawBackup){sessionStorage.setItem(REVIEW_BACKUP_KEY,reviewRawBackup);reviewCacheBlocked=false;}$('#review-recovery-saved').hidden=false;}}catch{}
    $('#review-storage-status').textContent='旧暂存恢复失败：'+error.message+'。原记录已保留，请下载恢复备份。';
    $('#review-recovery-download').hidden=false;
  }
  reviewInitialized=true;renderReviewCase();renderRestoreBackups();
}).catch(error=>{$('#review-case-content').innerHTML=`<p class="form-error">草稿未加载：${esc(error.message)}。可刷新或使用草稿备份恢复。</p>`;});
$('#review-recovery-download').addEventListener('click',()=>{
  const raw=reviewRawBackup;if(!raw){toast('没有可下载的恢复记录。');return;}
  const url=URL.createObjectURL(new Blob([raw],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='惠才通-原始复核恢复记录.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('#review-recovery-saved').addEventListener('click',()=>{try{const raw=sessionStorage.getItem(REVIEW_BACKUP_KEY);if(!raw)throw new Error('没有既有备份');const url=URL.createObjectURL(new Blob([raw],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='惠才通-既有复核恢复备份.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){toast(error.message,true);}});
