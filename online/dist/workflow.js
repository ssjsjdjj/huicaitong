'use strict';
state.materialConfirmations=[];
state.materialResult=null;
state.materialRequestVersion=0;
state.materialBody=null;state.materialContextDirty=false;
state.reviewUnsaved=false;state.reviewStored=false;
state.reviewCases=[];
state.reviewIndex=0;
state.reviewLabels={};

function clearMaterialState(){
  state.materialConfirmations=[];state.materialResult=null;state.materialBody=null;state.materialContextDirty=false;state.materialRequestVersion++;
  if($('#material-context'))updateMaterialContext();
  $('#material-result').innerHTML='<div class="simple-empty">材料信息已清空。请选择文件或合成样例重新核对。</div>';
  $$('[data-material-demo]').forEach(b=>b.disabled=false);$('#material-upload').disabled=false;$('#choose-material').disabled=false;
}

function renderRetrievalTrace(trace){
  const items=[...trace.hits.map(h=>({id:h.id,label:'问题检索命中'})),...trace.expanded_ids.map(id=>({id,label:'补齐必要依据'}))];
  const policy=state.policies.find(p=>p.id===trace.policy_id);
  return `<details class="retrieval-trace"><summary>本次证据：检索 ${trace.hits.length} 条，补齐 ${trace.expanded_ids.length} 条</summary><p>问题：${esc(trace.query)}</p><p>参考日期 ${esc(trace.as_of)} · 来源发布 ${esc(trace.published_on)}</p>${items.map(item=>`<div class="trace-item"><span>${esc(policy?.clauses.find(c=>c.id===item.id)?.section||item.id)}<small> · ${item.label}</small></span>${evidenceButton(item.id)}</div>`).join('')}<p class="field-note">${esc(trace.notice)}</p></details>`;
}

function updateMaterialContext(){
  const p=readProfile();state.materialContextDirty=false;
  $('#material-context').innerHTML=`<form id="material-context-form"><strong>本次计算使用的日期</strong><label>毕业日期<input type="date" id="material-graduation" value="${esc(p.graduation_date||'')}"></label><label>参考日期<input type="date" id="material-reference" required value="${esc(p.application_date||'')}"></label><button class="btn full" id="update-material-context" type="submit">保存日期${state.materialBody?'并重新计算':''}</button><small>日期会同步到申请表；原文件只保留在当前页面内存。</small></form>`;
}

function renderLedger(d){
  if(!d?.ledger?.length)return '';
  return `<details class="ledger-details" ${d.continuous_months!==undefined?'open':''}><summary>逐月计算明细${d.continuous_months!==undefined?' · 连续 '+d.continuous_months+' 个月':''}</summary><p>计算至 ${esc(d.calculated_through)}。只有最后一段连续有效记录计入本次月数；缺行不能视为未参保。</p><div class="ledger-grid">${d.ledger.map(m=>`<div class="ledger-month ${m.counted?'counted':m.state==='excluded'?'excluded':''}"><strong>${esc(m.month)}</strong><span>${esc(m.status)}</span><small>${m.counted?'计入连续时长':m.state==='excluded'?'中断连续计数':'未计入本次连续段'}</small><span>第 ${m.evidence.page} 页 / 第 ${m.evidence.line} 行</span></div>`).join('')}</div>${d.ledger_truncated?'<p>仅展示最近 120 条月份记录，完整原文请在下方查看。</p>':''}</details>`;
}

async function readBase64(file){
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
}

function renderMaterial(result){
  state.materialResult=result;
  const blocked=result.diagnostics?.status==='needs_context';
  $('#material-result').innerHTML=`<h3 class="material-file-title">${esc(result.filename)}</h3><p class="field-note">${esc(({local_pdf_text:'文字 PDF 提取',local_text:'文本读取',windows_local_ocr:'Windows 本机图片识别'})[result.method]||result.method)} · ${result.pages} 页${blocked?'':` · ${result.candidates.length} 个待确认字段`}</p>${blocked?'<div class="context-needed" role="status"><strong>文件文字已读取，缺毕业日期，暂不能计算参保月数</strong><p>请在左侧补齐毕业日期，再点“保存日期并重新计算”。无需再次选择文件。</p></div>':''}${result.candidates.map((c,i)=>`<label class="material-candidate"><input type="checkbox" data-confirm-material="${i}"><span><strong>${esc(c.label)}</strong><span class="candidate-value">${esc(c.value_label)}</span>${c.conflict?`<p class="candidate-conflict">表单原值：${esc(readableValue(c.current_value))} → 材料候选：${esc(c.value_label)}。勾选确认后才替换。</p>`:''}<blockquote class="source-quote">第 ${c.evidence.page} 页，第 ${c.evidence.line} 行：${esc(c.evidence.quote)}</blockquote></span></label>`).join('')||(!blocked?'<div class="simple-empty">没有找到可明确填写的字段。请核对原文，或在表单中手工补充。</div>':'')}${renderLedger(result.diagnostics)}${result.issues.length?`<ul class="material-issues">${result.issues.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}<p class="field-note">${esc(result.notice)}</p><button id="apply-material" class="btn btn-primary full" disabled>确认所勾选字段，填入表单</button><div class="material-done" id="material-done" hidden></div><details class="material-text-preview"><summary>查看提取文字${result.text_preview_truncated?'（前 6000 字）':''}</summary><pre>${esc(result.text_preview)}</pre></details>`;
  updateMaterialContext();
}

async function extractFile(body){
  state.materialBody=body;
  const requestVersion=++state.materialRequestVersion;
  $('#material-result').innerHTML='<div class="result-loading"><span class="spinner"></span>正在本机读取材料…</div>';
  state.materialResult=null;
  $$('[data-material-demo]').forEach(b=>b.disabled=true);
  $('#material-upload').disabled=true;$('#choose-material').disabled=true;
  try{
    const result=await api('/api/materials/extract',{...body,profile:readProfile()});
    if(requestVersion===state.materialRequestVersion)renderMaterial(result);
  }catch(error){if(requestVersion===state.materialRequestVersion)$('#material-result').innerHTML=`<div class="form-error">${esc(error.message)}</div>`;}
  finally{if(requestVersion===state.materialRequestVersion){$$('[data-material-demo]').forEach(b=>b.disabled=false);$('#material-upload').disabled=false;$('#choose-material').disabled=false;}}
}

function applyMaterial(){
  const result=state.materialResult;
  if(!result)return;
  if(state.materialContextDirty){toast('日期已修改，请先保存日期并重新计算。',true);return;}
  const checkboxes=$$('[data-confirm-material]:checked:not(:disabled)');
  const selected=checkboxes.map(e=>result.candidates[Number(e.dataset.confirmMaterial)]);
  if(!selected.length)return;
  const profile=readProfile();
  for(const c of selected){
    for(const [key,value] of Object.entries(c.context||{})){
      if(profile[key]!==value){toast('参考日期或毕业日期已变化，请重新读取材料后确认。',true);return;}
    }
  }
  const proposed={...profile,...Object.fromEntries(selected.map(c=>[c.field,c.value]))};
  // A graduation date extracted together with a ledger cannot silently change
  // the date on which that ledger's calculation depended.
  for(const c of selected){for(const [key,value] of Object.entries(c.context||{})){if(proposed[key]!==value){toast('先确认毕业日期，再重新读取参保记录。',true);return;}}}
  fillProfile(proposed);
  state.materialConfirmations.push({filename:result.filename,document_sha256:result.document_sha256,method:result.method,confirmed_at:new Date().toISOString(),fields:selected.map(c=>({field:c.field,value:c.value,evidence:c.evidence,context:c.context}))});
  checkboxes.forEach(c=>c.disabled=true);
  $('#apply-material').disabled=true;
  updateMaterialContext();
  $('#material-done').hidden=false;$('#material-done').innerHTML=`已确认 ${selected.length} 个字段。可继续读取下一份材料，或<button class="text-button" data-view="match">回到表单重新初筛 →</button>`;
  toast(`已填写 ${selected.length} 个字段，可继续核对下一份材料。`);
}

$('#choose-material').addEventListener('click',()=>$('#material-upload').click());
$('#material-context').addEventListener('input',()=>{state.materialContextDirty=true;if($('#apply-material'))$('#apply-material').disabled=true;});
$('#material-context').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('#update-material-context');button.disabled=true;
  try{const p=readProfile();const result=await api('/api/profile/validate',{profile:{...p,graduation_date:$('#material-graduation').value||null,application_date:$('#material-reference').value||null}});fillProfile(result.profile);updateMaterialContext();if(state.materialBody)await extractFile(state.materialBody);else toast('日期已保存，可以选择材料。');}
  catch(error){toast(error.message,true);}finally{if($('#update-material-context'))$('#update-material-context').disabled=false;}
});
$('#material-upload').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;
  try{if(file.size>2000000)throw new Error('每份材料不超过 2MB');await extractFile({filename:file.name,content_base64:await readBase64(file)});}
  catch(error){toast(error.message,true);}
  event.target.value='';
});
$('#material-result').addEventListener('change',()=>{const button=$('#apply-material');if(button)button.disabled=state.materialContextDirty||!$$('[data-confirm-material]:checked:not(:disabled)').length;});
$('#material-result').addEventListener('click',event=>{if(event.target.closest('#apply-material'))applyMaterial();});
document.addEventListener('click',async event=>{
  const demo=event.target.closest('[data-material-demo]');
  if(demo){try{const body=await api('/api/materials/example?id='+encodeURIComponent(demo.dataset.materialDemo));await extractFile(body);}catch(error){toast(error.message,true);}}
  if(event.target.closest('[data-view="materials"]'))updateMaterialContext();
});
updateMaterialContext();
api('/api/materials/capabilities').then(cap=>{
  $('#material-formats').textContent=(cap.pdf?'文字 PDF、TXT':'TXT')+(cap.image?'、PNG/JPG':'')+' · 每份不超过 2MB';
  $('#material-capabilities').textContent=`本机能力：文字 PDF ${cap.pdf?'可用':'需配置'}；图片识别 ${cap.image?'可用（'+cap.ocr_language+'）':'当前不可用'}。`;
  if(!cap.image)$('#material-upload').accept=cap.pdf?'.pdf,.txt':'.txt';
}).catch(()=>{$('#material-capabilities').textContent='暂未读取到材料处理能力，请重试。';});

function readableValue(value){
  if(value===null||value===undefined)return '待确认';
  if(typeof value==='boolean')return value?'是':'否';
  return ({college:'大专',bachelor:'本科',master:'硕士',phd:'博士',fulltime:'全日制',parttime:'非全日制',mainland:'国内普通高校',overseas:'国（境）外高校',cn:'中国国籍',other:'其他'})[value]||String(value);
}

