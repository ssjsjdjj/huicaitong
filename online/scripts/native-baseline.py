from pathlib import Path
import base64
import copy
import json
import sys
import tempfile
import zipfile

site=Path(__file__).resolve().parent.parent
work=site/'.work'
work.mkdir(exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='online-baseline-',dir=work)).resolve()
assert root.is_relative_to(work.resolve())
with zipfile.ZipFile(site/'dist'/'python-app.zip') as archive:
    for info in archive.infolist():
        assert not Path(info.filename).is_absolute() and '..' not in Path(info.filename).parts
    archive.extractall(root)
sys.path.insert(0,str(root))
from browser_backend import request
from fixtures import CASES

spec=[]
def run(path,body=None):
    result=request(path,body)
    spec.append({'url':path,'body':body,'expected':copy.deepcopy(result)})
    return result['data']

for path in ('/api/health','/api/meta','/api/policies','/api/examples','/api/materials/capabilities','/api/evaluate'):
    run(path)
for case in CASES:
    run('/api/assess',{'profile':case['profile']})
run('/api/application/meta')
safe={'graduation_record_precision':'day','has_dispatch_history':False,'family_scope_confirmed':True,'housing_scope_confirmed':True,'family_property_history':False,'prior_rent_degree_subsidy':False}
application={'profile':CASES[0]['profile'],'supplementary':safe,'intent':'rent','saved_at':'2026-11-11T08:00:00+08:00'}
run('/api/application/assess',application)
run('/api/application/assess',{**application,'supplementary':{}})
run('/api/application/assess',{**application,'supplementary':{**safe,'family_property_history':True}})
run('/api/application/guide',{'profile':{'application_date':'2026-11-11'},'intent':'rent','deferred':['degree']})
run('/api/application/guide',{**application,'focus_question':'extra.family_property_history'})
application_report=run('/api/application/assess',application)
application['preparation']={'context_sha256':application_report['application']['context_sha256'],'items':{application_report['application']['preparation_items'][0]['id']:'ready'}}
application_packet=run('/api/application/packet',application)
run('/api/application/restore',{'packet':application_packet})
tampered=copy.deepcopy(application_packet);tampered['profile']['degree']='phd'
run('/api/application/restore',{'packet':tampered})
run('/api/application/packet',{'profile':{'insurance_months':True}})
run('/api/application/packet',{'profile':{'application_date':None,'insurance_start_date':'2025-01-01','graduation_date':'2026-10-01'},'saved_at':application['saved_at']})
for query in ('生活补贴首笔需要几个月社保','租房补贴家庭有房能申请吗','生活补贴多少钱 去哪里申请'):
    from urllib.parse import urlencode
    run('/api/search?'+urlencode({'q':query,'as_of':'2026-10-21'}))
run('/api/search?q=生活补贴&as_of=2018-01-01&history=1')
run('/api/search?q=test&as_of=bad-date')
for example in ('graduation','insurance','gap'):
    file=run('/api/materials/example?id='+example)
    run('/api/materials/extract',{**file,'profile':CASES[0]['profile']})
run('/api/materials/extract',{'filename':'image.png','content_base64':base64.b64encode(b'not an image').decode(),'profile':CASES[0]['profile']})
run('/api/materials/extract',{'filename':'bad.pdf','content_base64':base64.b64encode(b'broken').decode(),'profile':CASES[0]['profile']})
draft=run('/api/review/draft')
run('/api/review/restore',{'schema_version':1,'cases':draft['cases']})
run('/api/review/validate',{'cases':draft['cases']})
run('/api/model-assess',{'profile':CASES[0]['profile']})
policy=copy.deepcopy(run('/api/policies')['policies'][0])
policy['id']='online-parity-policy-v1'
mapping={c['id']:'online-parity-'+str(i) for i,c in enumerate(policy['clauses'])}
for clause in policy['clauses']:
    clause['id']=mapping[clause['id']]
for entry in policy['scope']+policy['rules']+policy['materials']:
    entry['citation']=mapping[entry['citation']]
payload={'city':'杭州','policies':[policy]}
run('/api/import',payload)
run('/api/policies')
run('/api/import',payload)
run('/api/meta')
run('/api/assess',{'profile':[]})
run('/api/unknown')
new=run('/api/review/new-case',{'case_id':'baseline-new-001','title':'Software fixture only','policy_id':draft['cases'][0]['policy_id'],'profile':{'city':'杭州','application_date':'2026-11-01'},'provenance':{'kind':'user_authored_synthetic','training_use':'not_used'}})['case']
settings={'name':'Software fixture only','dataset_id':'baseline-unit-v1','purpose':'development','frozen_at':'2026-10-30T08:00:00+00:00'}
run('/api/benchmark/freeze',{**settings,'cases':[new]})
confirmed=copy.deepcopy(new)
confirmed['expected']={'policy_id':new['policy_id'],'conclusion':'insufficient','evidence_ids':[],'materials':[],'missing_fields':[],'explanation':'Software fixture; not an actual human policy judgment.'}
confirmed['review']={'status':'reviewed','reviewer':'software-fixture','reviewed_at':'2026-10-30T08:00:00+00:00'}
dataset=run('/api/benchmark/freeze',{**settings,'cases':[confirmed]})['dataset']
run('/api/benchmark/verify',{'dataset':dataset})
run('/api/benchmark/evaluate',{'dataset':dataset,'predictions':[],'model_name':'Software fixture only','prediction_dataset_sha256':dataset['sha256']})
run('/api/benchmark/evaluate',{'dataset':dataset,'predictions':[],'model_name':'Software fixture only','prediction_dataset_sha256':'wrong'})
practice=copy.deepcopy(draft['cases'][0]);practice.update(expected=confirmed['expected'],review=confirmed['review'])
run('/api/benchmark/freeze',{**settings,'cases':[practice],'purpose':'test','independence_confirmed':True})
run('/api/review/summary',{'cases':[new,confirmed]})
run('/api/sources');run('/api/campaign')
assignment=run('/api/campaign/assignment',{'slot':'A'})['packet']
run('/api/review/restore',assignment)
run('/api/campaign/submit',{'cases':assignment['cases'],'reviewer_id':'software-fixture','independent_confirmed':True,'submitted_at':'2026-10-30T08:00:00+00:00'})
run('/api/campaign/assignment',{'slot':'invalid'})
packets={}
for slot in ('A','B'):
    rows=run('/api/campaign/assignment',{'slot':slot})['packet']['cases']
    for row in rows:
        row['expected']={'policy_id':row['policy_id'],'conclusion':'insufficient','evidence_ids':[],'missing_fields':[],'materials':[],'explanation':'Software parity fixture only, NOT human labels.'}
        row['review']={'status':'reviewed','reviewer':'software-parity-'+slot,'reviewed_at':settings['frozen_at'],'source_checked':True}
    packets[slot.lower()]=run('/api/campaign/submit',{'cases':rows,'reviewer_id':'software-parity-'+slot,'independent_confirmed':True,'submitted_at':settings['frozen_at']})['packet']
run('/api/campaign/compare',packets)
dual=run('/api/campaign/freeze',{**packets,**settings,'adjudicator_id':'software-parity-C','source_checked':True,'independence_confirmed':True,'decisions':[]})['dataset']
run('/api/benchmark/verify',{'dataset':dual})
run('/api/primary/catalogue')
run('/api/primary/search?q=房产交易记录&as_of=2026-11-11')
run('/api/primary/search?q=租房补贴&as_of=2026-10-21&history=1')
run('/api/primary/passage?id=living-guide-2024-p3&q=连续参保')
run('/api/primary/clause?id=rent-eligibility')
run('/api/primary/search?q=x&as_of=bad')
run('/api/primary/search?q=x&as_of=2026-11-11&history=bad')
run('/api/primary/passage?id=not-found')
run('/api/diagnostics/history')
# Clearly synthetic software parity labels; never included in distributed human materials.
import v08_evaluation as v08
run('/api/v08/meta');run('/api/v08/catalogue')
a08=run('/api/v08/assignment',{'slot':'A'})
d08=run('/api/v08/draft',{'slot':'A','records':a08['records'],'reviewer_id':'software-parity-A','saved_at':'2026-11-11T12:00:00+08:00'})
run('/api/v08/restore',{'packet':d08})
run('/api/v08/submit',{'packet':d08,'independent_confirmed':True,'submitted_at':'2026-11-11T12:00:00+08:00'})
s08={}
for slot in ('A','B'):
    ap=v08.assignment(slot)
    for row in ap['records']:
        c=next(c for c in ap['cases'] if c['case_id']==row['case_id'])
        row.update(answer={'screening':'insufficient','qualification':'pending','missing_fields':[],'next_questions':[],'materials':[],'evidence_ids':[c['evidence_probe']['passage_id']],'evidence_support':'not_assessable','evidence_reason':'Software parity fixture only, not human labels.','explanation':'Software parity fixture only, not human labels.'},confirmed=True,source_checked=True,reviewer='software-parity-'+slot,reviewed_at='2026-11-11T12:00:00+08:00')
    packet=v08.draft({'slot':slot,'records':ap['records'],'reviewer_id':'software-parity-'+slot,'saved_at':'2026-11-11T12:00:00+08:00'})
    s08[slot.lower()]=run('/api/v08/submit',{'packet':packet,'independent_confirmed':True,'submitted_at':'2026-11-11T12:00:00+08:00'})
comparison=run('/api/v08/compare',s08)
partial=run('/api/v08/adjudication-draft',{'a':s08['a'],'b':None,'decisions':[],'adjudicator_id':''})
run('/api/v08/restore-adjudication',{'packet':partial})
body08={**s08,'pair_sha256':comparison['pair_sha256'],'adjudicator_id':'software-parity-C','source_checked':True,'independence_confirmed':True,'frozen_at':'2026-11-11T12:00:00+08:00','decisions':[{'case_id':c['case_id'],'choice':'A','reason':'Software parity fixture only, not an actual adjudication.','checked':True} for c in v08.batch()['cases']]}
f08=run('/api/v08/freeze',body08)
run('/api/v08/verify',{'dataset':f08})
run('/api/v08/template',{'dataset':f08})
run('/api/v08/evaluate',{'dataset':f08,'model_name':'Software parity fixture only','dataset_sha256':f08['sha256'],'predictions':[]})
# AI-assisted development protocol: explicitly synthetic software output, never model evidence.
run('/api/ai-review/catalogue')
ai_req=run('/api/ai-review/request',{'case_id':'ai-dev-01'})
ai_p=ai_req['input']['evidence'][0]
ai_row=run('/api/ai-review/import',{'case_id':'ai-dev-01','response':{'protocol':'huicaitong-ai-prereview-v1','case_id':'ai-dev-01','request_sha256':ai_req['request_sha256'],'result':{'judgment':'needs_info','summary':'Software parity fixture only, not an actual AI answer.','missing_fields':[],'next_questions':[],'citations':[{'passage_id':ai_p['id'],'quote':ai_p['text'][:30],'reason':'Software fixture only.'}]}},'model':{'name':'Software fixture only','source':'user_declared_external_model','generated_at':'2026-11-11T12:00:00+08:00'},'imported_at':'2026-11-11T12:00:00+08:00'})
ai_checked=run('/api/ai-review/check',{'record':ai_row,'human_check':{'status':'needs_revision','reviewer':'software-only','checked_at':'2026-11-11T12:00:00+08:00','source_checked':True,'note':'Software fixture only, not a genuine human review.'}})
ai_packet=run('/api/ai-review/packet',{'records':[ai_row,ai_checked],'saved_at':'2026-11-11T12:00:00+08:00'})
run('/api/ai-review/restore',{'packet':ai_packet})
run('/api/ai-review/restore',{'packet':a08})
# v0.8.3 source-time and legacy-input compatibility (software fixtures only).
run('/api/primary/search?q=租房补贴再次取得学历&as_of=2026-11-11')
run('/api/primary/search?q=租房补贴连续参保&as_of=2026-10-21&later_snapshot=1')
run('/api/primary/search?q=租房补贴&as_of=2026-10-21&later_snapshot=bad')
run('/api/primary/passage?id=rent-platform-2026-l92&as_of=2026-10-21')
run('/api/ai-review/context',{'case_id':ai_req['case_id'],'request_sha256':ai_req['request_sha256']})
import ai_prereview as ai_review
legacy=ai_review.legacy_request('ai-dev-09');lp=legacy['input']['evidence'][0]
legacy_row=run('/api/ai-review/import',{'case_id':legacy['case_id'],'response':{'protocol':legacy['protocol'],'case_id':legacy['case_id'],'request_sha256':legacy['request_sha256'],'result':{'judgment':'unable','summary':'Software compatibility fixture only, not an AI policy answer.','missing_fields':[],'next_questions':[],'citations':[{'passage_id':lp['id'],'quote':lp['text'][:30],'reason':'Software fixture only.'}]}},'model':{'name':'SOFTWARE LEGACY FIXTURE','source':'user_declared_external_model','generated_at':'2026-11-11T12:00:00+08:00'},'imported_at':'2026-11-11T12:00:00+08:00'})
run('/api/ai-review/context',{'case_id':legacy_row['case_id'],'request_sha256':legacy_row['request_sha256']})
run('/api/ai-review/context',{'case_id':'ai-dev-09','request_sha256':'0'*64})
legacy_packet=run('/api/ai-review/packet',{'records':[legacy_row],'saved_at':'2026-11-11T12:00:00+08:00'})
run('/api/ai-review/restore',{'packet':legacy_packet})
timed=run('/api/application/assess',{'profile':{'city':'杭州','application_date':'2026-10-21'},'intent':'rent','supplementary':{}})
assert timed['results'][0]['source_time']['documents'][0]['captured_after_reference']
(work/'online-qa-baseline.json').write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
print('Native baseline scenarios:',len(spec))
