'use strict';
// This renderer displays evidence dates. It never decides eligibility or effect.
window.sourceTimeMarkup=function(t,title='政策适用时间待核验'){
  if(!t)return '';
  const later=t.documents?.some(d=>d.captured_after_reference);
  return `<section class="source-time-notice"><strong>${esc(title)}</strong><p>申请／检索参考日 ${esc(t.reference_date)}。${later?'有页面快照取证晚于参考日，只能作为补充线索。':''}${t.unbound_source?'当前上下文没有可核对日期的原文；来源可能尚未绑定，或被日期范围排除。':'发布或取证在先，也不等于已确认该日适用。'}</p><details><summary>区分发布、取证与正文自述施行日期</summary>${(t.documents||[]).map(d=>`<article><h4>${esc(d.title)}</h4><dl><div><dt>文件发布日期</dt><dd>${esc(d.published_on||'页面未标明')}</dd></div><div><dt>页面取证日期</dt><dd>${esc(d.captured_on||'非动态页面取证口径')}</dd></div><div><dt>来源核对日期</dt><dd>${esc(d.source_checked_on)}</dd></div><div><dt>正文自述施行日</dt><dd>${esc(d.declared_effective_from||'未单独确认')}</dd></div><div><dt>参考日适用效力</dt><dd>尚未确认</dd></div></dl><ul>${d.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>${d.effective_statement?`<blockquote>${esc(d.effective_statement.quote)}</blockquote>`:''}<a href="${esc(safeURL(new URL(d.original_file_url,location.href).href))}" target="_blank" rel="noopener">核对原始文件及完整版本</a></article>`).join('')}<p>${esc(t.notice)}</p></details></section>`;
};
