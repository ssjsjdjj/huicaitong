"""Lexical retrieval over versioned primary-source text; no model or eligibility claim."""
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path
import hashlib,json,math,re
from rag import tokenize

ROOT=Path(__file__).resolve().parent
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
@lru_cache(maxsize=1)
def corpus():
    data=json.loads((ROOT/'data/primary-corpus.json').read_text(encoding='utf-8'))
    if data.get('sha256')!=digest({k:v for k,v in data.items() if k!='sha256'}):raise ValueError('原文检索库指纹不匹配，已停止检索')
    return data
def query_text(value):
    if not isinstance(value,str) or len(value)>4000:raise ValueError('检索问题须为不超过4000字的文本')
    return value.strip()
def reference_date(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('检索参考日期须为 YYYY-MM-DD')
    date.fromisoformat(value);return value
def highlight(text,query):
    """Return plain-text parts. The browser escapes all parts before adding <mark>."""
    q=query_text(query);terms=sorted({t for t in tokenize(q) if len(t)>1 or len(q)==1},key=lambda t:(-len(t),t))[:160]
    if not terms:return [{'text':text,'matched':False}]
    pattern=re.compile('|'.join(re.escape(t) for t in terms),re.I);parts=[];start=0
    for m in pattern.finditer(text):
        if m.start()>start:parts.append({'text':text[start:m.start()],'matched':False})
        parts.append({'text':m.group(),'matched':True});start=m.end()
    if start<len(text):parts.append({'text':text[start:],'matched':False})
    return parts or [{'text':text,'matched':False}]
def catalogue():
    c=corpus()
    return {'corpus_id':c['corpus_id'],'sha256':c['sha256'],'source_registry_sha256':c['source_registry_sha256'],'checked_on':c['sources_checked_on'],'indexed_documents':len(c['documents']),'searchable_passages':sum(p['searchable'] for p in c['passages']),'documents':[{k:v for k,v in d.items() if k!='pages'} for d in c['documents']],'excluded_documents':c['excluded_documents'],'notice':c['notice']}
def result_for(p,doc,q):
    parts=highlight(p['text'],q);offset=0
    for part in parts:
        if part['matched']:break
        offset+=len(part['text'])
    start=max(0,min(offset,len(p['text']))-55) if any(part['matched'] for part in parts) else 0;end=min(len(p['text']),start+280)
    return {**p,'document_title':doc['title'],'publisher':doc['publisher'],'issued_on':doc['issued_on'],'checked_on':doc['checked_on'],'role':doc['role'],'temporal_basis':doc['temporal_basis'],'visible_from':doc['visible_from'],'official_url':doc['url'],'original_file_url':doc['local_url']+('#page='+str(p['page']) if p['page'] else ''),'source_sha256':doc['source_sha256'],'parts':parts,'snippet_parts':highlight(p['text'][start:end],q),'snippet_before':start>0,'snippet_after':end<len(p['text'])}
def search(query,as_of,include_history=False,limit=8):
    q=query_text(query);as_of=reference_date(as_of)
    if type(include_history) is not bool:raise ValueError('历史资料开关须为布尔值')
    if type(limit) is not int or not 1<=limit<=12:raise ValueError('检索条数须为1—12的整数')
    c=corpus();docs={d['id']:d for d in c['documents']};eligible={d['id'] for d in docs.values() if d['visible_from']<=as_of and (include_history or d['role']!='historical_qa')}
    candidates=[p for p in c['passages'] if p['searchable'] and p['document_id'] in eligible]
    terms={t for t in tokenize(q) if len(t)>1 or len(q)==1};token_lists=[tokenize(p['text']) for p in candidates]
    freq=Counter(t for ts in token_lists for t in set(ts));avg=sum(map(len,token_lists))/len(token_lists) if token_lists else 1;n=len(candidates);hits=[]
    for p,ts in zip(candidates,token_lists):
        counts=Counter(ts);score=0
        for t in terms:
            tf=counts[t]
            if tf:score+=math.log(1+(n-freq[t]+.5)/(freq[t]+.5))*tf*2.2/(tf+1.2*(.25+.75*len(ts)/avg))
        # A title alone never turns an unrelated page into a hit.
        if score>0:
            doc=docs[p['document_id']];title_terms=set(tokenize(doc['title']))
            score+=.15*len(terms&title_terms)
            hits.append({**result_for(p,doc,q),'score':round(score,4)})
    hits.sort(key=lambda p:(-p['score'],p['id']))
    excluded=[{'id':d['id'],'title':d['title'],'reason':'晚于参考日期（平台快照按取证日期隔离）' if d['visible_from']>as_of else '历史问答默认隔离'} for d in docs.values() if d['id'] not in eligible]
    return {'query':q,'as_of':as_of,'method':'primary-bm25-v1','corpus_sha256':c['sha256'],'source_registry_sha256':c['source_registry_sha256'],'results':hits[:limit] if q else [],'matching_passages':len(hits),'excluded_by_filter':excluded,'not_indexed':c['excluded_documents'],'notice':c['notice']}
def passage(passage_id,query=''):
    c=corpus();p=next((p for p in c['passages'] if p['id']==passage_id),None)
    if p is None:raise ValueError('未找到该原文片段，请重新检索当前版本')
    doc=next(d for d in c['documents'] if d['id']==p['document_id']);page=next(pg for pg in doc['pages'] if pg['page']==p['page'])
    nearby=c['passages'];i=next(i for i,x in enumerate(nearby) if x['id']==passage_id)
    adjacent=[x for x in nearby[max(0,i-1):i+2] if x['document_id']==doc['id'] and x['id']!=p['id']]
    return {'passage':result_for(p,doc,query),'context_parts':highlight(page['text'],query),'context_locator':('PDF第'+str(p['page'])+'页' if p['page'] else '已取证页面完整可见正文'),'adjacent':[{'id':x['id'],'locator':x['locator']} for x in adjacent],'corpus_sha256':c['sha256'],'notice':doc['verification_note']+' '+c['notice']}
def clause_evidence(clause_id):
    c=corpus();ids=c['clause_anchors'].get(clause_id,[]);docs={d['id']:d for d in c['documents']}
    return {'clause_id':clause_id,'results':[result_for(p,docs[p['document_id']],'') for p in c['passages'] if p['id'] in ids],'notice':'定位到原始文件的相关页或段落；整理条款仍需人工逐项核对，不能据此认定现行资格。'}
