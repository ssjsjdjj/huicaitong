"""Author blank v0.8 inputs and handoff materials; never call any assessor/model."""
from pathlib import Path
import collections,hashlib,html,json,sys,zipfile,copy
SITE=Path(__file__).resolve().parent.parent;LOCAL=SITE.parent if (SITE.parent/'app.py').is_file() else SITE.parent/'huicaitong'
sys.path[:0]=[str(SITE),str(LOCAL)]
from core import validate_profile
from application_flow import EXTRA,INTENT_IDS,draft_profile,extras
from human_evaluation import digest,profile_hash
from campaign_review import signed
from review import policy_hash

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
policies=[p for p in read(LOCAL/'data/policies.json')['policies'] if p['id'] in INTENT_IDS.values()]
registry=read(SITE/'data/source-registry.json');corpus=read(SITE/'data/primary-corpus.json')
safe={k:d['safe'] for k,d in EXTRA.items()}
living_claims=['连续参保时长可以不区分正常缴费与补缴。','第二笔生活补贴与首笔对应同一次生活补贴发放安排。','只提供学历信息就足以核对全部申请条件。','材料中毕业日期只记年月时，需要进一步核对日期口径。','在职取得学历和毕业后新就业可以不作区分。','用人单位类型与参保主体不影响申请条件核对。']
rent_claims=['家庭住房范围仅包括申请人本人。','当前无房即可代替房产交易历史的核对。','每笔补贴均需提交申请。','每户每年一万元等同于每笔发放一万元。','劳务派遣经历无需核对实际用工单位。','取得新学历后可以忽略以前领取租房补贴的记录。']
cases=[];design=[]
for task,intent in enumerate(INTENT_IDS):
    for i in range(20):
        month=1+(i*3+task)%8;day=1+(i*5+task*7)%27
        p={'city':'杭州','degree':['bachelor','master','phd'][(i+task)%3],'study_mode':'fulltime','school_region':'mainland','nationality':'cn','graduation_date':f'2025-{month:02d}-{day:02d}','application_date':'2026-11-11','insurance_start_date':f'2025-{month+1:02d}-01','insurance_months':6+(i%4),'employed_hangzhou':True,'employer_qualified':True,'insurance_current':True,'insurance_without_backpay':True,'degree_while_employed':False,'prior_other_degree_subsidy':False,'first_installment_received':intent=='living-second','family_has_home':False,'other_housing_benefit':False,'rent_first_received':False}
        e=copy.deepcopy(safe);tags=[]
        def change(key,value):p[key]=value;tags.append(key)
        def extra(key,value):e[key]=value;tags.append('extra.'+key)
        if i==0:
            change('degree',None);change('insurance_months',None);e={k:None for k in e};tags+=['supplementary_all_unknown']
        elif i==1:change('insurance_months',5)
        elif i==2:change('employer_qualified',None)
        elif i==3:change('school_region','overseas')
        elif i==4:change('study_mode','parttime')
        elif i==5:change('insurance_months',None)
        elif i==6:change('employed_hangzhou',None)
        elif i==7:change('insurance_start_date',None);change('insurance_months',None)
        elif i==8:change('insurance_without_backpay',False)
        elif i==9:change('rent_first_received' if intent=='rent' else 'first_installment_received',intent!='living-second')
        elif i==10:
            change('graduation_date',f'2027-04-{day:02d}');change('insurance_start_date',None);change('insurance_months',None);change('employed_hangzhou',None)
        elif i==11:
            change('graduation_date',f'2023-09-{day:02d}');change('insurance_start_date','2024-10-01');change('insurance_months',12)
        elif i==12:extra('graduation_record_precision','month')
        elif i==13:extra('has_dispatch_history',True)
        elif i==14:extra('family_scope_confirmed' if intent=='rent' else 'graduation_record_precision',False if intent=='rent' else 'unknown')
        elif i==15:extra('family_property_history' if intent=='rent' else 'has_dispatch_history',True if intent=='rent' else None)
        elif i==16:
            if intent=='rent':extra('prior_rent_degree_subsidy',True)
            else:change('prior_other_degree_subsidy',True)
        elif i==17:
            if intent=='rent':extra('housing_scope_confirmed',None);change('family_has_home',None)
            else:change('degree_while_employed',True)
        elif i==18:change('insurance_current',False)
        elif i==19:
            extra('has_dispatch_history',None)
            if intent=='rent':extra('housing_scope_confirmed',False);extra('family_property_history',None)
            else:change('nationality','other')
        p=draft_profile(validate_profile(p));e=extras(e)
        anchors=corpus['clause_anchors'];keys=['rent-eligibility','rent-time','rent-channel','rent-standard'] if intent=='rent' else ['living-materials','living-insurance','living-employer','living-payment']
        ids=anchors[keys[i%len(keys)]];passage=next(x for x in corpus['passages'] if x['id']==ids[i%len(ids)])
        probe={'claim':(rent_claims if intent=='rent' else living_claims)[i%6],'passage_id':passage['id'],'quote':passage['text'][:600],'origin':'project_authored_claim_for_human_verification_not_a_model_prediction'}
        case={'case_id':'v08-'+digest([intent,p,e,probe])[:12],'policy_id':INTENT_IDS[intent],'intent':intent,'profile':p,'supplementary':e,'evidence_probe':probe}
        case.update(input_sha256=digest(case),expected=None,title='合成记录 · '+case['case_id'][-6:],provenance={'kind':'project_authored_synthetic','training_use':'reserved_not_used','human_labeled':False})
        cases.append(case);design.append({'case_id':case['case_id'],'varied_fields':tags,'notice':'协调者抽样审计信息，不含参考答案，不发给盲审者。'})
cases.sort(key=lambda c:c['case_id'])
with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:known=set(json.loads(z.read('data/evaluation-known-profiles.json'))['profile_sha256'])
old=read(SITE/'data/review-campaign.json');old_hash={profile_hash(c['profile']) for c in old['cases']}
hashes=[profile_hash(c['profile']) for c in cases]
assert len(set(hashes))==60 and not set(hashes)&(known|old_hash)
patterns=collections.Counter(digest({'intent':c['intent'],'profile':{k:v for k,v in c['profile'].items() if k not in {'graduation_date','application_date','insurance_start_date'}},'supplementary':c['supplementary']}) for c in cases)
b={'schema_version':1,'protocol':'huicaitong-v08-human-v1','batch_id':'hz-v08-review-60-v1','created_on':'2026-11-11','engine_sha256':hashlib.sha256((SITE/'application_flow.py').read_bytes()).hexdigest(),'policies':policies,'source_registry':registry,'corpus':corpus,'cases':cases,'audit':{'cases':60,'blank_answers':60,'unique_profile_hashes':60,'known_exact_overlaps':0,'old54_exact_overlaps':0,'same_nondated_pattern_groups':sum(n>1 for n in patterns.values()),'policy_tasks':dict(collections.Counter(c['policy_id'] for c in cases)),'policy_families':2,'notice':'只排除本项目完全重复，日期差异不证明近重复独立性；整批及近重复须保留，不用于开发。'},'notice':'项目编写的合成输入，不是真实用户，不含人工答案。来源仍为2026-10-30快照；不认定当前效力。'}
write(SITE/'data/v08-reserved-profiles.json',{'batch_id':b['batch_id'],'batch_sha256':signed(b)['sha256'],'profile_sha256':sorted(hashes)});write(SITE/'data/review-v08.json',signed(b));write(SITE/'data/review-v08-design.json',{'batch_id':b['batch_id'],'cases':design})
print(json.dumps({'batch_id':b['batch_id'],'sha256':signed(b)['sha256'],'audit':b['audit']},ensure_ascii=False))
