'use strict';

function todayInput(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
$('#profile-form').elements.namedItem('application_date').value=todayInput();
$('#search-date').value=todayInput();
updateMaterialContext();

function renderBenefit(r){
  const b=r.display?.benefit;
  return `<div class="benefit-summary"><strong>${esc(b?.label||r.amount_label)}</strong><p>${esc(b?.basis||r.amount_note)}</p>${b?.standard_note&&b.standard_note!==b.basis?`<small>${esc(b.standard_note)}</small>`:''}<small>${esc(b?.notice||'按收录资料口径展示，实际标准与获批金额需官方确认。')}</small></div>`;
}

function renderDecisionNotes(r){
  if(r.display?.planning)return `<div class="planning-notes"><strong>现在可以准备什么</strong><ol>${r.display.preparation.map(t=>`<li>${esc(t)}</li>`).join('')}</ol>${r.display.other_blockers?.length?`<strong>这些非时间条件也要核对</strong><ul>${r.display.other_blockers.map(c=>`<li>${esc(c.label)}：当前不满足 ${evidenceButton(c.citation)}</li>`).join('')}</ul>`:''}<p>以下日期按所填预计毕业日期计算，仅供准备；实际毕业后需重新核对。</p></div>`;
  const blockers=r.display?.blockers||[];
  if(!blockers.length)return '';
  return `<div class="decision-notes"><strong>先核对这些条件</strong><ul>${blockers.slice(0,3).map(c=>`<li>${esc(c.label)}：${c.status==='fail'?'当前不满足':'待确认'}（所填 / 计算值：${esc(c.actual_label)}） ${evidenceButton(c.citation)}</li>`).join('')}</ul>${blockers.length>3?'<small>其余条件可在下方“逐条核对”中查看。</small>':''}</div>`;
}

function renderResultCheck(c,display){
  const d=display||c;
  const label={pass:'满足',fail:'不满足',unknown:'待确认',not_started:'尚未开始'}[d.status];
  return `<div class="check-row"><span class="check-indicator ${d.status}" aria-label="${label}">${{pass:'✓',fail:'×',unknown:'?',not_started:'○'}[d.status]}</span><span>${esc(d.label)}${d.note?`<small class="check-explanation">${esc(d.note)}</small>`:''}</span>${evidenceButton(c.citation)}</div>`;
}

function renderSearchSummaries(rows){
  if(!rows.length)return '';
  return `<section class="search-metadata"><h2>相关资料的金额与办理说明</h2><p>以下为知识库的政策摘要，不是检索条款或获批结论。金额依收录日期口径，现行效力待核验。</p>${rows.map(p=>`<article><h3>${esc(p.title)}${p.outside_reference_period?'（参考期外，仅供历史对照）':''}</h3><p>${esc(p.amount_note)}</p><p>办理渠道：${esc(p.application_channel)}</p><small>发布 ${esc(p.published_on)} · ${esc(p.legal_status)}</small><a href="${esc(safeURL(p.source_url))}" target="_blank" rel="noopener noreferrer">核对官方指南 ↗</a></article>`).join('')}</section>`;
}

const fieldHelp={
  employer_qualified:{title:'不确定单位是否符合条件时，先保留“待确认”',intro:'下面是核对方法，不会仅凭办公地址替你认定单位资格。请让单位人事结合官方指南确认。',steps:['向人事确认申报单位的全称、单位类型，以及按该类型适用的税务或登记条件。','核对当前参保单位是否为本次申报单位；如有派遣、外包等经历，另外确认实际用工单位与申报主体。','确认后再填写“单位符合指南要求”和“当前在合格杭州单位参保”；没有确认的信息可留待补充。']},
  family_has_home:{title:'住房与其他优惠按政策家庭口径核对',intro:'家庭成员范围、住房认定和互斥优惠需要按原文确认，不能只凭本人名下无房作判断。',steps:['核对原文定义的申请家庭范围，再确认该家庭在杭州的住房情况。','整理已经领取或正在享受的住房、租房优惠名称，请受理系统确认是否互斥。','不清楚的选项保留“待确认”，补齐信息后重新核对。']}
};
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-field-help]');if(!button)return;
  const key=button.dataset.fieldHelp,h=fieldHelp[key];if(!h)return;
  const policy=state.policies.find(p=>p.status==='included'&&p.rules.some(r=>r.field===key));
  $('#field-help-content').innerHTML=`<h2>${esc(h.title)}</h2><p>${esc(h.intro)}</p><ol>${h.steps.map(t=>`<li>${esc(t)}</li>`).join('')}</ol>${policy?`<a class="btn" href="${esc(safeURL(policy.source_url))}" target="_blank" rel="noopener noreferrer">核对官方指南 ↗</a><p class="field-note">来源发布 ${esc(policy.published_on)} · ${esc(policy.legal_status)}</p>`:''}`;
  $('#field-help-dialog').showModal();
});

const reportStyles=`body{font:15px/1.8 "Microsoft YaHei","Segoe UI",sans-serif;color:#243b34;max-width:960px;margin:32px auto;padding:0 22px}h1{font-size:27px}h2{font-size:21px}h3{font-size:17px}.report-notice,.report-conflict{padding:14px;border:1px solid #b8c6b8;background:#f2f6ee}.report-conflict{border-color:#c1a06b;background:#fff6e5}section{margin:25px 0;border-bottom:1px solid #ccd6cc;padding-bottom:20px}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{text-align:left;vertical-align:top;border:1px solid #cbd5cb;padding:8px;overflow-wrap:anywhere}th{background:#f2f6ee}a{color:#184f42;overflow-wrap:anywhere}small{display:block;color:#52675b}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}summary{cursor:pointer;font-weight:600}li{margin:5px 0}@page{size:A4;margin:16mm}@media print{body{max-width:none;margin:0;padding:0;font-size:11pt}h1{font-size:20pt}h2{font-size:15pt}a{color:inherit}tr,.report-conflict{break-inside:avoid}h2,h3{break-after:avoid}.report-experiment{display:none}table{font-size:10pt}}`;

function exportSnapshot(){
  return {...state.report,application_preparation:window.applicationExportPreparation?.(state.report),sources:state.policies.map(p=>({id:p.id,source_url:p.source_url,published_on:p.published_on,checked_on:p.checked_on,legal_status:p.legal_status}))};
}

function reportMarkup(report){
  const labels={city:'城市',...Object.fromEntries([...$('#profile-form').elements].filter(e=>e.name).map(e=>[e.name,e.closest('label')?.firstChild?.textContent?.trim()||e.name])),...(state.reviewLabels||{})};
  const profileRows=Object.entries(report.profile).map(([key,value])=>`<tr><th>${esc(labels[key]||{city:'城市'}[key]||key)}</th><td>${esc(readableValue(value))}</td></tr>`).join('');
  const modelRuns=report.model_runs||[];
  const conflicts=Object.values(report.model_assessments||{}).filter(m=>m.audit?.status==='needs_review');
  return `<div class="report-document"><h1>惠才通 · 杭州人才政策核验报告</h1><p>核对参考日期：${esc(report.as_of)}<br>生成时间：${esc(new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}（北京时间）</p><div class="report-notice"><strong>初筛不是审批结论。</strong>仅核对已录入资料和条件，政策现行效力及完整资格仍需官方确认。生活补贴首笔、第二笔属于同一补贴，金额不重复累计。</div>${conflicts.length?`<p class="report-conflict"><strong>${conflicts.length} 项存在模型核验冲突。</strong>请先核对报告中的具体不满足项；实验模型输出不作为通过或办理建议。</p>`:''}<h2>一、核验结果与下一步</h2>${report.results.map(r=>{
    const d=r.display||{},b=d.benefit,blockers=d.blockers||[];
    const model=report.model_assessments?.[r.policy_id];
    return `<section><h3>${esc(r.title)} · ${esc(d.label||status[r.conclusion][0])}</h3><p>${esc(d.reason||r.reason)}</p><p><strong>${esc(b?.label||r.amount_label)}</strong><br>${esc(b?.basis||r.amount_note)}</p>${b?.standard_note&&b.standard_note!==b.basis?`<p>${esc(b.standard_note)}</p>`:''}<small>${esc(b?.notice||'按收录资料口径，获批金额需官方确认。')}</small>${d.preparation?.length?`<h4>现在可以准备</h4><ol>${d.preparation.map(t=>`<li>${esc(t)}</li>`).join('')}</ol>`:''}${blockers.length?`<h4>需要先核对的条件</h4><table><thead><tr><th>条件</th><th>当前状态</th><th>填写或计算值</th></tr></thead><tbody>${blockers.map(c=>{const shown=d.checks?.find(x=>x.field===c.field)||c;return `<tr><td>${esc(shown.label)}</td><td>${esc({fail:'不满足',unknown:'待确认',not_started:'尚未开始'}[shown.status]||shown.status)}</td><td>${esc(c.actual_label)}</td></tr>`;}).join('')}</tbody></table>`:r.conclusion==='eligible'?'<p>所列已录入条件已通过规则初筛，完整资格仍需官方确认。</p>':'<p>请按上方的资料效力或范围说明人工核验。</p>'}${model?.audit?.status==='needs_review'?`<div class="report-conflict"><strong>此事项存在实验模型冲突</strong><p>${esc(model.audit.next_action)}</p></div>`:''}${window.applicationQualificationReport?.(r,report)||''}<h4>准备信息</h4><ul>${r.materials.map(m=>`<li>${esc(m.label)}（${esc(m.kind)}）</li>`).join('')}</ul><p>清单仅表示需核对的信息，不表示这些材料已经上传或审核。</p><h4>办理渠道</h4><p>${esc(r.application_channel)}</p>${r.timeline?.length?`<h4>参考时间点</h4><ul>${r.timeline.map(t=>`<li>${esc(t.date)}：${esc(t.label)}</li>`).join('')}</ul><p>参保时间点按起算月连续有效缴费计算，不代表已经完成缴费；在读情形依赖预计毕业日期，毕业后须重新核对。</p>`:''}<p>来源：${esc(d.source?.source_org||'官方公开资料')} · 发布 ${esc(d.source?.published_on)} · 整理核对 ${esc(d.source?.checked_on)}<br>${esc(d.source?.legal_status||'现行效力待核验')}<br><a href="${esc(safeURL(r.source_url))}" target="_blank" rel="noopener noreferrer">查看官方指南</a></p></section>`;
  }).join('')}<h2>二、你的情况</h2><table><tbody>${profileRows}</tbody></table><h2>三、已确认的材料信息</h2>${report.material_confirmations?.length?report.material_confirmations.map(m=>`<p>${esc(m.filename)}：${m.fields.map(f=>esc(labels[f.field]||f.field)+' = '+esc(readableValue(f.value))).join('；')}<br><small>只记录用户确认的字段及对应来源，不验证材料真伪。</small></p>`).join(''):'<p>本次没有仍适用于当前资料的材料确认记录。</p>'}<h2>四、实验与追溯</h2><p>本报告包含 ${modelRuns.length} 次模型调用记录。规则初筛与实验模型分别保留；结构化对照不验证解释文字。</p>${modelRuns.length?`<details class="report-experiment"><summary>展开实验模型原始记录（打印时默认不展开；完整内容可另导出 JSON）</summary><pre>${esc(JSON.stringify(modelRuns,null,2))}</pre></details>`:''}<p>完整逐条规则核验记录可在应用中查看，或导出实验数据 JSON 留存。政策匹配表单不在服务端保存。</p></div>`;
}

function ensureFreshReport(){
  if(!state.report||state.dirty){toast('请先核对最新申请信息，再生成报告。',true);return false;}return true;
}
function refreshReadableReport(){if(state.report&&!$('#view-report').hidden)$('#readable-report').innerHTML=reportMarkup(state.report);}
function openReadableReport(){if(!ensureFreshReport())return;setView('report');refreshReadableReport();markProfileChanged();}
function downloadText(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('#print-report').addEventListener('click',()=>{if(ensureFreshReport()){refreshReadableReport();window.print();}});
$('#download-readable').addEventListener('click',()=>{
  if(!ensureFreshReport())return;
  const html=`<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>惠才通中文核验报告</title><style>${reportStyles}</style></head><body>${reportMarkup(state.report)}<p>可使用浏览器“打印”保存为 PDF。</p></body></html>`;
  downloadText('惠才通-中文核验报告-'+state.report.as_of+'.html',html,'text/html;charset=utf-8');toast('中文报告已生成；打开 HTML 可阅读或打印。');
});
$('#export-json').addEventListener('click',()=>{if(ensureFreshReport())download('惠才通-杭州政策核验-'+state.report.as_of+'.json',exportSnapshot());});
if(location.hash==='#report')$('#readable-report').innerHTML='<p>当前没有核验报告。请先返回政策匹配填写并核对资料，再生成中文报告。</p>';
markProfileChanged();
