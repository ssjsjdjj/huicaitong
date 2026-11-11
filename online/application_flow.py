"""Application-only guidance and user-declared supplementary checks.
Keep historical policy/RAW_FIELDS snapshots and benchmark labels unchanged.
"""
from datetime import date,datetime,timezone
import copy,hashlib,json,re
from core import RAW_FIELDS,BOOL_FIELDS,DATE_FIELDS,ENUMS,FIELD_LABELS,validate_profile,assess_all
from review import policy_hash
from guidance import QUESTIONS
from campaign_review import registry

INTENTS={'all':'全部收录事项','living-first':'生活补贴首笔','living-second':'生活补贴第二笔','rent':'租房补贴首笔'}
INTENT_IDS={'living-first':'hz-living-first-2024','living-second':'hz-living-second-2024','rent':'hz-rent-first-2026'}
EXTRA={
 'graduation_record_precision':{'label':'毕业记录上的日期精确到哪一层？','type':'select','options':[['day','明确到具体日期'],['month','只记载年月'],['unknown','尚未核对记录']],'safe':'day','help':'只记载年月时，需按原指南确认月末日期；不要随意填写某一天。','citation':'living-materials'},
 'has_dispatch_history':{'label':'当前或计入参保时长的经历中，有劳务派遣或人力资源单位经历吗？','type':'bool','safe':False,'help':'有此经历需另外核实实际用工单位和历史用工信息，准备状态不代表已经核实。','citation':'living-materials'},
 'family_scope_confirmed':{'label':'住房核验是否已包含申请人、配偶及未成年子女？','type':'bool','safe':True,'help':'只核对本人名下信息可能不完整；不需要在此填写家人姓名或证件号码。','citation':'rent-eligibility'},
 'housing_scope_confirmed':{'label':'是否已按用人单位所在区域核对家庭住房的地域范围？','type':'bool','safe':True,'help':'主城区等范围与西部区县口径有区别，住宅与非住宅均需按原文核对。','citation':'rent-eligibility'},
 'family_property_history':{'label':'按上述家庭与地域口径，是否存在房产交易历史？','type':'bool','safe':False,'help':'所存原文涉及买卖、赠与、继承等历史；存在或不清楚时转人工核验。','citation':'rent-eligibility'},
 'prior_rent_degree_subsidy':{'label':'是否曾享受应届大学生租房补贴后，又取得了本次学历？','type':'bool','safe':False,'help':'这与是否领取过当前首笔不同，需要结合完整原文核验。','citation':'rent-eligibility'},
}
PRIORITY=['degree','study_mode','school_region','nationality','graduation_date','first_installment_received','rent_first_received','family_has_home','other_housing_benefit','prior_other_degree_subsidy','degree_while_employed','employed_hangzhou','employer_qualified','insurance_current','insurance_start_date','insurance_months','insurance_without_backpay']
CHOICES={'degree':[['college','大专'],['bachelor','本科'],['master','硕士'],['phd','博士']],'study_mode':[['fulltime','全日制'],['parttime','非全日制']],'school_region':[['mainland','国内普通高校'],['overseas','国（境）外高校']],'nationality':[['cn','中国国籍'],['other','其他国籍']]}
PROGRESS={'not_started','ready','to_confirm'}
NOTICE='补充项来自已收录原文的覆盖缺口。填写或自填准备标记不验证真伪、不确认现行效力，也不构成完整资格或审批结论。'

def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def intent(value):
    if value not in INTENTS:raise ValueError('请选择有效的核对事项')
    return value
def selected(policies,which):
    which=intent(which)
    return [p for p in policies if p['status']=='included' and (which=='all' or p['id']==INTENT_IDS[which])]
def draft_profile(raw):
    """Partial drafts may contain cross-field contradictions; assessment validates them later."""
    if not isinstance(raw,dict) or set(raw)-RAW_FIELDS:raise ValueError('申请草稿包含未知字段，不能存入身份标识等信息')
    p={k:None if raw.get(k)=='' else raw.get(k) for k in sorted(RAW_FIELDS)};p['city']='杭州' if raw.get('city') in (None,'') else raw['city']
    if p['city']!='杭州':raise ValueError('当前仅支持杭州')
    for k,v in p.items():
        if v is None:continue
        if k in BOOL_FIELDS and type(v) is not bool:raise ValueError(FIELD_LABELS[k]+'须为是、否或待确认')
        if k in ENUMS and (not isinstance(v,str) or v not in ENUMS[k]):raise ValueError('无效的'+FIELD_LABELS[k])
        if k in DATE_FIELDS:
            try:
                if not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v):raise ValueError()
                date.fromisoformat(v)
            except (ValueError,TypeError):raise ValueError(FIELD_LABELS[k]+'日期无效') from None
        if k=='insurance_months' and (type(v) is not int or not 0<=v<=600):raise ValueError('连续参保月数须为0—600的整数')
    return p
def extras(raw):
    if not isinstance(raw,dict) or set(raw)-set(EXTRA):raise ValueError('补充核验信息含未知字段')
    result={}
    for k,d in EXTRA.items():
        v=raw.get(k);v=None if v=='' else v
        if d['type']=='bool' and v is not None and type(v) is not bool:raise ValueError(d['label']+'须为是、否或待确认')
        if d['type']=='select' and v is not None and (not isinstance(v,str) or v not in {o[0] for o in d['options']}):raise ValueError('毕业日期精度选项无效')
        result[k]=v
    return result
def bindings(policies,which):return {p['id']:policy_hash(p) for p in selected(policies,which)}
def context(profile,supplementary,which,policies):return digest({'profile':draft_profile(profile),'supplementary':extras(supplementary),'intent':intent(which),'policies':bindings(policies,which),'source_registry_sha256':registry()['sha256']})
def extra_keys(policy):
    common=['graduation_record_precision','has_dispatch_history']
    return common+(['family_scope_confirmed','housing_scope_confirmed','family_property_history','prior_rent_degree_subsidy'] if policy['family']=='hz-rent' else [])
def question(key):
    if key.startswith('extra.'):
        field=key[6:]
        if field not in EXTRA:raise ValueError('补充问题编号无效')
        return {'key':key,'field':field,'group':'supplementary',**{k:v for k,v in EXTRA[field].items() if k!='safe'}}
    if key not in RAW_FIELDS-{'city'}:raise ValueError('问题编号无效')
    type_='bool' if key in BOOL_FIELDS else 'select' if key in ENUMS else 'month' if key=='insurance_start_date' else 'date' if key in DATE_FIELDS else 'number'
    return {'key':key,'field':key,'group':'profile','label':FIELD_LABELS[key],'type':type_,'options':CHOICES.get(key,[]),'help':QUESTIONS.get(key,'不确定可选择“暂不清楚”，之后仍需补充。')}
def assess(body,policies):
    p=validate_profile(body.get('profile'));e=extras(body.get('supplementary',{}));which=intent(body.get('intent','all'));ps=selected(policies,which)
    if not ps:raise ValueError('当前没有可核对的所选事项')
    report=assess_all(ps,p);catalogue={x['id']:x for x in ps}
    for row in report['results']:
        policy=catalogue[row['policy_id']];checks=[];out=any(c['kind']=='scope' and c['status']=='unknown' and c['actual'] is not None for c in row['checks'])
        blocked=row['conclusion']=='ineligible' and not row['display'].get('planning')
        if out:stage='outside_scope'
        elif row['display'].get('planning'):stage='planning'
        elif blocked:stage='base_blocked'
        else:
            for k in extra_keys(policy):
                d=EXTRA[k];v=e[k];citation=d['citation'] if policy['family']!='hz-rent' or d['citation'].startswith('rent') else 'rent-time' if k=='graduation_record_precision' else 'rent-channel'
                checks.append({'key':'extra.'+k,'label':d['label'],'state':'pending' if v is None else 'confirmed' if v==d['safe'] else 'manual','value':v,'help':d['help'],'citation':citation})
            if policy['family']=='hz-rent':
                for k,safe in [('study_mode','fulltime'),('employer_qualified',True),('insurance_current',True),('insurance_without_backpay',True),('degree_while_employed',False)]:
                    v=p.get(k);checks.append({'key':k,'label':FIELD_LABELS[k],'state':'pending' if v is None else 'confirmed' if v==safe else 'manual','value':v,'help':'结合租房原文核对本项，不能只依据简化规则。','citation':'rent-eligibility' if k!='insurance_without_backpay' else 'rent-time'})
            stage='manual' if any(c['state']=='manual' for c in checks) else 'pending' if any(c['state']=='pending' for c in checks) else 'recorded'
            if policy['family'] not in {'hz-living','hz-rent'}:stage='manual'
        for c in checks:
            value=c['value'];key=c['key'].removeprefix('extra.')
            choices=EXTRA.get(key,{}).get('options',CHOICES.get(key,[]))
            c['value_label']='待确认' if value is None else '是' if value is True else '否' if value is False else dict(choices).get(value,str(value))
        row['qualification_review']={'status':stage,'checks':checks,'notice':NOTICE,'source_registry_sha256':registry()['sha256']}
        if stage in {'pending','manual'} and row['conclusion']=='eligible':
            row['display']['label']='所列条件满足，补充资格待核验' if stage=='pending' else '补充资格需人工核验'
            row['display']['reason']='原有规则的已录入条件已满足；请先核对下方补充项，再向受理系统确认完整资格。'
    sha=context(p,e,which,policies);items=[]
    for row in report['results']:
        if row['qualification_review']['status']=='base_blocked':continue
        for m in row['materials']:
            items.append({'id':row['policy_id']+'/'+m['id'],'policy_id':row['policy_id'],'policy_title':row['title'],'label':m['label'],'kind':m['kind'],'citation':m['citation']})
    report['application']={'schema_version':1,'intent':which,'supplementary':e,'context_sha256':sha,'preparation_items':items,'notice':NOTICE}
    return report
def guide(body,policies):
    report=assess(body,policies);p=report['profile'];e=report['application']['supplementary'];deferred=body.get('deferred',[])
    if not isinstance(deferred,list) or len(deferred)>50 or any(not isinstance(k,str) for k in deferred) or len(set(deferred))!=len(deferred):raise ValueError('暂不清楚的问题记录无效')
    for key in deferred:question(key)
    pending=set()
    for r in report['results']:
        stage=r['qualification_review']['status']
        if stage in {'outside_scope','planning','base_blocked'}:continue
        pending.update(r['missing_fields']);pending.update(c['key'] for c in r['qualification_review']['checks'] if c['state']=='pending')
    priority=PRIORITY+['extra.'+k for k in EXTRA]
    ordered=[k for k in priority if k in pending]+[k for k in sorted(pending) if k not in priority]
    focus=body.get('focus_question')
    if focus is not None and (not isinstance(focus,str) or len(focus)>120):raise ValueError('问题编号无效')
    key=focus or next((k for k in ordered if k not in deferred),None)
    q=question(key) if key else None
    if q:q['value']=e.get(q['field']) if q['group']=='supplementary' else p.get(q['field'])
    return {'question':q,'pending_keys':ordered,'deferred':deferred,'remaining':len(ordered),'deferred_count':sum(k in deferred for k in ordered),'results':[{'policy_id':r['policy_id'],'title':r['title'],'label':r['display'].get('label') or {'eligible':'所列条件满足','ineligible':'存在不满足项','insufficient':'信息待核验'}[r['conclusion']],'qualification_status':r['qualification_review']['status']} for r in report['results']],'notice':NOTICE}
def timestamp(v):
    try:
        if datetime.fromisoformat(v.replace('Z','+00:00')).tzinfo is None:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ValueError('草稿时间无效') from None
    return v
def progress(raw,expected_context,allowed,stale=False):
    if not isinstance(raw,dict) or set(raw)-{'context_sha256','items'}:raise ValueError('准备进度格式无效')
    items=raw.get('items',{})
    if not isinstance(items,dict) or len(items)>100:raise ValueError('准备进度条数无效')
    if any(not isinstance(k,str) or len(k)>180 or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',k) or not isinstance(v,str) or v not in PROGRESS for k,v in items.items()):raise ValueError('准备状态或条目编号无效')
    if stale or raw.get('context_sha256')!=expected_context:return {'context_sha256':expected_context,'items':{}}
    if set(items)-allowed:raise ValueError('准备清单包含不属于当前事项的条目')
    return {'context_sha256':expected_context,'items':items.copy()}
def packet(body,policies):
    p=draft_profile(body.get('profile'));e=extras(body.get('supplementary',{}));which=intent(body.get('intent','all'));deferred=body.get('deferred',[])
    if not isinstance(deferred,list) or len(deferred)>50 or any(not isinstance(k,str) for k in deferred) or len(set(deferred))!=len(deferred):raise ValueError('暂不清楚的问题记录无效')
    for key in deferred:question(key)
    sha=context(p,e,which,policies);allowed={x['id']+'/'+m['id'] for x in selected(policies,which) for m in x['materials']}
    result={'schema_version':1,'type':'huicaitong_application_draft','saved_at':timestamp(body.get('saved_at') or datetime.now(timezone.utc).isoformat()),'profile':p,'supplementary':e,'intent':which,'deferred':deferred,'preparation':progress(body.get('preparation',{}),sha,allowed),'policy_bindings':bindings(policies,which),'source_registry_sha256':registry()['sha256'],'notice':'自填申请草稿；不含原始材料、材料真伪核验或审批结果。恢复后请重新核对；准备标记不代表已提交或获批。'}
    result['sha256']=digest(result);return result
def restore(value,policies):
    if not isinstance(value,dict) or value.get('schema_version')!=1 or value.get('type')!='huicaitong_application_draft':raise ValueError('请选择惠才通申请草稿，不是人工评测或政策导入文件')
    allowed={'schema_version','type','saved_at','profile','supplementary','intent','deferred','preparation','policy_bindings','source_registry_sha256','notice','sha256'}
    if set(value)!=allowed or value.get('sha256')!=digest({k:v for k,v in value.items() if k!='sha256'}):raise ValueError('申请草稿指纹或字段不匹配，原填写未改变')
    stale=value['policy_bindings']!=bindings(policies,value['intent']) or value['source_registry_sha256']!=registry()['sha256']
    normalized=packet(value,policies)
    if stale:
        normalized['preparation']['items']={};normalized['sha256']=digest({k:v for k,v in normalized.items() if k!='sha256'})
    return {'packet':normalized,'stale':stale,'notice':'政策或原文版本已变化，已保留填写信息，准备状态需重新核对。' if stale else '填写进度已恢复，请重新核对后查看结果；原始材料和材料确认记录未恢复。'}
