'use strict';
const supplementaryKeys=['graduation_record_precision','has_dispatch_history','family_scope_confirmed','housing_scope_confirmed','family_property_history','prior_rent_degree_subsidy'];
let applicationExtra=Object.fromEntries(supplementaryKeys.map(k=>[k,null])),applicationDeferred=[],applicationHistory=[],applicationQuestion=null,applicationMeta=null;
let applicationPreparation={context_sha256:'',items:{}},applicationGuideActive=false,applicationFullMode=false,applicationDirty=false,applicationGeneration=0,applicationRestorePending=null,applicationRaw=null;
let applicationStorageGeneration=0;
const applicationStorage=import('/application-storage.mjs?v=f9b47f48e2ae9c9c');
const localDraftStore={getItem:k=>localStorage.getItem(k),setItem:(k,v)=>localStorage.setItem(k,v),removeItem:k=>localStorage.removeItem(k)};
const tabDraftStore={getItem:k=>sessionStorage.getItem(k),setItem:(k,v)=>sessionStorage.setItem(k,v)};
function applicationSnapshot(){return {profile:readProfile(),supplementary:{...applicationExtra},intent:$('#application-intent').value,deferred:[...applicationDeferred],preparation:structuredClone(applicationPreparation)};}
window.applicationRequest=profile=>({...applicationSnapshot(),profile});
window.applicationSignature=(profile,submitted)=>signature({profile,supplementary:submitted?.supplementary||applicationExtra,intent:submitted?.intent||$('#application-intent').value});
function applicationChanged(){window.invalidateApplicationAssessment?.();applicationDirty=true;markProfileChanged();renderApplicationPreparation();}
function setApplicationField(field,value){const el=$('#profile-form').elements.namedItem(field);if(!el)return;el.value=value===null?'':field==='insurance_start_date'?value.slice(0,7):String(value);if(field==='application_date')$('#application-date').value=el.value;}
function renderSupplementary(){
  if(!applicationMeta)return;
  $('#application-extra-fields').innerHTML=Object.entries(applicationMeta.supplementary_fields).map(([k,d])=>`<label>${esc(d.label)}<select data-application-extra="${k}"><option value="">待确认</option>${(d.type==='bool'?[[true,'是'],[false,'否']]:d.options).map(([v,label])=>`<option value="${v}" ${applicationExtra[k]===v?'selected':''}>${esc(label)}</option>`).join('')}</select><small>${esc(d.help)}</small></label>`).join('');
}
window.renderQualificationReview=function(result){
  const q=result.qualification_review;if(!q)return '';
  const labels={pending:'待补充',manual:'需人工核验',confirmed:'已自填核对'};
  return `<details class="policy-details qualification-review" ${q.status==='manual'?'open':''}><summary>补充资格核验 · ${q.checks.filter(c=>c.state==='pending').length} 项待补充 · ${q.checks.filter(c=>c.state==='manual').length} 项需人工核验</summary><p class="field-note">${esc(q.notice)}</p>${q.checks.map(c=>`<div class="qualification-row"><div><strong>${esc(c.label)}</strong><p>你的填写：${esc(c.value_label)} · ${esc(labels[c.state])}<br>${esc(c.help)}</p></div><div><button class="text-button" data-application-revisit="${esc(c.key)}">补充或修改</button>${evidenceButton(c.citation)}</div></div>`).join('')||'<p class="field-note">当前事项有明确不满足项、尚未毕业或超出自动覆盖，先按结果说明处理，后续再核对补充资格。</p>'}</details>`;
};
function renderApplicationPreparation(){
  const report=state.report,panel=$('#application-preparation');panel.hidden=!report?.application;
  if(!report?.application)return;
  if(state.dirty){$('#application-preparation-message').textContent='申请信息或政策已变化，请重新核对后更新准备清单；旧标记不会套用于新情况。';$('#application-preparation-items').replaceChildren();return;}
  const rows=report.application.preparation_items,items=applicationPreparation.context_sha256===report.application.context_sha256?applicationPreparation.items:{};
  $('#application-preparation-message').textContent=`已自填准备 ${rows.filter(r=>items[r.id]==='ready').length} / ${rows.length} 项；修改后请保存或下载申请草稿。`;
  $('#application-preparation-items').innerHTML=rows.map(r=>`<div class="application-preparation-row"><div><strong>${esc(r.label)}</strong><small>${esc(r.policy_title)} · ${esc(r.kind)}</small></div><label>准备状态<select data-application-preparation="${esc(r.id)}"><option value="not_started">待准备</option><option value="ready" ${items[r.id]==='ready'?'selected':''}>我已准备</option><option value="to_confirm" ${items[r.id]==='to_confirm'?'selected':''}>需单位或官方确认</option></select></label>${evidenceButton(r.citation)}</div>`).join('')||'<p class="field-note">当前事项已有明确不满足项，先处理资格问题，再核对准备清单。</p>';
}
window.applicationReportReady=function(report){
  const context=report.application?.context_sha256;if(!context)return;
  if(applicationPreparation.context_sha256!==context)applicationPreparation={context_sha256:context,items:{}};
  renderApplicationPreparation();
};
window.applicationAssessmentError=message=>{$('#application-flow-message').textContent='未完成核对：'+message;};
window.applicationExportPreparation=report=>report?.application?.context_sha256===applicationPreparation.context_sha256?structuredClone(applicationPreparation):{context_sha256:report?.application?.context_sha256||'',items:{}};
window.applicationQualificationReport=function(row,report){
  const review=row.qualification_review;if(!review)return '';
  const labels={pending:'待补充',manual:'需人工核验',confirmed:'已自填核对'},progress=window.applicationExportPreparation(report).items;
  return `<h4>补充资格核验</h4><p>${esc(review.notice)}</p>${review.checks.length?`<table><thead><tr><th>补充事项</th><th>你的填写</th><th>核对状态</th><th>需核对的内容</th></tr></thead><tbody>${review.checks.map(c=>`<tr><td>${esc(c.label)}</td><td>${esc(c.value_label)}</td><td>${esc(labels[c.state])}</td><td>${esc(c.help)}</td></tr>`).join('')}</tbody></table>`:'<p>请先处理当前阶段、规则条件或覆盖范围问题。</p>'}<h4>自填准备进度</h4><ul>${(report.application?.preparation_items||[]).filter(i=>i.policy_id===row.policy_id).map(i=>`<li>${esc(i.label)}：${esc({ready:'我已准备',to_confirm:'需单位或官方确认',not_started:'待准备'}[progress[i.id]]||'待准备')}</li>`).join('')||'<li>当前没有列出的准备条目</li>'}</ul><p>自填标记不代表材料真实、已提交或获批。</p>`;
};
window.onBaseProfileFilled=function(){applicationExtra=Object.fromEntries(supplementaryKeys.map(k=>[k,null]));applicationDeferred=[];applicationHistory=[];applicationPreparation={context_sha256:'',items:{}};$('#application-date').value=$('#profile-form').elements.namedItem('application_date').value;renderSupplementary();applicationChanged();if(applicationGuideActive)requestApplicationGuide();};
function renderApplicationGuide(data){
  applicationQuestion=data.question;
  $('#application-flow-message').textContent=`当前还有 ${data.remaining} 项待确认，其中 ${data.deferred_count} 项已选择暂不清楚。`;
  $('#application-start').hidden=true;$('#application-back').hidden=!applicationHistory.length;
  const q=data.question;
  if(q){
    const choices=q.type==='bool'?[[true,'是'],[false,'否']]:q.options;
    const control=['bool','select'].includes(q.type)?`<select id="application-answer" required><option value="">请选择</option>${choices.map(([value,label])=>`<option value="${value}" ${q.value===value?'selected':''}>${esc(label)}</option>`).join('')}</select>`:`<input id="application-answer" type="${q.type}" ${q.type==='number'?'min="0" max="600" step="1"':''} required value="${esc(q.value===null||q.value===undefined?'':q.type==='month'?q.value.slice(0,7):q.value)}">`;
    $('#application-question').innerHTML=`<form id="application-answer-form"><label class="application-question-label">${esc(q.label)}${control}</label><p class="field-note">${esc(q.help)}</p><div class="toolbar"><button class="btn btn-primary" type="submit">保存这一步，继续</button><button class="btn btn-quiet" type="button" id="application-skip">暂不清楚，先跳过</button></div></form>`;
  }else{
    $('#application-question').innerHTML=`<div class="application-guide-summary"><h3>${data.remaining?'先保留待确认事项，再看当前结果':'本轮可回答的问题已完成'}</h3><ul>${data.results.map(r=>`<li><strong>${esc(r.title)}</strong>：${esc(r.label)}${r.qualification_status==='outside_scope'?'；超出自动覆盖，请人工核验':''}</li>`).join('')}</ul>${data.pending_keys.length?`<p>稍后可继续补充：</p><div class="toolbar">${data.pending_keys.map(k=>`<button class="btn btn-quiet small" data-application-revisit="${esc(k)}">${esc(k.startsWith('extra.')?applicationMeta?.supplementary_fields[k.slice(6)]?.label||k:state.reviewLabels?.[k]||k)}</button>`).join('')}</div>`:''}<p class="field-note">${esc(data.notice)}</p></div>`;
  }
}
async function requestApplicationGuide(focus){
  const generation=++applicationGeneration;applicationGuideActive=true;$('#application-flow-message').textContent='正在选择下一项需要核对的信息…';
  try{const data=await api('/api/application/guide',{...applicationSnapshot(),...(focus?{focus_question:focus}:{})});if(generation===applicationGeneration){applicationGuideActive=true;renderApplicationGuide(data);}}
  catch(e){if(generation===applicationGeneration)$('#application-flow-message').textContent=e.message+'。可切换完整表单修正，未保存的填写仍保留。';}
}
async function answerApplication(skip=false){
  const q=applicationQuestion;if(!q)return;const generation=++applicationGeneration,before=signature(applicationSnapshot()),body=applicationSnapshot();let value=null;
  if(!skip){const input=$('#application-answer');if(!input.reportValidity())return;const raw=input.value;value=q.type==='bool'?raw==='true':q.type==='number'?Number(raw):q.type==='month'?raw+'-01':raw;}
  if(q.group==='supplementary')body.supplementary[q.field]=value;else body.profile[q.field]=value;
  body.deferred=body.deferred.filter(k=>k!==q.key);if(skip)body.deferred.push(q.key);
  const button=$('#application-answer-form button[type="submit"]'),skipButton=$('#application-skip');if(button)button.disabled=true;if(skipButton)skipButton.disabled=true;
  try{const data=await api('/api/application/guide',body);if(generation!==applicationGeneration)return;if(before!==signature(applicationSnapshot()))throw new Error('填写已变化，请重新保存当前问题');
    if(q.group==='supplementary')applicationExtra[q.field]=value;else setApplicationField(q.field,value);
    applicationDeferred=body.deferred;applicationHistory.push(q.key);renderSupplementary();applicationChanged();renderApplicationGuide(data);
  }catch(e){if(generation===applicationGeneration)$('#application-flow-message').textContent='未保存这一步：'+e.message;}finally{if(button?.isConnected)button.disabled=false;if(skipButton?.isConnected)skipButton.disabled=false;}
}
function applyApplicationMode(){
  const grid=$('#view-match .match-grid');grid.classList.toggle('application-guided-mode',!applicationFullMode);$('#view-match .profile-panel').hidden=!applicationFullMode;
  $('#application-mode').textContent=applicationFullMode?'切回逐问向导':'切换完整表单';$('#application-question').hidden=applicationFullMode;$('#application-start').hidden=applicationFullMode||applicationGuideActive;$('#application-back').hidden=applicationFullMode||!applicationHistory.length;
}
async function makeApplicationPacket(){const snapshot=applicationSnapshot(),before=signature(snapshot);const packet=await api('/api/application/packet',{...snapshot,saved_at:new Date().toISOString()});if(before!==signature(applicationSnapshot()))throw new Error('填写已变化，请再次保存最新进度');return packet;}
function rawDownload(name,raw){const u=URL.createObjectURL(new Blob([raw],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
async function refreshApplicationStorage(){
  const m=await applicationStorage;
  try{const raw=localDraftStore.getItem(m.DRAFT_KEY);$('#application-draft-summary').textContent=raw?'申请草稿 · 已有草稿可恢复':'申请草稿 · 保存、恢复与下载';$('#application-storage-status').textContent=raw?'本浏览器已有申请草稿，点击“恢复已保存草稿”载入；当前填写不会自动替换。':'尚未保存本浏览器申请草稿；填写默认只在当前页面。';}catch{$('#application-storage-status').textContent='浏览器存储暂不可用，可下载申请草稿文件保留进度。';}
  try{const rows=JSON.parse(tabDraftStore.getItem(m.BACKUP_KEY)||'[]');if(!Array.isArray(rows))throw new Error();$('#application-backups').hidden=!rows.length;$('#application-backup-list').replaceChildren();rows.forEach((r,i)=>{const line=document.createElement('div');line.className='backup-row';const label=document.createElement('span');label.textContent=(r.reason||'恢复前备份')+' · '+(r.saved_at||'时间未知');const b=document.createElement('button');b.className='btn btn-quiet small';b.textContent='下载备份 '+(i+1);b.addEventListener('click',()=>rawDownload('惠才通-申请恢复前备份-'+(i+1)+'.json',r.raw));line.append(label,b);$('#application-backup-list').append(line);});}
  catch{$('#application-backups').hidden=false;$('#application-backup-list').textContent='备份暂不可读取，覆盖或清除已保存草稿将停止。';}
}
async function applyApplicationRestore(allowConflict){
  if(!applicationRestorePending)return;const generation=applicationStorageGeneration,pending=applicationRestorePending,m=await applicationStorage,current=await makeApplicationPacket();
  if(generation!==applicationStorageGeneration||pending!==applicationRestorePending)return;
  if(m.restoreConflicts(current,applicationRestorePending.packet)&&!allowConflict){$('#application-restore-conflict').hidden=false;return;}
  if(m.hasWork(current))m.preserveRaw(tabDraftStore,JSON.stringify(current),'恢复前的当前填写');
  const incoming=applicationRestorePending;applicationRestorePending=null;++applicationGeneration;applicationGuideActive=false;applicationQuestion=null;
  if(typeof clearMaterialState==='function')clearMaterialState();
  fillProfile(incoming.packet.profile);applicationExtra={...incoming.packet.supplementary};applicationDeferred=[...incoming.packet.deferred];applicationHistory=[];applicationPreparation=structuredClone(incoming.packet.preparation);$('#application-intent').value=incoming.packet.intent;$('#application-date').value=incoming.packet.profile.application_date||'';
  state.report=null;state.profileSignature=null;state.applicationPolicyDirty=false;$('#results').innerHTML='<div class="simple-empty">已恢复填写进度，请重新核对当前政策和补充资格后生成结果。</div>';$('#application-restore-conflict').hidden=true;renderSupplementary();markProfileChanged();renderApplicationPreparation();applicationDirty=incoming.stale||!incoming.fromLocal;
  $('#application-message').textContent=incoming.notice;refreshApplicationStorage();if(!applicationFullMode)requestApplicationGuide();
}
async function loadApplicationRaw(raw,fromLocal,generation){
  if(new TextEncoder().encode(raw).length>200000)throw new Error('申请草稿请控制在200KB以内');
  const packet=parseJSONInput(raw,'申请草稿'),result=await api('/api/application/restore',{packet});if(generation!==applicationStorageGeneration)return;applicationRestorePending={...result,fromLocal};await applyApplicationRestore(false);
}
$('#application-start').addEventListener('click',()=>requestApplicationGuide());
$('#application-mode').addEventListener('click',()=>{applicationFullMode=!applicationFullMode;applyApplicationMode();if(!applicationFullMode&&applicationGuideActive)requestApplicationGuide();});
$('#application-show-results').addEventListener('click',()=>assess());
$('#application-back').addEventListener('click',()=>{const key=applicationHistory.pop();if(key)requestApplicationGuide(key);});
$('#application-question').addEventListener('submit',e=>{e.preventDefault();answerApplication();});
$('#application-question').addEventListener('click',e=>{if(e.target.closest('#application-skip'))answerApplication(true);});
window.openApplicationQuestion=function(key){applicationFullMode=false;applyApplicationMode();requestApplicationGuide(key);$('#application-wizard').scrollIntoView({behavior:'smooth',block:'start'});};
document.addEventListener('click',e=>{const b=e.target.closest('[data-application-revisit]');if(b)window.openApplicationQuestion(b.dataset.applicationRevisit);});
$('#application-intent').addEventListener('change',()=>{applicationDeferred=[];applicationHistory=[];applicationChanged();if(applicationGuideActive)requestApplicationGuide();});
$('#application-date').addEventListener('change',()=>{setApplicationField('application_date',$('#application-date').value||null);applicationChanged();if(applicationGuideActive)requestApplicationGuide();});
$('#profile-form').addEventListener('input',()=>{applicationChanged();$('#application-date').value=$('#profile-form').elements.namedItem('application_date').value;});
$('#profile-form').addEventListener('change',applicationChanged);
$('#application-extra-fields').addEventListener('change',e=>{const k=e.target.dataset.applicationExtra;if(!k)return;const d=applicationMeta.supplementary_fields[k];applicationExtra[k]=e.target.value===''?null:d.type==='bool'?e.target.value==='true':e.target.value;applicationChanged();});
$('#application-preparation-items').addEventListener('change',e=>{const id=e.target.dataset.applicationPreparation;if(!id||state.dirty)return;applicationPreparation.items[id]=e.target.value;applicationDirty=true;renderApplicationPreparation();});
$('#application-save').addEventListener('click',async()=>{const generation=++applicationStorageGeneration;try{const packet=await makeApplicationPacket(),m=await applicationStorage;if(generation!==applicationStorageGeneration)return;m.saveExplicit(localDraftStore,tabDraftStore,packet);applicationPreparation=structuredClone(packet.preparation);applicationDirty=false;$('#application-message').textContent='已保存本浏览器申请草稿；更改后请再次保存。';refreshApplicationStorage();}catch(e){$('#application-message').textContent='未保存：'+e.message+'。原草稿保留，可下载当前草稿文件。';}});
$('#application-export').addEventListener('click',async()=>{try{const packet=await makeApplicationPacket();download('惠才通-申请草稿.json',packet);applicationDirty=false;$('#application-message').textContent='已生成申请草稿下载，请确认文件已保存。';}catch(e){$('#application-message').textContent='未导出：'+e.message;}});
$('#application-restore').addEventListener('click',async()=>{const generation=++applicationStorageGeneration;let raw=null;try{const m=await applicationStorage;raw=localDraftStore.getItem(m.DRAFT_KEY);if(raw===null)throw new Error('本浏览器尚无已保存草稿');await loadApplicationRaw(raw,true,generation);}catch(e){$('#application-message').textContent='未恢复：'+e.message;if(raw!==null){applicationRaw=raw;$('#application-raw-download').hidden=false;}}});
$('#application-import').addEventListener('click',()=>$('#application-file').click());
$('#application-file').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;const generation=++applicationStorageGeneration;try{if(f.size>200000)throw new Error('申请草稿请控制在200KB以内');await loadApplicationRaw(await f.text(),false,generation);}catch(error){$('#application-message').textContent='未导入：'+error.message;}finally{e.target.value='';}});
$('#application-raw-download').addEventListener('click',()=>{if(applicationRaw!==null)rawDownload('惠才通-未恢复原始申请草稿.txt',applicationRaw);});
$('#application-cancel-restore').addEventListener('click',()=>{++applicationStorageGeneration;applicationRestorePending=null;$('#application-restore-conflict').hidden=true;$('#application-message').textContent='已保留当前填写，未执行恢复。';});
$('#application-apply-restore').addEventListener('click',async()=>{try{await applyApplicationRestore(true);}catch(e){$('#application-message').textContent='恢复已停止：'+e.message+'。当前填写保留，请先下载草稿备份。';}});
$('#application-clear').addEventListener('click',async()=>{const generation=++applicationStorageGeneration;applicationRestorePending=null;$('#application-restore-conflict').hidden=true;try{const m=await applicationStorage;if(generation!==applicationStorageGeneration)return;const changed=m.clearSaved(localDraftStore,tabDraftStore);$('#application-message').textContent=changed?'已清除本浏览器草稿，并保留清除前标签页备份。当前页面填写未清空。':'本浏览器没有已保存的申请草稿。';refreshApplicationStorage();}catch(e){$('#application-message').textContent='未清除：'+e.message+'。原草稿保留。';}});
window.addEventListener('hct:policies-updated',()=>{window.invalidateApplicationAssessment?.();if(state.report){state.applicationPolicyDirty=true;markProfileChanged();renderApplicationPreparation();}if(applicationGuideActive)requestApplicationGuide();});
window.addEventListener('beforeunload',e=>{if(applicationDirty){e.preventDefault();e.returnValue='';}});
$('#application-date').value=$('#profile-form').elements.namedItem('application_date').value;applyApplicationMode();refreshApplicationStorage();
api('/api/application/meta').then(meta=>{applicationMeta=meta;renderSupplementary();}).catch(e=>{$('#application-flow-message').textContent='补充核验资料未载入：'+e.message;});
