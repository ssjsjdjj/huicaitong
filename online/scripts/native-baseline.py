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
(work/'online-qa-baseline.json').write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
print('Native baseline scenarios:',len(spec))
