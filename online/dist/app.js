'use strict';
const $ = (q, root=document) => root.querySelector(q);
const $$ = (q, root=document) => [...root.querySelectorAll(q)];
const state = {policies:[],examples:[],meta:{},report:null,profileSignature:null,dirty:false};
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const status = {eligible:['初筛通过','pass'],ineligible:['暂不满足','fail'],insufficient:['待补充 / 核验','unknown']};
let toastTimer;
function toast(message, error=false){const el=$('#toast');el.textContent=message;el.classList.toggle('error',error);el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,error?6500:3500);}
async function api(url,body){const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};const res=await fetch(url,options);const data=await res.json();if(!res.ok)throw new Error(data.error||'请求失败，请稍后重试');return data;}
function safeURL(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:'#';}catch{return '#';}}
function parseJSONInput(content,label='文件'){
  try{return JSON.parse(content.replace(/^\uFEFF/,''));}
  catch{throw new Error(label+'不是有效的 JSON。请使用下载的模板，检查引号、逗号和括号；原有记录未更改。');}
}
function download(name,data){const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function setView(name,fromHistory=false){
  const known=['match','materials','knowledge','search','training','review','review-v08','review-ai','report'];
  const valid=known.includes(name);if(!valid)name='match';
  $$('.view').forEach(el=>el.hidden=el.id!==`view-${name}`);
  $$('.nav-item').forEach(el=>{el.classList.toggle('active',el.dataset.view===name);el.setAttribute('aria-current',el.dataset.view===name?'page':'false');});
  $('#breadcrumb-title').textContent={match:'政策匹配',materials:'材料核验',review:'人工复核',knowledge:'政策知识库',search:'证据检索',training:'训练与评测',report:'中文报告','review-v08':'v0.8 独立复核','review-ai':'AI 辅助预审'}[name];
  if(location.hash!==`#${name}`)history[fromHistory||!valid?'replaceState':'pushState'](null,'',`#${name}`);
  if(name==='report'){
    if(!state.report)$('#readable-report').innerHTML='<p>当前没有核验报告。请返回政策匹配填写并核对资料，再生成中文报告。</p>';
    else if(typeof refreshReadableReport==='function')refreshReadableReport();
    markProfileChanged();
  }
  window.scrollTo({top:0,behavior:'instant'});
}
function fillProfile(profile){const form=$('#profile-form');for(const el of form.elements){if(!el.name)continue;let value=profile[el.name];if(el.name==='insurance_start_date'&&value)value=value.slice(0,7);el.value=value===null||value===undefined?'':String(value);}$('#profile-error').hidden=true;window.onBaseProfileFilled?.(profile);markProfileChanged();}
function readProfile(){const p={city:'杭州'};for(const el of $('#profile-form').elements){if(!el.name)continue;const v=el.value;if(el.hasAttribute('data-bool'))p[el.name]=v===''?null:v==='true';else if(el.name==='insurance_months')p[el.name]=v===''?null:Number(v);else if(el.name==='insurance_start_date')p[el.name]=v?v+'-01':null;else p[el.name]=v||null;}return p;}
function evidenceButton(id){return `<button class="cite-button" data-evidence="${esc(id)}">查看依据 ↗</button>`;}
function signature(profile){return JSON.stringify(Object.fromEntries(Object.entries(profile).sort(([a],[b])=>a.localeCompare(b))));}
function markProfileChanged(){
  state.dirty=!!state.report&&(state.applicationPolicyDirty||(window.applicationSignature?.(readProfile())||signature(readProfile()))!==state.profileSignature);
  $('#report-stale').hidden=!state.dirty;
  $('#export-report').disabled=!state.report||state.dirty;
  for(const id of ['print-report','download-readable','export-json']){const button=$('#'+id);if(button)button.disabled=!state.report||state.dirty;}
  if($('#report-stale-copy'))$('#report-stale-copy').hidden=!state.dirty;
  $$('[data-model]').forEach(button=>button.disabled=state.dirty||!state.meta.model_configured||button.dataset.busy==='true');
  $('#results').classList.toggle('stale-results',state.dirty);
}
function focusField(field){if(window.openApplicationQuestion){window.openApplicationQuestion(field);return;}const input=$('#profile-form').elements.namedItem(field);if(!input)return;const details=input.closest('details');if(details)details.open=true;input.scrollIntoView({behavior:'smooth',block:'center'});input.focus({preventScroll:true});input.classList.add('field-highlight');setTimeout(()=>input.classList.remove('field-highlight'),1800);}
function renderGuidance(report){
  const rows=report.guidance?.followups||[];
  if(!rows.length)return '';
  return `<section class="followup-panel"><div class="panel-heading"><h3>补全 ${rows.length} 个关键信息</h3><span class="method-tag">按影响事项排序</span></div><p class="field-note">${esc(report.guidance.notice)}</p><div class="followup-list">${rows.map(q=>`<button class="followup-item" data-focus-field="${esc(q.field)}"><span><strong>${esc(q.label)}</strong><small>${esc(q.question)}</small></span><b>${q.policy_ids.length} 项 ↗</b></button>`).join('')}</div></section>`;
}
function renderTimeline(result){
  if(!result.timeline?.length)return '';
  return `<details class="policy-details"><summary>申请时间轴 · ${result.timeline.length} 个参考节点</summary><div class="timeline">${result.timeline.map(t=>`<div class="timeline-row"><div><strong>${esc(t.date)}</strong><span>${esc(t.label)}</span></div>${evidenceButton(t.citation)}</div>`).join('')}</div><p class="field-note">根据所填日期和已录入规则计算。参保节点假定从起算月持续有效缴费，不代表已缴满或确定发放；实际时长仍按已填写的完整月数核对。</p></details>`;
}
function renderResults(report){
  const pass=report.results.filter(r=>r.conclusion==='eligible'&&(!r.qualification_review||r.qualification_review.status==='recorded')).length;
  $('#results').innerHTML=`<div class="result-summary"><span>已核对 ${report.results.length} 项，${pass} 项所列条件满足且补充项无待核验</span><span>参考日期 ${esc(report.as_of)}</span></div>`+renderGuidance(report)+report.results.map(r=>{
    const d=r.display||{}, [baseLabel,baseClass]=status[r.qualification_review&&['pending','manual'].includes(r.qualification_review.status)?'insufficient':r.conclusion];
    const label=d.label||baseLabel,cls=d.planning?'unknown':baseClass;
    return `<article class="policy-result" data-policy="${esc(r.policy_id)}"><div class="policy-result-head"><div class="category-label">${esc(state.policies.find(p=>p.id===r.policy_id)?.category||'人才服务')} · 规则初筛</div><div class="policy-heading"><h3>${esc(r.title)}</h3><span class="status-pill ${cls}">${esc(label)}</span></div><p class="reason">${esc(d.reason||r.reason)}</p>${r.missing_labels.length&&!d.planning?`<div class="missing-box">待补充：${r.missing_labels.map(esc).join('、')}</div>`:''}${renderBenefit(r)}${renderDecisionNotes(r)}<div class="next-step"><strong>下一步到哪里办理</strong><p>${esc(r.application_channel)}</p><small>来源发布 ${esc(d.source?.published_on||'待核对')} · ${esc(d.source?.legal_status||'现行效力待核验')}</small></div></div><div class="policy-actions"><a href="${esc(safeURL(r.source_url))}" target="_blank" rel="noopener noreferrer">核对官方指南 ↗</a><button class="btn btn-quiet" data-model="${esc(r.policy_id)}" ${!state.meta.model_configured?'disabled title="公开版未启用在线推理"':''}>${state.meta.model_configured?'实验模型交叉核验 →':'公开版未启用在线模型'}</button></div><div class="model-slot"></div><details class="policy-details"><summary>逐条核对 · ${r.checks.filter(c=>c.status==='pass').length}/${r.checks.length} 项满足</summary>${r.checks.map((c,i)=>renderResultCheck(c,d.checks?.[i])).join('')}<p class="field-note">${esc(r.scope_note)}</p></details><details class="policy-details"><summary>核验准备清单 · ${r.materials.length} 项</summary><ul class="materials">${r.materials.map(m=>`<li><span>${esc(m.label)}<small>${esc(m.kind)}</small></span>${evidenceButton(m.citation)}</li>`).join('')}<p class="field-note">准备状态可在“我的准备进度”中标记并保存。</p></ul></details>${window.sourceTimeMarkup?.(r.source_time)||''}${window.renderQualificationReview?.(r)||''}${renderTimeline(r)}</article>`;
  }).join('');
  for(const [id,response] of Object.entries(report.model_assessments||{})){const article=$$('.policy-result').find(a=>a.dataset.policy===id);if(article)$('.model-slot',article).innerHTML=renderModel(response);}
  markProfileChanged();window.applicationReportReady?.(report);
}
let assessmentGeneration=0;
window.invalidateApplicationAssessment=()=>++assessmentGeneration;
async function assess(event){
  event?.preventDefault();
  const generation=++assessmentGeneration,button=$('#assess-button'),original=button.innerHTML,show=$('#application-show-results');
  const profile=readProfile(),body=window.applicationRequest?.(profile)||{profile};
  button.disabled=true;if(show)show.disabled=true;
  button.innerHTML='<span class="spinner"></span>正在核对';$('#profile-error').hidden=true;
  try{
    const report=await api('/api/application/assess',body);if(generation!==assessmentGeneration)return;
    state.report=report;state.applicationPolicyDirty=false;
    report.material_confirmations=(state.materialConfirmations||[]).filter(r=>r.fields.every(f=>profile[f.field]===f.value&&Object.entries(f.context||{}).every(([key,value])=>profile[key]===value)));
    state.profileSignature=window.applicationSignature?.(profile,body)||signature(profile);renderResults(report);
    if(matchMedia('(max-width:1000px)').matches)$('#results').scrollIntoView({behavior:'smooth',block:'start'});
    toast('已完成规则与补充资格核对，可展开查看依据');
  }catch(e){if(generation===assessmentGeneration){$('#profile-error').textContent=e.message;$('#profile-error').hidden=false;window.applicationAssessmentError?.(e.message);}}
  finally{button.disabled=false;if(show)show.disabled=false;button.innerHTML=original;}
}
function showEvidence(id){for(const p of state.policies){const c=p.clauses.find(c=>c.id===id);if(c){$('#evidence-content').innerHTML=`<span class="method-tag">${esc(c.id)}</span><h2>${esc(p.title)}</h2><div class="source-line">${esc(c.section)}</div><div class="evidence-text">${esc(c.text)}</div><div class="source-line">整理说明：上文为原文要点转述，完整表述请查看官方来源。</div><div class="source-line">来源：${esc(p.source_org)} · 发布 ${esc(p.published_on)}</div><div class="source-line">来源核对：${esc(p.checked_on)} · ${esc(p.legal_status||'现行效力待核验')}</div><a class="btn btn-primary" href="${esc(safeURL(p.source_url))}" target="_blank" rel="noopener noreferrer">打开官方原文 ↗</a><div class="clause-primary-evidence"></div>`;$('#evidence-dialog').showModal();window.loadClauseEvidence?.(id,$('#evidence-content .clause-primary-evidence'));return;}}toast('未找到对应证据',true);}
function renderKnowledge(){const term=$('#policy-filter').value.trim();const history=$('#show-history').checked;const list=state.policies.filter(p=>(history||p.status!=='archived')&&(!term||(p.title+p.summary+p.clauses.map(c=>c.text).join('')).includes(term)));$('#knowledge-list').innerHTML=list.length?list.map(p=>`<article class="panel knowledge-card ${p.status==='archived'?'archive-card':''}"><div class="evidence-meta"><span>${esc(p.category)}</span><span class="status-pill ${p.status==='included'?'pass':'unknown'}">${{included:'已收录 · 效力待复核',archived:'历史隔离',reference:'仅供参考'}[p.status]}</span></div><h3>${esc(p.title)}</h3><p>${esc(p.summary)}</p><p>${esc(p.amount_note)}</p><details><summary>规则覆盖范围与 ${p.clauses.length} 条证据</summary><p>${esc(p.coverage)}</p>${p.clauses.map(c=>`<div class="check-row"><span>↳</span><span>${esc(c.section)}</span>${evidenceButton(c.id)}</div>`).join('')}</details><div class="source-meta">${esc(p.source_org)} · 发布 ${esc(p.published_on)}<br>来源核对 ${esc(p.checked_on)} · ${esc(p.legal_status||'现行效力待核验')}</div><div class="card-bottom"><span class="method-tag">${p.rules.length} 条核验规则</span><a class="text-button" href="${esc(safeURL(p.source_url))}" target="_blank" rel="noopener noreferrer">官方原文 ↗</a></div></article>`).join(''):'<div class="simple-empty">没有符合筛选条件的政策。</div>';}
function renderTrainingStatus(){
  const info=state.meta.training||{};
  const label=$('#view-training .page-heading .status-pill');
  const stage=$('.pipeline li:nth-child(4) em');
  if(info.sft){$('.pipeline li:nth-child(3) em').textContent='已生成 · 待人工复核';$('.pipeline li:nth-child(5) em').textContent='待正式评测';}
  if(info.grpo?.reward_signal_steps>0){label.textContent='初始训练已完成 · 正式评测待做';stage.textContent=`SFT ${info.sft?.steps_completed||0} 步 / GRPO ${info.grpo.steps_completed} 步`;}
  else if(info.grpo){label.textContent='训练循环已验证 · 奖励待改善';stage.textContent='需检查有效梯度';}
  else if(info.sft){label.textContent='SFT 已运行 · GRPO 待验证';stage.textContent=`SFT ${info.sft.steps_completed} 步`;}
  if(info.sft||info.grpo){const old=$('#gpu-run-note');if(old)old.remove();const note=document.createElement('p');note.id='gpu-run-note';note.className='field-note';note.textContent=`本机 PyTorch 峰值已分配显存：SFT ${info.sft?.max_gpu_allocated_gb??'—'} GiB，GRPO ${info.grpo?.max_gpu_allocated_gb??'—'} GiB。不包含桌面及其他进程。`;$('.config-pairs').after(note);}
  const reports=state.meta.model_evaluations||[];
  if(reports.length){
    $('#model-metrics')?.remove();
    const latest=reports.filter(r=>r.per_class&&r.cases===92).at(-1);
    const pct=value=>value===null||value===undefined?'—':(value*100).toFixed(1)+'%';
    const panel=document.createElement('section');panel.id='model-metrics';panel.className='panel model-metrics';
    panel.innerHTML=`<div class="panel-heading"><h2>模型开发诊断 · 真实预测</h2><span class="status-pill unknown">尚待人工政策基准</span></div><p class="selection-note">默认模型：${esc(state.meta.selected_model?.model_id||'尚未冻结')}。按完整开发集的结构完全一致率、结论一致率依次选择。</p><p class="field-note">标签来自规则程序。开发集参与了调试；租房文件族未进入训练，前 12 条已在首轮查看。这些是旧固定提示的历史实验；当前检索核验尚无独立准确率结果，也不能单独证明 GRPO 收益。</p><table class="eval-table"><thead><tr><th>实验</th><th>范围</th><th>结论与弱标签一致</th><th>有效 JSON</th><th>结构完全一致</th></tr></thead><tbody>${reports.map(r=>`<tr><td>${esc(r.label)}</td><td>${esc(r.scope)}</td><td>${r.correct} / ${r.cases}</td><td>${pct(r.valid_output_rate)}</td><td>${pct(r.structured_exact_match)}</td></tr>`).join('')}</tbody></table>${latest?`<h3 class="metric-subtitle">按类别检查 · ${esc(latest.label)}</h3><table class="eval-table"><thead><tr><th>程序参考类别</th><th>参考样本数</th><th>模型预测该类数</th><th>精确率</th><th>召回率</th></tr></thead><tbody>${Object.entries(latest.per_class).map(([name,m])=>`<tr><td>${esc(status[name]?.[0]||name)}</td><td>${m.support}</td><td>${m.predicted}</td><td>${pct(m.precision)}</td><td>${pct(m.recall)}</td></tr>`).join('')}</tbody></table>`:''}<p class="field-note">结构完全一致要求结论、引用、缺失字段和准备清单同时匹配，不评价解释文字。完整开发集结果比前 12 条流程检查更有代表性，但仍是同源合成诊断；需要另建人工标注基准。</p>`;
    $('.evaluation-panel').before(panel);
    if(latest)$('.pipeline li:nth-child(5) em').textContent='开发诊断已完成';
  }
}
let evidenceSearchGeneration=0;
for(const id of ['search-date','search-history','search-later-snapshot','search-mode'])$('#'+id).addEventListener('change',()=>{
  ++evidenceSearchGeneration;$('#search-results').innerHTML='<p class="field-note">检索日期或范围已变化，请重新检索；上次结果不作为当前日期的依据。</p>';
  $('#search-later-snapshot').disabled=$('#search-mode').value!=='primary';
});
async function search(event){
  event?.preventDefault();const generation=++evidenceSearchGeneration,query=$('#search-query').value.trim();if(!query){$('#search-results').innerHTML='<div class="simple-empty">输入问题，查看可追溯的政策证据。</div>';return;}
  $('#search-results').innerHTML='<div class="result-loading"><span class="spinner"></span>正在检索证据</div>';
  try{
    const date=$('#search-date').value,history=$('#search-history').checked;
    if($('#search-mode').value==='primary'){
      const html=await window.searchPrimaryEvidence(query,date,history);if(generation===evidenceSearchGeneration)$('#search-results').innerHTML=html;return;
    }
    const params=new URLSearchParams({q:query,as_of:date,history:history?'1':'0'});const data=await api('/api/search?'+params);if(generation!==evidenceSearchGeneration)return;
    $('#search-results').innerHTML=`<div class="result-summary"><span>找到 ${data.results.length} 条整理证据</span><span>整理要点检索 · 词法相关度不是可信概率</span></div>`+renderSearchSummaries(data.policy_summaries||[])+(data.results.length?data.results.map(r=>`<article class="evidence-card"><div class="evidence-meta"><span>${esc(r.source_org)} · ${esc(r.published_on)}</span><span class="method-tag">${esc(r.id)}${r.status==='archived'?' · 历史资料':r.outside_reference_period?' · 参考期外资料':''}</span></div><h3>${esc(r.policy_title)} / ${esc(r.section)}</h3><p>${esc(r.text)}</p><div class="evidence-meta"><span>BM25 相关度 ${r.score.toFixed(2)}</span><button class="text-button" data-evidence="${esc(r.id)}">核对整理条款与原文 ↗</button></div></article>`).join(''):'<div class="simple-empty">当前日期与收录范围内没有相关证据，请换个关键词。</div>');
  }catch(e){if(generation===evidenceSearchGeneration)$('#search-results').innerHTML=`<div class="form-error">${esc(e.message)}</div>`;}
}
async function runEvaluation(){const button=$('#run-evaluation');button.disabled=true;$('#evaluation-results').innerHTML='<div class="result-loading"><span class="spinner"></span>正在运行合成场景验收</div>';try{const r=await api('/api/evaluate',{});$('#evaluation-results').innerHTML=`<div class="evaluation-score"><strong>${r.passed} / ${r.total}</strong><span>场景通过 · ${r.checks} 项结论比较<br>当前方法：规则基线；模型对照见上方诊断表</span></div><table class="eval-table"><thead><tr><th>合成场景</th><th>比较项</th><th>结果</th></tr></thead><tbody>${r.cases.map(c=>`<tr><td>${esc(c.name)}</td><td>${c.details.length} 项</td><td><span class="status-pill ${c.passed?'pass':'fail'}">${c.passed?'通过':'需检查'}</span></td></tr>`).join('')}</tbody></table>`;toast(`验收完成：${r.passed}/${r.total} 个场景通过`);}catch(e){$('#evaluation-results').innerHTML=`<div class="form-error">${esc(e.message)}</div>`;}finally{button.disabled=false;}}
async function refresh(){const [meta,policies,examples]=await Promise.all([api('/api/meta'),api('/api/policies'),api('/api/examples')]);state.meta=meta;state.policies=policies.policies;state.examples=examples.examples;$('#stat-policies').innerHTML=`${meta.policies}<small>项</small>`;$('#stat-clauses').innerHTML=`${meta.clauses}<small>条</small>`;$('#checked-on').textContent=meta.checked_on.replaceAll('-','.');$('#side-mode').textContent=meta.model_configured?'本地实验模型 · 结果需核验':'浏览器规则核验 · 公开演示';$('#model-settings').innerHTML=meta.model_configured?'模型状态 / 设置 ↗':'模型实验说明 ↗';renderKnowledge();if(state.report)renderResults(state.report);}
function renderModel(response){
  const result=response.result,audit=response.audit,review=audit?.status==='needs_review';
  const policy=state.policies.find(p=>p.id===result.policy_id);
  const describe=(field,id)=>field==='evidence_ids'?policy?.clauses.find(c=>c.id===id)?.section||id:field==='materials'?policy?.materials.find(m=>m.id===id)?.label||id:$('#profile-form').elements.namedItem(id)?.closest('label')?.firstChild?.textContent?.trim()||id;
  const relevant=(audit?.blocking_checks||[]).filter(c=>c.status==='fail'||result.conclusion==='eligible');
  const conflicts=relevant.length?relevant.map(c=>`<li><strong>${esc(c.label)}</strong>：${c.status==='unknown'?'待确认':'当前不满足'}；所填 / 计算值：${esc(c.actual_label)} ${evidenceButton(c.citation)}</li>`).join(''):(audit?.issues||[]).filter(i=>i.severity==='review').map(i=>`<li>${esc(i.message)}</li>`).join('');
  return `<div class="model-result"><strong>${review?'核验存在冲突，请先核对具体条件':'模型结构化对照完成'}</strong><p class="model-action">${esc(audit?.next_action||'实验输出需另行核验。')}</p>${review?`<ul class="conflict-checks">${conflicts}</ul><p>如资料填错，请修改后重新初筛；如资料无误，请持原文向受理系统确认。</p>`:'<p>规则与模型的结构化对照一致，仍不代表解释文字正确或资格获批。</p>'}<details class="model-experiment"><summary>查看实验模型输出${review?'（存在冲突，不作办理建议）':''}</summary><p>模型 ${esc(response.model)} · 原始结论：${esc(status[result.conclusion]?.[0]||result.conclusion)}</p><p>${esc(result.explanation)}</p><p>${result.evidence_ids.map(evidenceButton).join(' ')}</p><details class="raw-model"><summary>原始结构化结果 JSON</summary><pre>${esc(JSON.stringify(result,null,2))}</pre></details></details>${response.retrieval?renderRetrievalTrace(response.retrieval):'<p class="field-note">旧版对照：所选事项全部条款。</p>'}${audit?`<details class="audit-box ${review?'audit-review':''}"><summary>查看完整结构化差异</summary><ul>${audit.issues.map(issue=>`<li>${esc(issue.message)}${issue.missing?.length?`<small>参考包含而模型遗漏：${issue.missing.map(id=>esc(describe(issue.field,id))).join('、')}</small>`:''}${issue.extra?.length?`<small>模型另外列出：${issue.extra.map(id=>esc(describe(issue.field,id))).join('、')}</small>`:''}</li>`).join('')}</ul><p>${esc(audit.notice)}</p></details>`:''}<p class="field-note">原始实验结果完整保留，未用规则答案替换模型输出。</p></div>`;
}
async function modelAssess(id,button){
  if(state.dirty||!state.report)return;
  const article=button.closest('.policy-result'),slot=$('.model-slot',article),report=state.report;
  const original=button.textContent;button.disabled=true;button.dataset.busy='true';button.textContent='模型核验中…';
  slot.innerHTML='<div class="model-result"><span class="spinner"></span>正在请求模型，随后逐项对照引用、缺失信息与准备清单。</div>';
  try{
    const response=await api('/api/model-assess',{policy_id:id,profile:report.profile,question:$('#assessment-question').value.trim(),evidence_mode:$('#evidence-mode').value});
    report.model_assessments??={};const record={...response,checked_at:new Date().toISOString()};report.model_assessments[id]=record;report.model_runs??=[];report.model_runs.push(record);
    if(report===state.report&&typeof refreshReadableReport==='function')refreshReadableReport();
    if(report===state.report&&article.isConnected)slot.innerHTML=renderModel(response);
  }catch(e){if(report===state.report&&article.isConnected)slot.innerHTML=`<div class="model-result"><strong>模型核验未完成</strong>${esc(e.message)}</div>`;}
  finally{delete button.dataset.busy;button.disabled=state.dirty||!state.meta.model_configured;button.textContent=original;}
}
document.addEventListener('click',async event=>{const nav=event.target.closest('[data-view]');if(nav)setView(nav.dataset.view);const evidence=event.target.closest('[data-evidence]');if(evidence)showEvidence(evidence.dataset.evidence);const example=event.target.closest('[data-example]');if(example){const c=state.examples[Number(example.dataset.example)];if(c){if(typeof clearMaterialState==='function')clearMaterialState();fillProfile(c.profile);toast('已载入合成案例：'+c.name);}}const query=event.target.closest('[data-query]');if(query){$('#search-query').value=query.dataset.query;await search();}const close=event.target.closest('[data-close]');if(close)close.closest('dialog').close();const copy=event.target.closest('[data-copy]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copy);toast('命令已复制，在项目目录终端运行');}catch{toast('复制不可用，请从页面手动选择命令',true);}}const model=event.target.closest('[data-model]');if(model&&!model.disabled)await modelAssess(model.dataset.model,model);});
$$('[data-bool]').forEach(el=>el.innerHTML='<option value="">待确认</option><option value="true">是</option><option value="false">否</option>');
$('#profile-form').addEventListener('submit',assess);
$('#profile-form').addEventListener('input',markProfileChanged);
$('#profile-form').addEventListener('change',markProfileChanged);
$('#results').addEventListener('click',event=>{const button=event.target.closest('[data-focus-field]');if(button)focusField(button.dataset.focusField);});
$('#reset-profile').addEventListener('click',()=>{if(typeof clearMaterialState==='function')clearMaterialState();fillProfile({application_date:todayInput()});state.report=null;state.profileSignature=null;markProfileChanged();$('#export-report').disabled=true;$('#results').innerHTML='<div class="empty-state"><h3>已清空申请信息</h3><p>填写基本情况后，重新开始核对。</p></div>';});
$('#export-report').addEventListener('click',()=>openReadableReport());
$('#model-settings').addEventListener('click',()=>$('#model-dialog').showModal());
$('#refresh-model').addEventListener('click',async()=>{try{await refresh();toast(state.meta.model_configured?'已检测到模型配置，调用是否成功需实际核验':'公开版运行正常，当前不提供在线模型推理');}catch(e){toast(e.message,true);}});
$('#policy-filter').addEventListener('input',renderKnowledge);$('#show-history').addEventListener('change',renderKnowledge);$('#search-form').addEventListener('submit',search);$('#run-evaluation').addEventListener('click',runEvaluation);
$('#import-button').addEventListener('click',()=>$('#policy-file').click());
$('#policy-file').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>500000)throw new Error('政策文件请控制在 500KB 以内');const body=parseJSONInput(await file.text(),'政策文件');const r=await api('/api/import',body);await refresh();toast(`已导入 ${r.imported} 份政策，仅影响当前浏览器。${r.storage_notice||''}`);}catch(e){toast(e.message,true);}event.target.value='';});
$('#download-template').addEventListener('click',()=>{if(!state.policies.length)return;const p=structuredClone(state.policies[0]);p.id='hz-custom-policy-v1';p.family='hz-custom';p.title='请修改：政策标题';p.status='reference';const mapping=Object.fromEntries(p.clauses.map((c,i)=>[c.id,`custom-clause-${i+1}`]));p.clauses.forEach(c=>c.id=mapping[c.id]);[...p.rules,...p.scope,...p.materials].forEach(r=>r.citation=mapping[r.citation]);download('杭州政策导入模板.json',{city:'杭州',policies:[p]});toast('模板为参考状态；修改来源、内容和编号后再导入');});
window.addEventListener('hashchange',()=>setView(location.hash.slice(1),true));
setView(location.hash.slice(1)||'match',true);
refresh().then(renderTrainingStatus).catch(e=>toast('服务加载失败：'+e.message,true));
