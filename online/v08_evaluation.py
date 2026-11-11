"""Human-only v0.8 review protocol. Never infer or populate reference labels."""
import copy,json,re
from pathlib import Path
from collections import Counter
from campaign_review import signed,verify,identity,stamp,json_browser_numbers
from human_evaluation import digest
from application_flow import EXTRA,INTENT_IDS,draft_profile,extras
from core import RAW_FIELDS,FIELD_LABELS

ROOT=Path(__file__).resolve().parent
PROTOCOL='huicaitong-v08-human-v1'
SCREEN={'conditions_met':'所列条件满足','not_met':'存在明确不满足项','insufficient':'信息不足','outside_scope':'超出自动覆盖','planning':'在读或未来规划'}
QUAL={'recorded':'补充项已自填核对','pending':'补充信息待确认','manual':'需人工核验','outside_scope':'超出自动覆盖','planning':'在读或未来规划','base_blocked':'先处理明确不满足项'}
SUPPORT={'supports':'片段直接支持陈述','partial':'仅部分支持','unsupported':'片段无关或不足以支持','conflicting':'片段与陈述冲突','not_assessable':'快照、上下文或效力信息不足'}
KEYS=['screening','qualification','missing_fields','next_questions','materials','evidence_ids','evidence_support','evidence_reason','explanation']
LISTS={'missing_fields','next_questions','materials','evidence_ids'}
NOTICE='项目编写的合成候选，参考答案须由真实复核者填写。只评价给定快照下的限定初筛；不确认当前效力、完整资格或审批结果。'

def read(name):return json.loads((ROOT/'data'/name).read_text(encoding='utf-8'))
def batch():return verify(read('review-v08.json'),'v0.8候选批次')
def check_batch(b):
    verify(b,'候选快照')
    if b.get('protocol')!=PROTOCOL or len(b.get('cases',[]))!=60:raise ValueError('v0.8候选批次或协议无效')
    if any(c.get('expected') is not None for c in b['cases']):raise ValueError('候选原始快照不能携带参考答案')
    verify(b.get('source_registry'),'原文目录');verify(b.get('corpus'),'原文库')
    if b['corpus'].get('source_registry_sha256')!=b['source_registry']['sha256']:raise ValueError('原文库与来源目录不匹配')
    if not re.fullmatch(r'[0-9a-f]{64}',b.get('engine_sha256','')):raise ValueError('引擎版本指纹无效')
    ids=set();passages={p['id']:p for p in b['corpus']['passages']}
    for c in b['cases']:
        if c['case_id'] in ids or c['input_sha256']!=digest(input_of(c)):raise ValueError('候选输入编号或指纹无效')
        ids.add(c['case_id']);draft_profile(c['profile']);extras(c['supplementary'])
        if INTENT_IDS.get(c['intent'])!=c['policy_id'] or not any(p['id']==c['policy_id'] for p in b['policies']):raise ValueError('候选事项与政策不匹配')
        probe=c['evidence_probe'];p=passages.get(probe['passage_id'])
        if not p or not probe['quote'] or probe['quote'] not in p['text']:raise ValueError('核验片段不是原文连续子串')
    return b
def fields():return {**{k:v for k,v in FIELD_LABELS.items()},**{'extra.'+k:v['label'] for k,v in EXTRA.items()}}
def meta():
    b=batch();return {'protocol':PROTOCOL,'batch_id':b['batch_id'],'batch_sha256':b['sha256'],'cases':len(b['cases']),'screening':SCREEN,'qualification':QUAL,'support':SUPPORT,'field_labels':fields(),'supplementary':{k:{key:value for key,value in d.items() if key!='safe'} for k,d in EXTRA.items()},'notice':NOTICE,'audit':b['audit'],'engine_sha256':b['engine_sha256']}
def record(c):return {'case_id':c['case_id'],'input_sha256':c['input_sha256'],'answer':None,'confirmed':False,'source_checked':False,'reviewer':None,'reviewed_at':None}
def base_packet(slot,b):
    if slot not in {'A','B'}:raise ValueError('请选择 A 或 B 独立任务')
    return {'schema_version':1,'protocol':PROTOCOL,'slot':slot,'batch_id':b['batch_id'],'batch_sha256':b['sha256'],'engine_sha256':b['engine_sha256'],'source_registry_sha256':b['source_registry']['sha256'],'corpus_sha256':b['corpus']['sha256']}
def assignment(slot):
    b=check_batch(batch());value={**base_packet(slot,b),'type':'v08_assignment','cases':copy.deepcopy(b['cases']),'records':[record(c) for c in b['cases']],'notice':NOTICE}
    # Different display order, not additional samples; no answer-derived sorting.
    value['cases'].sort(key=lambda c:digest([slot,c['case_id']]))
    return signed(value)
def catalogue():
    b=batch();return {'cases':copy.deepcopy(b['cases']),'policies':b['policies'],'source_registry':b['source_registry'],'corpus':b['corpus'],'engine_sha256':b['engine_sha256']}
def input_of(c):return {k:c[k] for k in ('case_id','policy_id','intent','profile','supplementary','evidence_probe')}
def allowed(c,b):
    p=next(p for p in b['policies'] if p['id']==c['policy_id'])
    return {'missing_fields':set(fields()),'next_questions':set(fields()),'materials':{m['id'] for m in p['materials']},'evidence_ids':{p['id'] for p in b['corpus']['passages']}}
def answer(value,c,b,complete=False):
    if value is None:
        if complete:raise ValueError('本条尚无人工答案')
        return None
    if not isinstance(value,dict) or set(value)!=set(KEYS):raise ValueError('标注字段不完整或含未知字段')
    out=copy.deepcopy(value)
    for k,choices in [('screening',SCREEN),('qualification',QUAL),('evidence_support',SUPPORT)]:
        if out[k] not in choices and (complete or out[k]!=''):raise ValueError('请选择有效的'+k)
    options=allowed(c,b)
    for key in LISTS:
        vals=out[key]
        if not isinstance(vals,list) or len(vals)>80 or any(not isinstance(x,str) for x in vals) or len(set(vals))!=len(vals) or set(vals)-options[key]:raise ValueError('标注中的字段、材料或原文定位编号无效：'+key)
        out[key]=sorted(vals)
    if len(out['next_questions'])>8:raise ValueError('可接受下一问最多选择8项')
    for k in ('evidence_reason','explanation'):
        if not isinstance(out[k],str) or len(out[k])>3000 or (complete and len(out[k].strip())<5):raise ValueError('请为条件判断与证据支持分别填写至少5字依据')
    if complete and not out['evidence_ids']:raise ValueError('请至少记录一个核对过的原文定位编号')
    return out
def records(rows,slot,b,complete=False,who=None):
    if not isinstance(rows,list) or len(rows)!=60:raise ValueError('须保留本批完整60条记录，不能只提交已确认子集')
    cs={c['case_id']:c for c in b['cases']};seen=set();clean=[]
    for r in rows:
        if not isinstance(r,dict) or set(r)!=set(record(b['cases'][0])):raise ValueError('复核记录格式无效')
        id=r.get('case_id');c=cs.get(id)
        if not c or id in seen or r.get('input_sha256')!=c['input_sha256']:raise ValueError('案例编号重复、输入或来源绑定已变化')
        seen.add(id)
        if type(r['confirmed']) is not bool or type(r['source_checked']) is not bool:raise ValueError('确认状态须为布尔值')
        confirmed=r['confirmed']
        if complete and not confirmed:raise ValueError('还有待复核案例：'+id)
        a=answer(r['answer'],c,b,confirmed)
        if confirmed:
            reviewer=identity(r['reviewer'],'本条复核者');stamp(r['reviewed_at'])
            if not r['source_checked']:raise ValueError('已确认记录须明确声明阅读原文')
            if who and reviewer.casefold()!=who.casefold():raise ValueError('本条复核者与整批提交标识不一致')
        elif r['reviewer'] is not None or r['reviewed_at'] is not None or r['source_checked']:
            raise ValueError('修改后的待复核记录须清除旧确认、复核者及时间')
        clean.append({**r,'answer':a})
    return sorted(clean,key=lambda r:r['case_id'])
def draft(body):
    b=batch();slot=body.get('slot');p=base_packet(slot,b);who=body.get('reviewer_id','')
    if not isinstance(who,str) or len(who)>80:raise ValueError('复核者标识无效')
    return signed({**p,'type':'v08_review_draft','reviewer_id':who.strip(),'records':records(body.get('records'),slot,b),'saved_at':stamp(body.get('saved_at'))})
def restore(packet):
    b=batch();verify(packet,'复核文件');slot=packet.get('slot');p=base_packet(slot,b)
    if any(packet.get(k)!=v for k,v in p.items()):raise ValueError('这份文件属于其他批次、引擎或原文版本，不能混入本次任务')
    if packet.get('type')=='v08_assignment':
        if packet!=assignment(slot):raise ValueError('原始任务内容已改变')
        return {'assignment':packet,'reviewer_id':'','records':packet['records']}
    if packet.get('type')!='v08_review_draft':raise ValueError('请导入v0.8任务文件或复核草稿；旧54条文件仍使用旧入口')
    rebuilt=draft({**packet,'slot':slot})
    if packet!=rebuilt:raise ValueError('草稿字段或内容不一致')
    return {'assignment':assignment(slot),'reviewer_id':packet['reviewer_id'],'records':rebuilt['records']}
def submit(body):
    restored=restore(body.get('packet'));p=body['packet']
    if p['type']!='v08_review_draft':raise ValueError('请先保存复核草稿再提交')
    who=identity(p['reviewer_id'],'整批复核者')
    if body.get('independent_confirmed') is not True:raise ValueError('请声明独立阅读，未参考另一人、规则或模型答案')
    b=batch();rows=records(restored['records'],p['slot'],b,True,who)
    return signed({**base_packet(p['slot'],b),'type':'v08_review_submission','reviewer_id':who,'records':rows,'independent_declared':True,'submitted_at':stamp(body.get('submitted_at'))})
def submission(p,b):
    verify(p,'正式提交');base=base_packet(p.get('slot'),b)
    if p.get('type')!='v08_review_submission' or any(p.get(k)!=v for k,v in base.items()) or p.get('independent_declared') is not True:raise ValueError('正式提交协议、批次、来源或独立性声明不一致')
    who=identity(p.get('reviewer_id'),'复核者');stamp(p.get('submitted_at'))
    clean=records(p.get('records'),p['slot'],b,True,who)
    expected=signed({**base,'type':'v08_review_submission','reviewer_id':who,'records':clean,'independent_declared':True,'submitted_at':p['submitted_at']})
    if p!=expected:raise ValueError('正式提交包含多余或不一致的内容')
    return p
def compare(body,b=None):
    b=check_batch(b or batch());a=submission(body.get('a'),b);bb=submission(body.get('b'),b)
    if a['slot']!='A' or bb['slot']!='B' or a['reviewer_id'].casefold()==bb['reviewer_id'].casefold():raise ValueError('需要A/B任务及两位不同标识的真实复核者')
    maps=[{r['case_id']:r for r in p['records']} for p in (a,bb)];rows=[]
    for c in b['cases']:
        x,y=[m[c['case_id']]['answer'] for m in maps];diff=[k for k in KEYS if x[k]!=y[k]]
        rows.append({'case_id':c['case_id'],'a':x,'b':y,'different_fields':diff})
    return {'cases':rows,'agreements':sum(not r['different_fields'] for r in rows),'total':60,'pair_sha256':digest([a['sha256'],bb['sha256']]),'notice':'结构与文字均纳入差异；全部案例都须第三人核对解释及证据。标识不认证真实身份。'}
def decisions(values,b,complete=False):
    if not isinstance(values,list) or len(values)>60:raise ValueError('终审记录无效')
    ids={c['case_id'] for c in b['cases']};seen=set()
    for d in values:
        if not isinstance(d,dict) or set(d)!={'case_id','choice','reason','checked'}:raise ValueError('终审字段无效')
        if d['case_id'] not in ids or d['case_id'] in seen:raise ValueError('终审编号未知或重复')
        seen.add(d['case_id'])
        if d['choice'] not in {'','A','B'} or not isinstance(d['reason'],str) or len(d['reason'])>3000 or type(d['checked']) is not bool:raise ValueError('终审选择、说明或确认无效')
        if complete and (d['choice']=='' or len(d['reason'].strip())<5 or not d['checked']):raise ValueError('每条均须第三人选择A/B、填写依据并确认已核对')
    if complete and seen!=ids:raise ValueError('第三人须完成全部60条终审，两人均有误时应退回重交')
    return sorted(copy.deepcopy(values),key=lambda d:d['case_id'])
def adjudication_draft(body):
    b=batch();a=body.get('a');bb=body.get('b')
    if a is not None:submission(a,b)
    if bb is not None:submission(bb,b)
    pair=compare(body,b)['pair_sha256'] if a is not None and bb is not None else None
    if body.get('decisions'):
        if pair is None:raise ValueError('未齐备A/B来源，不能保存终审选择')
        if body.get('pair_sha256')!=pair:raise ValueError('终审选择绑定的A/B提交已变化，请重新核对')
    who=body.get('adjudicator_id','')
    if not isinstance(who,str) or len(who)>80:raise ValueError('终审者标识无效')
    return signed({'schema_version':1,'protocol':PROTOCOL,'type':'v08_adjudication_draft','a':a,'b':bb,'adjudicator_id':who,'decisions':decisions(body.get('decisions',[]),b),'batch_sha256':b['sha256'],'pair_sha256':pair})
def restore_adjudication(packet):
    verify(packet,'终审草稿')
    if packet!=adjudication_draft(packet):raise ValueError('终审草稿与A/B来源不匹配')
    return packet
def freeze(body):
    b=check_batch(batch());report=compare(body,b);who=identity(body.get('adjudicator_id'),'第三人终审者')
    if body.get('pair_sha256')!=report['pair_sha256']:raise ValueError('终审记录与当前A/B提交指纹不一致')
    if who.casefold() in {body[x]['reviewer_id'].casefold() for x in ('a','b')}:raise ValueError('终审者标识须与两位初审者不同')
    if body.get('source_checked') is not True or body.get('independence_confirmed') is not True:raise ValueError('请声明核对全部原文及解释，并确认本批及近重复未用于开发')
    ds=decisions(body.get('decisions'),b,True);dm={d['case_id']:d for d in ds};chosen=[]
    for r in report['cases']:chosen.append({'case_id':r['case_id'],'expected':r[dm[r['case_id']]['choice'].lower()]})
    return signed({'schema_version':1,'protocol':PROTOCOL,'type':'v08_frozen_dataset','purpose':'test','annotation_source':'reviewer_declared','batch_snapshot':b,'a':body['a'],'b':body['b'],'pair_sha256':report['pair_sha256'],'adjudicator_id':who,'decisions':ds,'source_checked':True,'independence_confirmed':True,'frozen_at':stamp(body.get('frozen_at')),'cases':chosen,'notice':NOTICE+' 本批仅两个政策家族；引用支持标签只针对指定陈述和片段，不认证模型解释。'})
def verify_dataset(d):
    verify(d,'冻结评测集')
    if d.get('type')!='v08_frozen_dataset' or d.get('protocol')!=PROTOCOL or d.get('purpose')!='test' or d.get('annotation_source')!='reviewer_declared':raise ValueError('请选择v0.8正式冻结评测集')
    b=check_batch(d.get('batch_snapshot'));r=compare(d,b);who=identity(d.get('adjudicator_id'),'终审者')
    if d.get('pair_sha256')!=r['pair_sha256']:raise ValueError('冻结终审记录与A/B提交不一致')
    if who.casefold() in {d[x]['reviewer_id'].casefold() for x in ('a','b')} or d.get('source_checked') is not True or d.get('independence_confirmed') is not True:raise ValueError('冻结独立性与三人复核记录无效')
    ds=decisions(d.get('decisions'),b,True);dm={v['case_id']:v['choice'].lower() for v in ds};stamp(d.get('frozen_at'))
    if d.get('cases')!=[{'case_id':c['case_id'],'expected':c[dm[c['case_id']]]} for c in r['cases']]:raise ValueError('冻结答案与终审选择不一致')
    return b
def prediction_input(d):
    b=verify_dataset(d)
    return {'schema_version':1,'protocol':PROTOCOL,'dataset_sha256':d['sha256'],'evidence_mode':'pinned_primary_snapshot','engine_sha256':b['engine_sha256'],'requests':[input_of(c) for c in b['cases']],'policies':b['policies'],'corpus':b['corpus'],'output_contract':{'screening':SCREEN,'qualification':QUAL,'missing_fields':'字段编号列表','materials':'材料编号列表','evidence_ids':'原文定位编号列表','next_question':'一个字段编号或null','evidence_support':SUPPORT,'explanation':'模型实际说明；不会自动评价语义'},'notice':'不含人工答案。必须固定模型、输入、提示词、解码与来源版本；这不是已完成的RAG检索评测。'}
def f1(a,b):
    a,b=set(a),set(b)
    return 1 if not a and not b else 2*len(a&b)/(len(a)+len(b)) if a or b else 0
def evaluate(body):
    d=body.get('dataset');b=verify_dataset(d);pred=body.get('predictions');model=identity(body.get('model_name'),'实验名称')
    if body.get('dataset_sha256')!=d['sha256']:raise ValueError('预测文件必须绑定当前冻结集指纹')
    if not isinstance(pred,list) or len(pred)>60:raise ValueError('预测须为不超过60条记录的列表')
    ids={c['case_id'] for c in b['cases']};ps={}
    for p in pred:
        if not isinstance(p,dict) or set(p)!={'case_id','completion'} or p['case_id'] not in ids or p['case_id'] in ps:raise ValueError('预测编号未知、重复或格式无效')
        ps[p['case_id']]=p['completion']
    truth={r['case_id']:r['expected'] for r in d['cases']};details=[];totals=Counter();confusion={}
    for c in b['cases']:
        id=c['case_id'];e=truth[id];raw=ps.get(id);valid=True
        try:
            p=json.loads(raw) if isinstance(raw,str) else raw
            if not isinstance(p,dict) or set(p)!={'screening','qualification','missing_fields','materials','evidence_ids','next_question','evidence_support','explanation'}:raise ValueError()
            if p['screening'] not in SCREEN or p['qualification'] not in QUAL or p['evidence_support'] not in SUPPORT or not isinstance(p['explanation'],str) or len(p['explanation'])>3000:raise ValueError()
            for k in ('missing_fields','materials','evidence_ids'):
                v=p[k]
                if not isinstance(v,list) or any(not isinstance(x,str) for x in v) or len(v)!=len(set(v)) or set(v)-allowed(c,b)[k]:raise ValueError()
            if p['next_question'] is not None and p['next_question'] not in fields():raise ValueError()
        except (ValueError,TypeError,KeyError):valid=False;p={}
        scores={k:int(valid and p.get(k)==e[k]) for k in ('screening','qualification','evidence_support')}
        scores.update({k:f1(p[k],e[k]) if valid else 0 for k in ('missing_fields','materials','evidence_ids')})
        scores['next_question']=int(valid and (p['next_question'] in e['next_questions'] if e['next_questions'] else p['next_question'] is None))
        for k,v in scores.items():totals[k]+=v
        totals['valid']+=int(valid);totals['missing']+=int(id not in ps)
        totals['false_conditions_met']+=int(valid and p['screening']=='conditions_met' and e['screening']!='conditions_met')
        totals['false_recorded']+=int(valid and p['qualification']=='recorded' and e['qualification']!='recorded')
        key=e['screening']+' → '+(p.get('screening') if valid else 'invalid');confusion[key]=confusion.get(key,0)+1
        details.append({'case_id':id,'valid':valid,'missing':id not in ps,'scores':scores,'expected':e,'prediction':raw})
    return json_browser_numbers({'dataset_sha256':d['sha256'],'model_name':model,'cases':60,'supplied':len(ps),'valid_outputs':totals['valid'],'missing_predictions':totals['missing'],'false_conditions_met':totals['false_conditions_met'],'false_recorded':totals['false_recorded'],'metrics':{k:totals[k]/60 for k in ('screening','qualification','evidence_support','missing_fields','materials','evidence_ids','next_question')},'screening_confusion':confusion,'details':details,'notice':'全部60条留在分母中；缺失与无效计零。原文编号F1不代表语义支持；片段支持准确率只评价预设陈述。未自动认证模型来源或解释正确性。'})
