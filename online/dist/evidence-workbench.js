'use strict';
let primaryRegistry=null,campaignPackets=null,campaignComparison=null;
let adjudicationUnsaved=false;
function sourceLink(doc,compact=false){return `<a href="${esc(safeURL(doc.url))}" target="_blank" rel="noopener noreferrer">${esc(compact?doc.title:'官方来源 ↗')}</a> · <a href="${esc(doc.local_url)}?v=a6f3b90eedd78575" target="_blank" rel="noopener noreferrer">本站原始文件</a>`;}
window.renderPrimarySources=function(){
  if(!primaryRegistry)return;
  $$('[data-policy-source]').forEach(box=>{
    const binding=primaryRegistry.bindings.find(b=>b.policy_id===box.dataset.policySource);if(!binding)return;
    const docMap=new Map(primaryRegistry.documents.map(d=>[d.id,d]));
    box.innerHTML=`<details><summary>本条复核的原始依据与覆盖缺口</summary><p>原文补核 ${esc(primaryRegistry.checked_on)}；自动规则快照 ${esc(primaryRegistry.rule_snapshot_date)}。请先阅读完整原文，再使用下方整理条款。</p><ul>${binding.direct_sources.map(id=>{const d=docMap.get(id);return `<li>${sourceLink(d,true)}<p class="field-note">${esc(d.verification_note)}</p></li>`;}).join('')}</ul><p class="field-note">条款定位：${esc([...new Set(binding.clause_links.map(c=>c.locator))].join('；'))}</p><ul class="field-note">${primaryRegistry.gaps.filter(g=>box.dataset.policySource.includes('rent')||!g.startsWith('租房')).map(g=>`<li>${esc(g)}</li>`).join('')}</ul></details>`;
  });
};
async function loadPrimaryEvidence(){
  primaryRegistry=await api('/api/sources');
  $('#primary-evidence-content').innerHTML=`<p>原文补核 ${esc(primaryRegistry.checked_on)} · 自动规则仍采用 ${esc(primaryRegistry.rule_snapshot_date)} 快照。</p><p>${esc(primaryRegistry.notice)}</p><div class="source-documents">${primaryRegistry.documents.map(d=>`<details><summary>${esc(d.title)} <small>· ${esc(d.kind)}</small></summary><p>${esc(d.publisher)} · 文件日期 ${esc(d.issued_on||'未标明')} · ${esc(d.status||'效力待核实')}</p><p>${esc(d.verification_note)}</p><p>${sourceLink(d)}</p><p class="source-hash">SHA-256：${esc(d.sha256)}</p>${d.effective_until?`<p>文本所载期限：${esc(d.effective_from)} 至 ${esc(d.effective_until)}</p>`:''}</details>`).join('')}</div><h3>尚待补齐与未编码条件</h3><ul>${primaryRegistry.gaps.map(g=>`<li>${esc(g)}</li>`).join('')}</ul><a class="btn btn-quiet small" href="/source-registry.json?v=a6f3b90eedd78575" download>下载原文目录与条款映射</a>`;
  window.renderPrimarySources();
}
loadPrimaryEvidence().catch(e=>{$('#primary-evidence-content').textContent='原文目录未载入：'+e.message+'。可刷新重试，已有填写保留。';});
api('/api/campaign').then(data=>{const a=data.audit;$('#campaign-audit').textContent=`${a.cases} 条候选 · ${a.blank_answers} 条答案留空 · ${a.unique_profiles} 组完整人物字段 · 与已收录开发记录完全重复 ${a.known_exact_overlaps.length} 条。${a.same_nondated_pattern_groups} 组存在日期不同、其余特征相同的模板组合，须整组保留给测试。尚未完成人工复核。`;}).catch(e=>{$('#campaign-audit').textContent='批次检查未完成：'+e.message;});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-campaign-download],[data-campaign-load]');if(!button)return;
  button.disabled=true;const slot=button.dataset.campaignDownload||button.dataset.campaignLoad;
  try{
    if(button.dataset.campaignLoad&&!reviewInitialized)throw new Error('原有复核进度仍在恢复，请稍后再载入任务。');
    const {packet}=await api('/api/campaign/assignment',{slot});
    if(button.dataset.campaignDownload){download('惠才通-54条空白任务-'+slot+'.json',packet);$('#campaign-message').textContent='已下载 '+slot+' 空白任务。请分别交给两位复核者，在各自浏览器通过“恢复复核草稿”载入。';}
    else{await restoreReviewFile(new File([JSON.stringify(packet)],'assignment-'+slot+'.json',{type:'application/json'}),false);$('#campaign-message').textContent=pendingReviewRestore?'已有填写存在冲突，请先处理下方恢复提示。':'已载入 '+slot+' 任务，工作台已切换到该批次。';}
  }catch(e){$('#campaign-message').textContent=e.message;}finally{button.disabled=false;}
});
$('#campaign-submit-form').addEventListener('submit',async event=>{
  event.preventDefault();stashReview();const button=event.submitter;button.disabled=true;
  try{const slot=$('#campaign-submit-slot').value;const {packet}=await api('/api/campaign/submit',{cases:state.reviewCases.filter(r=>r.campaign?.slot===slot),reviewer_id:$('#campaign-reviewer').value,independent_confirmed:$('#campaign-independent').checked});download('惠才通-54条正式提交-'+slot+'.json',packet);$('#campaign-message').textContent='已检查并下载 '+slot+' 正式提交，请交给第三位终审者。请另行下载全部草稿备份以保存其他填写。';}
  catch(e){$('#campaign-message').textContent='尚未提交：'+e.message;}finally{button.disabled=false;}
});
function invalidateComparison(){campaignPackets=null;campaignComparison=null;$('#campaign-decision-backup').disabled=true;$('#campaign-freeze-form').hidden=true;$('#campaign-comparison').replaceChildren();$('#campaign-comparison-status').textContent='提交文件已变更，请重新检查对照。';adjudicationUnsaved=false;}
for(const id of ['campaign-file-a','campaign-file-b'])$('#'+id).addEventListener('change',()=>{if(adjudicationUnsaved){$('#campaign-freeze-form').hidden=true;$('#campaign-comparison-status').textContent='文件已变更，当前填写仍对应旧提交。请先下载终审进度草稿，再重新检查对照。';}else invalidateComparison();});
$('#campaign-compare-form').addEventListener('submit',async event=>{
  event.preventDefault();const message=$('#campaign-comparison-status');if(adjudicationUnsaved){message.textContent='请先下载终审进度草稿，再重新对照提交，避免丢失填写。';return;}invalidateComparison();message.textContent='正在核对两份完整提交…';const button=event.submitter;button.disabled=true;
  try{
    const files=[$('#campaign-file-a').files[0],$('#campaign-file-b').files[0]];if(files.some(f=>!f||f.size>1_000_000))throw new Error('请选择两份不超过1MB的正式提交。');
    const [a,b]=await Promise.all(files.map(async f=>parseJSONInput(await f.text(),'正式提交')));const result=await api('/api/campaign/compare',{a,b});
    campaignPackets={a,b};campaignComparison=result;$('#campaign-decision-backup').disabled=false;const s=result.summary;message.textContent=`完整 ${s.cases} 条 · 结构完全一致 ${s.structured_agreements} 条 · 结论一致率 ${(s.conclusion_agreement*100).toFixed(1)}% · kappa ${s.cohen_kappa===null?'未定义（单一类别）':s.cohen_kappa.toFixed(3)}。这些是复核者一致性，不是模型准确率。`;
    $('#campaign-comparison').innerHTML=result.cases.map((r,i)=>`<details class="adjudication-case" data-adjudication-id="${esc(r.case_id)}"><summary>${esc(r.case_id)} · ${r.different_fields.length?'存在分歧：'+esc(r.different_fields.join('、')):'结构一致，仍需阅读解释'}</summary><pre>${esc(JSON.stringify(r.profile,null,2))}</pre><div class="review-pair"><div><h3>A · ${esc(result.reviewer_a)}</h3><pre>${esc(JSON.stringify(r.a,null,2))}</pre></div><div><h3>B · ${esc(result.reviewer_b)}</h3><pre>${esc(JSON.stringify(r.b,null,2))}</pre></div></div>${r.different_fields.length?`<label>终审采用<select data-adjudication-choice><option value="">请阅读原文后选择</option><option value="A">A 的标注</option><option value="B">B 的标注</option></select></label><label>终审理由（至少5字）<textarea data-adjudication-reason maxlength="3000" rows="3"></textarea></label>`:'<p class="field-note">默认保留 A 解释。若解释或结论有误，请退回初审者修订，再重新导入两份正式提交。</p>'}</details>`).join('');$('#campaign-freeze-form').hidden=false;
  }catch(e){message.textContent='未对照：'+e.message;}finally{button.disabled=false;}
});
$('#campaign-freeze-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{
    if(!campaignPackets)throw new Error('请先检查两份正式提交。');if(frozenUnsaved)throw new Error('请先下载当前冻结评测集，再冻结另一份。');
    const decisions=$$('[data-adjudication-id]').filter(box=>box.querySelector('[data-adjudication-choice]')).map(box=>({case_id:box.dataset.adjudicationId,choice:box.querySelector('[data-adjudication-choice]').value,reason:box.querySelector('[data-adjudication-reason]').value}));
    const {dataset}=await api('/api/campaign/freeze',{...campaignPackets,decisions,name:$('#campaign-dataset-name').value,dataset_id:$('#campaign-dataset-id').value,adjudicator_id:$('#campaign-adjudicator').value,source_checked:$('#campaign-final-source').checked,independence_confirmed:$('#campaign-final-independence').checked});showDataset(dataset,true);adjudicationUnsaved=false;$('#campaign-comparison-status').textContent='整批已冻结，包含双人初审、终审理由和原文目录。请在下方下载冻结集，再生成真实模型预测。';$('#benchmark-freeze-panel').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){$('#campaign-comparison-status').textContent='尚未冻结：'+e.message;}finally{button.disabled=false;}
});
function decisionDraft(){return {schema_version:1,type:'adjudication_draft',submission_a_sha256:campaignPackets.a.sha256,submission_b_sha256:campaignPackets.b.sha256,decisions:$$('[data-adjudication-id]').filter(box=>box.querySelector('[data-adjudication-choice]')).map(box=>({case_id:box.dataset.adjudicationId,choice:box.querySelector('[data-adjudication-choice]').value,reason:box.querySelector('[data-adjudication-reason]').value})),adjudicator_id:$('#campaign-adjudicator').value,name:$('#campaign-dataset-name').value,dataset_id:$('#campaign-dataset-id').value,notice:'仅为终审进度草稿，不是已冻结评测集。恢复后须重新核对并声明。'};}
$('#campaign-comparison').addEventListener('input',()=>{adjudicationUnsaved=true;$('#campaign-final-source').checked=false;});
$('#campaign-freeze-form').addEventListener('input',()=>{adjudicationUnsaved=true;});
$('#campaign-decision-backup').addEventListener('click',()=>{if(campaignPackets){download('惠才通-终审进度草稿.json',decisionDraft());adjudicationUnsaved=false;}});
$('#campaign-decision-file').addEventListener('change',async event=>{
  try{
    const file=event.target.files[0];if(!file)return;if(!campaignPackets)throw new Error('先导入 A/B 正式提交并检查对照，再恢复终审草稿。');if(adjudicationUnsaved)throw new Error('请先下载当前终审进度草稿，再恢复其他进度。');if(file.size>500000)throw new Error('终审草稿不超过500KB');
    const d=parseJSONInput(await file.text(),'终审草稿');if(d.type!=='adjudication_draft'||d.schema_version!==1||d.submission_a_sha256!==campaignPackets.a.sha256||d.submission_b_sha256!==campaignPackets.b.sha256)throw new Error('终审草稿与当前两份提交指纹不一致。');
    const boxes=new Map($$('[data-adjudication-id]').filter(b=>b.querySelector('[data-adjudication-choice]')).map(b=>[b.dataset.adjudicationId,b]));
    if(!Array.isArray(d.decisions)||new Set(d.decisions.map(r=>r.case_id)).size!==d.decisions.length||d.decisions.some(r=>!boxes.has(r.case_id)||!['','A','B'].includes(r.choice)||typeof r.reason!=='string'||r.reason.length>3000))throw new Error('终审草稿的编号、选择或理由无效。');
    if(['adjudicator_id','name','dataset_id'].some(k=>typeof d[k]!=='string'||d[k].length>120))throw new Error('终审草稿名称字段无效。');
    for(const box of boxes.values()){box.querySelector('[data-adjudication-choice]').value='';box.querySelector('[data-adjudication-reason]').value='';}
    for(const r of d.decisions){const box=boxes.get(r.case_id);box.querySelector('[data-adjudication-choice]').value=r.choice;box.querySelector('[data-adjudication-reason]').value=r.reason;}
    $('#campaign-adjudicator').value=d.adjudicator_id;$('#campaign-dataset-name').value=d.name;$('#campaign-dataset-id').value=d.dataset_id;$('#campaign-final-source').checked=false;$('#campaign-final-independence').checked=false;adjudicationUnsaved=false;$('#campaign-comparison-status').textContent='终审进度已恢复，未自动冻结，请重新核对并声明。';
  }catch(e){$('#campaign-comparison-status').textContent='未恢复：'+e.message;}finally{event.target.value='';}
});
window.addEventListener('beforeunload',event=>{if(adjudicationUnsaved){event.preventDefault();event.returnValue='';}});
