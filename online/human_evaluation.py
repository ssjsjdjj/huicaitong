"""Reviewer-declared datasets and reproducible evaluation; never generate human labels."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from core import RAW_FIELDS, validate_profile
from review import policy_hash, restore_drafts, reviewed_tasks
from store import validate_policy

ROOT=Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def profile_hash(profile):
    clean=validate_profile(profile)
    return digest({field:clean.get(field) for field in sorted(RAW_FIELDS)})


def provenance(row):
    if str(row.get('case_id','')).startswith('ai-dev-') or row.get('protocol')=='huicaitong-ai-prereview-v1' or row.get('type')=='ai_assisted_development_records':
        raise ValueError('AI辅助开发记录不能作为独立人工标注，请使用AI辅助预审入口')
    if row.get('case_id','').startswith('review-draft-') or row.get('scenario_source')=='synthetic_draft_for_blind_review':
        return {'kind':'built_in_practice','training_use':'unknown'}
    source=row.get('provenance',{})
    if not isinstance(source,dict):
        raise ValueError('案例来源记录须为对象')
    kind=source.get('kind','unknown')
    use=source.get('training_use','unknown')
    if kind not in {'user_authored_synthetic','deidentified_case','unknown'} or use not in {'not_used','used','unknown'}:
        raise ValueError('案例来源或既往使用情况无效')
    return {'kind':kind,'training_use':use}


def restore_rows(rows,policies):
    clean=restore_drafts(rows,policies)
    for original,row in zip(rows,clean):
        row['provenance']=provenance(original)
        if 'campaign' in original:
            from campaign_review import validate_assignment_rows
            validate_assignment_rows([original],policies)
            row['campaign']=original['campaign'].copy()
    return clean


def new_case(body,policies):
    case_id=body.get('case_id')
    if not isinstance(case_id,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{2,119}',case_id) or case_id.startswith('review-draft-'):
        raise ValueError('新案例编号须为 3—120 位英文、数字、点、下划线或短横线，不能使用内置草稿前缀')
    title=body.get('title')
    if not isinstance(title,str) or not title.strip() or len(title)>200:
        raise ValueError('请填写不超过 200 字的案例标题')
    policy=next((p for p in policies if p['id']==body.get('policy_id')),None)
    if policy is None:
        raise ValueError('请选择已有政策')
    raw_profile=body.get('profile')
    if not isinstance(raw_profile,dict) or not raw_profile.get('application_date'):
        raise ValueError('请在新案例中明确填写 application_date 参考日期')
    profile=validate_profile(raw_profile)
    source=provenance(body)
    return {'case_id':case_id,'title':title.strip(),'policy_id':policy['id'],'profile':profile,
            'source_policy_sha256':policy_hash(policy),'provenance':source,'expected':None,
            'review':{'status':'pending','reviewer':None,'reviewed_at':None}}


def known_profiles():
    path=ROOT/'data'/'evaluation-known-profiles.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'profile_sha256':[]}


def summarize(rows,policies):
    catalogue={p['id']:p for p in policies}
    confirmed=[r for r in rows if r.get('review',{}).get('status')=='reviewed']
    return {'cases':len(rows),'reviewed':len(confirmed),'pending':len(rows)-len(confirmed),
            'unique_profiles':len({profile_hash(r['profile']) for r in rows}),
            'conclusions':dict(Counter(r['expected']['conclusion'] for r in confirmed)),
            'families':dict(Counter(catalogue[r['policy_id']]['family'] for r in rows)),
            'origins':dict(Counter(provenance(r)['kind'] for r in rows))}


def freeze_dataset(body,policies,*,_campaign_authorized=False):
    if not body.get('cases'):
        raise ValueError('当前没有已确认记录，请先阅读原文并保存人工标注')
    rows=restore_rows(body.get('cases'),policies)
    if any('campaign' in r for r in rows):
        raise ValueError('54条保留批次须通过双人独立复核与终审冻结，不能从普通冻结入口跳过流程')
    reserved_path=ROOT/'data'/'review-campaign.json'
    if reserved_path.exists() and not _campaign_authorized:
        reserved={profile_hash(r['profile']) for r in json.loads(reserved_path.read_text(encoding='utf-8'))['cases']}
        if any(profile_hash(r['profile']) in reserved for r in rows):
            raise ValueError('人物字段属于54条保留批次，移除任务元数据也不能跳过双人复核')
    v08_reserved=ROOT/'data'/'v08-reserved-profiles.json'
    if v08_reserved.exists():
        v08_hashes=set(json.loads(v08_reserved.read_text(encoding='utf-8'))['profile_sha256'])
        if any(profile_hash(r['profile']) in v08_hashes for r in rows):
            raise ValueError('人物字段属于v0.8保留批次，请使用专用三人复核入口；不能降为旧格式绕过流程')
    if any(r['review']['status']!='reviewed' for r in rows):
        raise ValueError('冻结评测集只接受已填写依据并人工确认的记录；待复核草稿不能计入')
    reviewed_tasks(rows,policies)
    name=body.get('name','')
    dataset_id=body.get('dataset_id','')
    purpose=body.get('purpose')
    if not isinstance(name,str) or not 1<=len(name.strip())<=120:
        raise ValueError('请填写 1—120 字的评测集名称')
    if not isinstance(dataset_id,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{2,79}',dataset_id):
        raise ValueError('评测集编号须为 3—80 位英文、数字、点、下划线或短横线')
    if purpose not in {'development','test'}:
        raise ValueError('请选择开发用途或测试用途')
    known=set(known_profiles().get('profile_sha256',[]))
    overlap=[r['case_id'] for r in rows if profile_hash(r['profile']) in known]
    tasks={(r['policy_id'],profile_hash(r['profile'])) for r in rows}
    if len(tasks)!=len(rows):
        raise ValueError('存在同一政策下人物字段完全相同的重复任务，请合并后再冻结')
    if purpose=='test':
        if any(provenance(r)['kind']=='built_in_practice' for r in rows):
            raise ValueError('内置 36 条练习草稿不能声明为独立测试集，请另建未参与开发的新案例')
        if overlap:
            raise ValueError('以下人物字段与已有开发或历史检查记录重复，不能声明为独立测试：'+ '、'.join(overlap[:8]))
        if any(provenance(r)['kind']=='unknown' or provenance(r)['training_use']!='not_used' for r in rows):
            raise ValueError('测试用途须逐条声明新案例来源及未用于训练、提示词或模型选择')
        if body.get('independence_confirmed') is not True:
            raise ValueError('请确认本批及其近重复案例未参与训练、调参或模型选择')
    catalogue={p['id']:p for p in policies}
    selected=[catalogue[i] for i in sorted({r['policy_id'] for r in rows})]
    timestamp=body.get('frozen_at') or datetime.now(timezone.utc).isoformat()
    try:
        if datetime.fromisoformat(timestamp.replace('Z','+00:00')).tzinfo is None:raise ValueError()
    except (TypeError,ValueError,AttributeError):
        raise ValueError('冻结时间须为带时区的 ISO 时间') from None
    result={'schema_version':1,'dataset_id':dataset_id,'name':name.strip(),'purpose':purpose,
            'annotation_source':'reviewer_declared','frozen_at':timestamp,'policies':selected,'cases':rows,
            'summary':summarize(rows,policies),'known_profile_overlap':overlap,
            'independence':{'user_declared':purpose=='test','external_training_history_verified':False,
                            'notice':'只检测本项目记录中的完全相同人物字段；不证明近重复、外部训练历史或跨政策泛化。'},
            'notice':'人工标注为复核者声明，不是主管部门审批或第三方认证。SHA-256 用于检查文件是否改变，不证明标注正确。'}
    result['sha256']=digest(result)
    return result


def verify_dataset(dataset):
    if not isinstance(dataset,dict) or dataset.get('schema_version')!=1:
        raise ValueError('评测集格式版本无效')
    content={k:v for k,v in dataset.items() if k!='sha256'}
    if dataset.get('sha256')!=digest(content):
        raise ValueError('评测集 SHA-256 不匹配，文件可能已修改；请使用冻结时的原文件')
    if dataset.get('purpose') not in {'development','test'} or dataset.get('annotation_source')!='reviewer_declared':
        raise ValueError('评测集用途或标注来源无效')
    policies=dataset.get('policies')
    if not isinstance(policies,list) or not 1<=len(policies)<=30:
        raise ValueError('评测集政策快照无效')
    for policy in policies:validate_policy(policy)
    if len({p['id'] for p in policies})!=len(policies):
        raise ValueError('评测集政策快照编号重复')
    rows=restore_rows(dataset.get('cases'),policies)
    tasks=reviewed_tasks(rows,policies)
    if dataset.get('review_protocol') is not None:
        from campaign_review import verify_protocol
        verify_protocol(dataset,policies)
    if dataset['purpose']=='test' and any(provenance(r)['kind']=='built_in_practice' for r in rows):
        raise ValueError('内置练习不能作为独立测试用途')
    return rows,tasks,policies


def evaluate_dataset(body):
    from training.evaluate import evaluate_predictions
    dataset=body.get('dataset')
    rows,tasks,policies=verify_dataset(dataset)
    predictions=body.get('predictions')
    model=body.get('model_name')
    if not isinstance(model,str) or not model.strip() or len(model)>120:
        raise ValueError('请填写本次预测对应的模型或实验名称')
    if not isinstance(predictions,list) or len(predictions)>200:
        raise ValueError('预测文件须为不超过 200 条记录的列表')
    binding=body.get('prediction_dataset_sha256')
    if binding is not None and binding!=dataset['sha256']:
        raise ValueError('预测文件的评测集指纹与当前冻结集不同，不能混用')
    if binding is None and body.get('binding_confirmed') is not True:
        raise ValueError('预测文件未带评测集指纹，请先确认其对应当前冻结集')
    normalized=[]
    for item in predictions:
        if not isinstance(item,dict) or not isinstance(item.get('case_id'),str) or 'completion' not in item:
            raise ValueError('每条预测需要 case_id 和 completion')
        completion=item['completion']
        if isinstance(completion,dict):completion=json.dumps(completion,ensure_ascii=False)
        if not isinstance(completion,str) or len(completion)>30000:
            raise ValueError('completion 须为 JSON 文本或对象，且不超过 30000 字')
        normalized.append({'case_id':item['case_id'],'completion':completion})
    result,details=evaluate_predictions(tasks,normalized)
    result.update(label_source='reviewer_declared',dataset_id=dataset['dataset_id'],dataset_sha256=dataset['sha256'],
                  model_name=model.strip(),predictions_sha256=digest(normalized),purpose=dataset.get('purpose'),
                  prediction_binding='artifact_sha256' if binding else 'user_declared',
                  warning='引用指标只比较编号，不证明解释语义或标注质量。缺失预测计错；本页面不运行模型，也不验证预测文件的模型来源。')
    supplied={row['case_id'] for row in normalized}
    for detail in details:detail['missing_prediction']=detail['case_id'] not in supplied
    result['dataset_summary']=summarize(rows,policies)
    from diagnostics import analyze
    return {'metrics':result,'details':details,'dataset_sha256':dataset['sha256'],'diagnostics':analyze(tasks,normalized,details,policies)}
