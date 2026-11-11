"""Two independent reviewer declarations, reconciliation and auditable freezing.
Fingerprints detect edits; they are not identity authentication or quality certification.
"""
import copy,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from human_evaluation import digest,profile_hash,restore_rows,known_profiles,freeze_dataset
from review import reviewed_tasks

ROOT=Path(__file__).resolve().parent
FIELDS=('conclusion','evidence_ids','missing_fields','materials')
def read(name):return json.loads((ROOT/'data'/name).read_text(encoding='utf-8'))
def signed(value):
    result=copy.deepcopy(value);result['sha256']=digest(result);return result
def json_browser_numbers(value):
    """JSON.stringify emits 1 for 1.0. Normalize new protocol rates before hashing.
    Do not change the historical dataset hashing algorithm or policy snapshots.
    """
    if isinstance(value,float) and value.is_integer():return int(value)
    if isinstance(value,list):return [json_browser_numbers(v) for v in value]
    if isinstance(value,dict):return {k:json_browser_numbers(v) for k,v in value.items()}
    return value
def verify(value,label):
    if not isinstance(value,dict) or value.get('sha256')!=digest({k:v for k,v in value.items() if k!='sha256'}):raise ValueError(label+'指纹不匹配')
    return value
def registry():return verify(read('source-registry.json'),'原文目录')
def campaign():return verify(read('review-campaign.json'),'候选批次')
def identity(value,label):
    if not isinstance(value,str) or not 1<=len(value.strip())<=80:raise ValueError('请填写'+label+'标识（1—80字）')
    return value.strip()
def stamp(value):
    try:
        if datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is None:raise ValueError()
    except (TypeError,ValueError,AttributeError):raise ValueError('时间须为带时区的 ISO 时间') from None
    return value
def assignment(slot):
    if slot not in {'A','B'}:raise ValueError('请选择复核者 A 或 B')
    batch=campaign();rows=copy.deepcopy(batch['cases'])
    for row in rows:
        row['campaign'].update(candidate_case_id=row['case_id'],slot=slot,batch_sha256=batch['sha256'])
        row['case_id']+='.'+slot.lower()
    return {'schema_version':1,'assignment_slot':slot,'batch_id':batch['batch_id'],'batch_sha256':batch['sha256'],'source_registry_sha256':batch['source_registry_sha256'],'cases':rows,'notice':'答案留空。独立阅读原文后标注，不查看另一位复核者、规则或模型答案；两份表的编号后缀用于隔离进度，不增加样本量。'}
def validate_assignment_rows(rows,policies,complete=False):
    if not isinstance(rows,list) or not rows:raise ValueError('未找到本批复核记录')
    slots={r.get('campaign',{}).get('slot') for r in rows}
    if len(slots)!=1 or not slots<={'A','B'}:raise ValueError('一次只接受同一份 A 或 B 任务，不能混合')
    slot=next(iter(slots));templates={r['case_id']:r for r in assignment(slot)['cases']}
    if complete and len(rows)!=len(templates):raise ValueError('必须完成本批全部54条，不能用已确认子集替代整批')
    seen=set()
    for r in rows:
        t=templates.get(r.get('case_id'))
        if not t or r['case_id'] in seen:raise ValueError('批次案例编号无效或重复')
        seen.add(r['case_id'])
        if any(r.get(k)!=t[k] for k in ('policy_id','source_policy_sha256','campaign','provenance')) or profile_hash(r.get('profile'))!=profile_hash(t['profile']):raise ValueError('批次人物、政策、来源或任务指纹已改变，请保留原文件并重新分发任务')
    if complete:
        reviewed_tasks(rows,policies)
        if any(r['review'].get('source_checked') is not True for r in rows):raise ValueError('每条须确认已阅读原文')
    return slot
def submission(body,policies):
    rows=restore_rows(body.get('cases'),policies);slot=validate_assignment_rows(rows,policies,True)
    who=identity(body.get('reviewer_id'),'复核者')
    if any(r['review']['reviewer'].strip().casefold()!=who.casefold() for r in rows):raise ValueError('整批记录的复核者标识须与提交标识一致')
    if body.get('independent_confirmed') is not True:raise ValueError('请声明未参考另一复核者、规则或模型答案，且本批未参与开发')
    batch=campaign()
    return signed({'schema_version':1,'type':'independent_review_submission','slot':slot,'reviewer_id':who,'submitted_at':stamp(body.get('submitted_at') or datetime.now(timezone.utc).isoformat()),'batch_sha256':batch['sha256'],'source_registry_sha256':batch['source_registry_sha256'],'independent_declared':True,'cases':rows,'notice':'复核者身份与独立性均为提交者声明；本站不提供身份认证或远程协作。'})
def validate_submission(packet,policies):
    verify(packet,'复核提交')
    if packet.get('type')!='independent_review_submission' or packet.get('schema_version')!=1:raise ValueError('这不是正式双人复核提交，请先在任务区检查并导出')
    expected=submission({'cases':packet.get('cases'),'reviewer_id':packet.get('reviewer_id'),'independent_confirmed':packet.get('independent_declared'),'submitted_at':packet.get('submitted_at')},policies)
    if packet!=expected:raise ValueError('复核提交元数据与当前任务不一致')
    return packet
def normalized(row):
    e=row['expected'];return {k:sorted(e[k]) if isinstance(e[k],list) else e[k] for k in FIELDS}
def compare(body,policies):
    a=validate_submission(body.get('a'),policies);b=validate_submission(body.get('b'),policies)
    if a['slot']!='A' or b['slot']!='B':raise ValueError('请分别导入 A 提交和 B 提交，不能交换或重复')
    if a['reviewer_id'].casefold()==b['reviewer_id'].casefold():raise ValueError('A 与 B 复核者标识必须不同')
    am={r['campaign']['candidate_case_id']:r for r in a['cases']};bm={r['campaign']['candidate_case_id']:r for r in b['cases']}
    comparisons=[];ca=Counter();cb=Counter();conclusion_agree=0
    for t in campaign()['cases']:
        id=t['case_id'];ar=am[id];br=bm[id];na=normalized(ar);nb=normalized(br)
        differences=[k for k in FIELDS if na[k]!=nb[k]]
        ca[na['conclusion']]+=1;cb[nb['conclusion']]+=1;conclusion_agree+=na['conclusion']==nb['conclusion']
        comparisons.append({'case_id':id,'policy_id':t['policy_id'],'profile':t['profile'],'a':ar['expected'],'b':br['expected'],'different_fields':differences,'explanation_review_required':True})
    n=len(comparisons);po=conclusion_agree/n;pe=sum(ca[k]*cb[k] for k in set(ca)|set(cb))/(n*n)
    return {'batch_id':campaign()['batch_id'],'cases':comparisons,'reviewer_a':a['reviewer_id'],'reviewer_b':b['reviewer_id'],'summary':{'cases':n,'structured_agreements':sum(not r['different_fields'] for r in comparisons),'conclusion_agreement':po,'cohen_kappa':(po-pe)/(1-pe) if pe<1 else None,'notice':'一致率及kappa只描述两位复核者的一致性，不是模型准确率；解释即使结构一致也需第三人阅读。'}}
def reconcile(body,policies):
    report=compare(body,policies);adjudicator=identity(body.get('adjudicator_id'),'终审者')
    if adjudicator.casefold() in {report['reviewer_a'].casefold(),report['reviewer_b'].casefold()}:raise ValueError('终审者标识须与两位初审者不同')
    if body.get('source_checked') is not True:raise ValueError('请确认终审已核对原文及全部解释')
    if body.get('independence_confirmed') is not True:raise ValueError('请确认本批及近重复未参与训练、提示词修改或模型选择')
    decisions=body.get('decisions',[])
    if not isinstance(decisions,list) or any(not isinstance(d,dict) for d in decisions):raise ValueError('分歧处理格式无效')
    dm={d.get('case_id'):d for d in decisions};ids={r['case_id'] for r in report['cases']}
    if len(dm)!=len(decisions) or set(dm)-ids:raise ValueError('终审记录编号重复或未知')
    now=stamp(body.get('frozen_at') or datetime.now(timezone.utc).isoformat());rows=copy.deepcopy(campaign()['cases']);audit=[]
    for row,result in zip(rows,report['cases']):
        decision=dm.get(row['case_id']);different=bool(result['different_fields'])
        if different and (not decision or decision.get('choice') not in {'A','B'} or not isinstance(decision.get('reason'),str) or not 5<=len(decision['reason'].strip())<=3000):raise ValueError('分歧尚未处理：'+row['case_id']+'；需选择 A/B 并填写至少5字依据。两人均有误时应退回修订重交。')
        if decision and (decision.get('choice') not in {'A','B'} or not isinstance(decision.get('reason',''),str) or len(decision.get('reason',''))>3000):raise ValueError('终审选择或理由无效')
        choice=decision['choice'] if decision else 'A'
        row.pop('campaign');row['expected']=copy.deepcopy(result[choice.lower()]);row['review']={'status':'reviewed','reviewer':adjudicator,'reviewed_at':now,'source_checked':True}
        audit.append({'case_id':row['case_id'],'choice':choice,'reason':decision.get('reason','结构一致，终审者已核对两份解释') if decision else '结构一致，终审者已核对两份解释'})
    batch=campaign()
    dataset=freeze_dataset({'cases':rows,'name':body.get('name'),'dataset_id':body.get('dataset_id'),'purpose':'test','independence_confirmed':True,'frozen_at':now},policies,_campaign_authorized=True)
    dataset.pop('sha256');dataset['review_protocol']={'version':2,'kind':'two_independent_reviewers_plus_adjudicator','batch_sha256':batch['sha256'],'source_registry_sha256':batch['source_registry_sha256'],'adjudicator_id':adjudicator,'reviewer_a':report['reviewer_a'],'reviewer_b':report['reviewer_b'],'submission_a':body['a'],'submission_b':body['b'],'decisions':audit,'agreement':report['summary'],'notice':'身份和独立性为人工声明；候选案例由项目编写，尚无外部认证。'}
    dataset['source_registry']=registry();dataset=json_browser_numbers(dataset);dataset['sha256']=digest(dataset)
    return dataset
def audit_candidates():
    batch=campaign();known=set(known_profiles().get('profile_sha256',[]));rows=batch['cases'];groups=Counter()
    for row in rows:
        p={k:v for k,v in row['profile'].items() if k not in {'application_date','graduation_date','insurance_start_date'}};groups[digest(p)]+=1
    return {'cases':len(rows),'blank_answers':sum(r.get('expected') is None and r['review']['status']=='pending' for r in rows),'unique_profiles':len({profile_hash(r['profile']) for r in rows}),'known_exact_overlaps':[r['case_id'] for r in rows if profile_hash(r['profile']) in known],'same_nondated_pattern_groups':sum(n>1 for n in groups.values()),'policy_tasks':dict(Counter(r['policy_id'] for r in rows)),'notice':'日期不同但其余特征相同的组合已单列；这些近重复须整批隔离于开发，不能把54条等同于54种独立政策或真实用户。'}

def verify_protocol(dataset,policies):
    """Verify a frozen audit with its own snapshots, not today's registry."""
    p=dataset['review_protocol'];reg=verify(dataset.get('source_registry'),'冻结原文目录')
    if p.get('kind')!='two_independent_reviewers_plus_adjudicator' or p.get('version')!=2 or p.get('source_registry_sha256')!=reg['sha256']:raise ValueError('冻结复核流程或原文绑定无效')
    a=verify(p.get('submission_a'),'A提交');b=verify(p.get('submission_b'),'B提交')
    people=[identity(p.get(k),'复核者') for k in ('reviewer_a','reviewer_b','adjudicator_id')]
    if len({x.casefold() for x in people})!=3:raise ValueError('冻结流程需要三位不同标识的复核者')
    if a.get('slot')!='A' or b.get('slot')!='B' or a.get('reviewer_id')!=people[0] or b.get('reviewer_id')!=people[1]:raise ValueError('冻结复核者不匹配')
    for packet in (a,b):
        if packet.get('source_registry_sha256')!=reg['sha256'] or packet.get('batch_sha256')!=p.get('batch_sha256') or packet.get('independent_declared') is not True:raise ValueError('冻结提交批次或原文指纹不匹配')
        reviewed_tasks(packet.get('cases'),policies)
    maps=[{r.get('campaign',{}).get('candidate_case_id'):r for r in s['cases']} for s in (a,b)]
    decisions={d.get('case_id'):d for d in p.get('decisions',[])}
    ids={r['case_id'] for r in dataset['cases']}
    if len(ids)!=54 or any(set(m)!=ids for m in maps) or set(decisions)!=ids:raise ValueError('冻结整批记录或终审记录不完整')
    for row in dataset['cases']:
        id=row['case_id'];d=decisions[id]
        if d.get('choice') not in {'A','B'} or not isinstance(d.get('reason'),str) or len(d['reason'].strip())<5:raise ValueError('冻结终审选择或依据无效')
        for m in maps:
            r=m[id]
            if profile_hash(r['profile'])!=profile_hash(row['profile']) or r['policy_id']!=row['policy_id'] or r['source_policy_sha256']!=row['source_policy_sha256']:raise ValueError('冻结案例与初审案例不一致')
        if row['expected']!=maps[0 if d['choice']=='A' else 1][id]['expected'] or row['review']['reviewer']!=people[2]:raise ValueError('冻结答案与终审记录不一致')
