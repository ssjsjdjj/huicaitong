"""Observable prediction errors and rule-comparison clues, never model causal claims."""
from collections import Counter
import json
from core import assess_policy
from llm import parse_completion

LABELS=('eligible','ineligible','insufficient')
CATEGORIES={'false_pass':'误判通过','false_reject':'误判拒绝','premature_reject':'信息不足却判拒绝','unnecessary_abstention':'可通过却转待核验','missed_rejection':'不满足却转待核验','invalid_output':'格式或编号错误','missing_prediction':'缺失预测','evidence_ids':'引用编号差异','missing_fields':'缺失字段差异','materials':'准备清单差异'}

def analyze(tasks,predictions,details,policies):
    ps={r['case_id']:r.get('completion','') for r in predictions};pm={p['id']:p for p in policies};tm={t['case_id']:t for t in tasks};records=[]
    for detail in details:
        task=tm[detail['case_id']];target=task['ground_truth'];target=json.loads(target) if isinstance(target,str) else target
        raw=ps.get(detail['case_id'],'');raw=json.dumps(raw,ensure_ascii=False) if isinstance(raw,dict) else raw
        predicted=detail['predicted'];expected=detail['expected'];missing=detail['case_id'] not in ps;categories=[]
        if missing:categories.append('missing_prediction')
        elif not detail['valid']:categories.append('invalid_output')
        if predicted=='eligible' and expected!='eligible':categories.append('false_pass')
        if predicted=='ineligible' and expected=='eligible':categories.append('false_reject')
        if predicted=='ineligible' and expected=='insufficient':categories.append('premature_reject')
        if predicted=='insufficient' and expected=='eligible':categories.append('unnecessary_abstention')
        if predicted=='insufficient' and expected=='ineligible':categories.append('missed_rejection')
        categories.extend(k for k in ('evidence_ids','missing_fields','materials') if k in detail['errors'])
        policy=pm[task['policy_id']];rule=assess_policy(policy,task['profile'])
        prediction=None
        if detail['valid']:
            try:prediction=parse_completion(raw)
            except (TypeError,ValueError):pass
        differences={}
        if prediction:
            for key in ('evidence_ids','missing_fields','materials'):
                wanted=set(target.get(key,[]));actual=set(prediction.get(key,[]));differences[key]={'omitted':sorted(wanted-actual),'extra':sorted(actual-wanted)}
        records.append({'case_id':detail['case_id'],'policy_id':policy['id'],'policy_title':policy['title'],'expected':expected,'predicted':predicted,'categories':categories,'structured_match':detail['valid'] and not detail['errors'],'missing_prediction':missing,'profile':task['profile'],'reference':{k:target[k] for k in ('policy_id','conclusion','evidence_ids','missing_fields','materials','explanation')},'prediction':prediction,'raw_output':raw,'differences':differences,'rule_signals':[{'field':r['field'],'label':r['label'],'status':r['status'],'actual':r['actual'],'citation':r['citation'],'kind':r['kind']} for r in rule['checks'] if r['status'] in {'fail','unknown'}],'rule_conclusion':rule['conclusion']})
    n=len(records);counts=Counter(k for r in records for k in r['categories']);nonpass=sum(r['expected']!='eligible' for r in records);predpass=sum(r['predicted']=='eligible' for r in records);correctpass=sum(r['predicted']==r['expected']=='eligible' for r in records)
    matrix={label:{p:sum(r['expected']==label and r['predicted']==p for r in records) for p in (*LABELS,'invalid')} for label in LABELS}
    return {'schema_version':1,'categories':CATEGORIES,'summary':{'cases':n,'cases_with_errors':sum(bool(r['categories']) for r in records),'false_pass':counts['false_pass'],'false_pass_from_ineligible':sum(r['predicted']=='eligible' and r['expected']=='ineligible' for r in records),'false_pass_from_insufficient':sum(r['predicted']=='eligible' and r['expected']=='insufficient' for r in records),'reference_nonpass':nonpass,'false_pass_rate':counts['false_pass']/nonpass if nonpass else None,'predicted_pass':predpass,'correct_pass':correctpass,'pass_precision':correctpass/predpass if predpass else None,'missing_predictions':counts['missing_prediction'],'invalid_outputs_supplied':counts['invalid_output'],'category_counts':dict(counts),'confusion_matrix':matrix},'cases':records,'notice':'分类来自参考标注与实际预测的可观察差异；规则线索只与所存快照对照，不推断模型内部原因，不认证人工标注、原文语义支持或真实审批资格。同一案例可能有多类错误。'}
