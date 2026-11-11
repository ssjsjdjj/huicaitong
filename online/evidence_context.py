"""Current retrieval coverage and date notices over UNCHANGED source snapshots.

Keep primary_evidence.search unchanged for reproducible v0.8.2 AI inputs. Short
clauses are explicitly identified by source ID + text, not by reserved cases.
"""
from collections import Counter
import math
import primary_evidence as primary

RENT='rent-platform-2026'
METHOD='primary-bm25-coverage-v2'
SHORT={32:'再次获得',34:'在职人员',36:'不得同时享受',54:'税务登记',56:'行政事业单位',58:'发证机关',62:'补贴续发',92:'本细则自2021年10月15日起施行'}
CORE=[48,50,68,32,34,40,92]
TOPICS=[
 ('insurance','连续参保与补缴',('社保','参保','补缴','断缴','连续','6个月','六个月'),[50,68]),
 ('prior_degree','既往领取后再获学历',('再获','再次','更高学历','新学历','又取得','学历升级','已享受','领取过','重复','重新申请'),[32]),
 ('employed_degree','在职取得学历',('在职','在岗'),[34]),
 ('housing','家庭、住房地域及交易历史',('住房','房产','家庭','配偶','未成年','无房','交易','赠与','继承'),[40]),
 ('benefit_overlap','其他住房优惠',('公租房','租房优惠','住房优惠','叠加','同时享受','同时领取'),[36,40]),
 ('employer','合格用人单位',('单位','企业','事业','税务','组织'),[54,56,58,50]),
 ('dispatch','派遣申报渠道',('派遣','人力资源'),[16,14]),
 ('timing','申请期限与日期认定',('期限','时限','毕业','何时','起算','申请日'),[68,70,72]),
 ('effective','正文自述施行日',('生效','施行','适用','效力','版本'),[92]),
 ('scope','申请条件覆盖',('申请条件','能否','符合','要求'),CORE),
]
NOTICE='发布日、正文自述施行日、页面取证日和来源核对日含义不同。没有完成效力及版本衔接核验，不能把命中片段或日期先后当作完整资格、申请日适用或当前有效的证明。'

def passage_id(line):return RENT+'-l'+str(line)
def short_passages(c):
    by_id={p['id']:p for p in c['passages']};result=set()
    for line,needle in SHORT.items():
        p=by_id.get(passage_id(line))
        if not p or p['document_id']!=RENT or needle not in p['text']:raise ValueError('关键短条款定位已变化，请重新核对原文；已停止补充检索')
        result.add(p['id'])
    return result

def document_time(doc,reference):
    reference=primary.reference_date(reference)
    capture='取证' in doc['temporal_basis']
    captured=doc['visible_from'] if capture else None
    declared=None;statement=None
    if doc['id']==RENT:
        p=next(p for p in primary.corpus()['passages'] if p['id']==passage_id(92))
        if SHORT[92] in p['text']:declared='2021-10-15';statement={'passage_id':p['id'],'quote':p['text']}
    warnings=[]
    if captured and captured>reference:warnings.append('页面取证晚于申请参考日，不能倒推当时页面状态或条款适用性。')
    if doc['issued_on'] and doc['issued_on']>reference:warnings.append('文件标明日期晚于申请参考日，不能作为当时已发布的依据。')
    if doc['role']=='historical_qa':warnings.append('这是历史问答，不代表当前完整政策。')
    if declared:warnings.append('正文自述自2021-10-15施行；同一页面另有后续补充，不能据此证明整篇内容从该日起均已适用。')
    warnings.append('适用效力及版本衔接尚未人工确认，不能据日期先后直接认定资格。')
    return {'document_id':doc['id'],'title':doc['title'],'reference_date':reference,'published_on':doc['issued_on'],'captured_on':captured,'source_checked_on':doc['checked_on'],'visible_from':doc['visible_from'],'temporal_basis':doc['temporal_basis'],'declared_effective_from':declared,'effective_statement':statement,'captured_after_reference':bool(captured and captured>reference),'effective_period_verified':False,'applicability':'unverified','warnings':warnings,'original_file_url':doc['local_url']}

def time_context(reference,document_ids):
    reference=primary.reference_date(reference);ids=set(document_ids)
    docs=[document_time(d,reference) for d in primary.corpus()['documents'] if d['id'] in ids]
    return {'reference_date':reference,'documents':docs,'applicability':'unverified','notice':NOTICE,'unbound_source':not docs}

def policy_time(policy_id,reference):
    ids=[RENT] if policy_id=='hz-rent-first-2026' else ['living-guide-2024'] if policy_id in {'hz-living-first-2024','hz-living-second-2024'} else []
    return time_context(reference,ids)

def catalogue():
    c=primary.corpus();extra=short_passages(c)
    return {**primary.catalogue(),'retrieval_method':METHOD,'additional_short_passages':len([p for p in c['passages'] if p['id'] in extra and not p['searchable']]),'total_searchable_passages':sum(p['searchable'] or p['id'] in extra for p in c['passages']),'time_notice':NOTICE}

def clause_evidence(clause_id):
    original=primary.clause_evidence(clause_id)
    lines={'rent-eligibility':[32,34,36,54,56,58],'rent-time':[50,68,70,72,92],'rent-channel':[14,16],'rent-standard':[8,76,62,64]}.get(clause_id,[])
    c=primary.corpus();short_passages(c);docs={d['id']:d for d in c['documents']}
    seen={p['id'] for p in original['results']};rows=list(original['results'])
    for line in lines:
        p=next(p for p in c['passages'] if p['id']==passage_id(line))
        if p['id'] not in seen:
            rows.append({**primary.result_for(p,docs[p['document_id']],''),'rank_origin':'coverage','retrieval_reason':'相关原文补充；不表示整理规则已覆盖或条款效力已确认','critical_short_clause':p['id'] in short_passages(c) and not p['searchable']});seen.add(p['id'])
    return {**original,'results':rows,'notice':original['notice']+' 本版另补充相关原文条件与短条款定位，不改变原始条款映射或冻结快照。'}

def search(query,as_of,include_history=False,limit=8,*,include_later_capture=False,document_id=None,coverage=None):
    q=primary.query_text(query);ref=primary.reference_date(as_of)
    if type(include_history) is not bool or type(include_later_capture) is not bool:raise ValueError('历史资料与晚取证开关须为布尔值')
    if type(limit) is not int or not 1<=limit<=12:raise ValueError('检索条数须为1—12的整数')
    c=primary.corpus();docs={d['id']:d for d in c['documents']};extra=short_passages(c)
    if document_id is not None and document_id not in docs:raise ValueError('原文来源编号无效')
    if coverage not in {None,'rent-review-core'}:raise ValueError('条款覆盖配置无效')
    rent_query=document_id==RENT or (any(t in q for t in ('租房','房租补贴','房补','租补')) and '生活补贴' not in q)
    def allowed(d):
        date_ok=d['visible_from']<=ref or (include_later_capture and '取证' in d['temporal_basis'])
        return date_ok and (include_history or d['role']!='historical_qa') and (not document_id or d['id']==document_id) and (not rent_query or d['id'].startswith('rent-'))
    eligible={i for i,d in docs.items() if allowed(d)}
    candidates=[p for p in c['passages'] if p['document_id'] in eligible and (p['searchable'] or p['id'] in extra)]
    terms={t for t in primary.tokenize(q) if len(t)>1 or len(q)==1}
    tokens=[primary.tokenize(p['text']) for p in candidates];freq=Counter(t for ts in tokens for t in set(ts));avg=sum(map(len,tokens))/len(tokens) if tokens else 1;n=len(candidates)
    hits={}
    for p,ts in zip(candidates,tokens):
        counts=Counter(ts);score=0
        for t in terms:
            tf=counts[t]
            if tf:score+=math.log(1+(n-freq[t]+.5)/(freq[t]+.5))*tf*2.2/(tf+1.2*(.25+.75*len(ts)/avg))
        if score>0:hits[p['id']]=(p,round(score+.15*len(terms&set(primary.tokenize(docs[p['document_id']]['title']))),4))
    topics=[t for t in TOPICS if rent_query and any(word in q for word in t[2])]
    lines=CORE if coverage=='rent-review-core' else [line for t in topics for line in t[3]]
    if rent_query and not lines and q:lines=[48,50,68,32,40,92]
    priority=list(dict.fromkeys(passage_id(line) for line in lines)) if q else []
    by_id={p['id']:p for p in candidates}
    for pid in priority:
        if pid in by_id and pid not in hits:hits[pid]=(by_id[pid],0.0)
    ranking=[pid for pid in priority if pid in hits]+[pid for pid,(p,score) in sorted(hits.items(),key=lambda item:(-item[1][1],item[0])) if pid not in priority]
    results=[]
    for pid in ranking[:limit]:
        p,score=hits[pid];d=docs[p['document_id']]
        reasons=['完整预审所需的基本条件与日期条款'] if coverage=='rent-review-core' and pid in priority else [t[1] for t in topics if pid in {passage_id(i) for i in t[3]}]
        results.append({**primary.result_for(p,d,q),'score':score,'retrieval_reason':'；'.join(reasons) or ('租房基本条件补充' if pid in priority else 'BM25词法匹配'),'rank_origin':'coverage' if pid in priority else 'bm25','critical_short_clause':pid in extra and not p['searchable'],'temporal':document_time(d,ref)})
    excluded=[]
    for d in docs.values():
        if d['id'] in eligible:continue
        reason='未在所选来源或政策家族内'
        if d['visible_from']>ref:reason='晚于参考日期；如为页面取证快照，须明确勾选“仅作线索”后才能查看'
        elif d['role']=='historical_qa' and not include_history:reason='历史问答默认隔离'
        excluded.append({'id':d['id'],'title':d['title'],'reason':reason})
    return {'query':q,'as_of':ref,'method':METHOD,'include_later_capture':include_later_capture,'corpus_sha256':c['sha256'],'source_registry_sha256':c['source_registry_sha256'],'results':results if q else [],'matching_passages':len(hits) if q else 0,'excluded_by_filter':excluded,'not_indexed':c['excluded_documents'],'coverage_topics':[{'id':t[0],'label':t[1]} for t in topics],'temporal_context':time_context(ref,[r['document_id'] for r in results]),'notice':'BM25词法检索与明确列出的主题条款补充；补充顺序不是可信概率或模型判断。短条款来自同一原始快照。'+NOTICE}
