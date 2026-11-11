"""Author a separate development-only batch; never inspect or change reserved inputs."""
import json,sys
from pathlib import Path
SITE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(SITE.parent if (SITE.parent/'app.py').is_file() else SITE.parent/'huicaitong'));sys.path.insert(0,str(SITE))
from human_evaluation import profile_hash,digest
from core import validate_profile

base={'city':'杭州','degree':'master','study_mode':'fulltime','school_region':'mainland','nationality':'cn','graduation_date':'2025-05-13','application_date':'2026-10-21','insurance_start_date':'2025-07-01','insurance_months':14,'employed_hangzhou':True,'employer_qualified':True,'insurance_current':True,'insurance_without_backpay':True,'prior_other_degree_subsidy':False,'degree_while_employed':False,'first_installment_received':False,'family_has_home':False,'other_housing_benefit':False,'rent_first_received':False}
supp={'graduation_record_precision':'day','has_dispatch_history':False,'family_scope_confirmed':True,'housing_scope_confirmed':True,'family_property_history':False,'prior_rent_degree_subsidy':False}
design=[
 ('living-first','毕业记录信息待核对',{'insurance_months':13},{'graduation_record_precision':'unknown'},'生活补贴 毕业时间 年月 申请材料'),
 ('living-first','有派遣工作经历',{'insurance_months':12},{'has_dispatch_history':True},'生活补贴 劳务派遣 实际用工单位 申请材料'),
 ('living-first','部分参保信息未填写',{'insurance_current':None,'insurance_months':None},{},'生活补贴 连续参保 补缴 单位'),
 ('living-first','国境外学习经历',{'school_region':'overseas','insurance_months':11},{},'生活补贴 国境外 学历认证 申请材料'),
 ('living-second','首笔领取记录待确认',{'first_installment_received':None,'insurance_months':10},{},'生活补贴 第二笔 首笔 申请时间'),
 ('living-second','当前参保存在待核项',{'first_installment_received':True,'insurance_current':None,'insurance_months':9},{},'生活补贴 第二笔 连续参保 申请条件'),
 ('living-second','曾以其他学历领取补贴',{'first_installment_received':True,'prior_other_degree_subsidy':True,'insurance_months':8},{},'生活补贴 其他学历 已享受 第二笔'),
 ('living-second','连续时长含待确认记录',{'first_installment_received':True,'insurance_without_backpay':None,'insurance_months':7},{},'生活补贴 第二笔 连续缴纳 补缴'),
 ('rent','家庭核验范围待确认',{'insurance_months':6},{'family_scope_confirmed':None},'租房补贴 申请人 配偶 未成年子女 住房'),
 ('rent','存在家庭房产交易历史',{'insurance_months':5},{'family_property_history':True},'租房补贴 房产交易 买卖 赠与 继承'),
 ('rent','曾领取后又取得新学历',{'insurance_months':4},{'prior_rent_degree_subsidy':True},'租房补贴 已享受 更高学历 申请条件'),
 ('rent','住房地域口径待核对',{'insurance_months':3},{'housing_scope_confirmed':None},'租房补贴 单位所在区 主城区 住房范围'),
]
cases=[]
for i,(intent,title,changes,extra,query) in enumerate(design,1):
    p={**base,**changes};e={**supp,**extra};validate_profile(p)
    cases.append({'case_id':f'ai-dev-{i:02}','title':title,'intent':intent,'profile':p,'supplementary':e,'query':query,'expected':None,'provenance':{'kind':'project_authored_synthetic_ai_development','training_use':'development_only','independent_human_reference':False}})
blocked=set(json.loads((SITE/'data/v08-reserved-profiles.json').read_text(encoding='utf-8'))['profile_sha256'])
blocked.update(profile_hash(r['profile']) for r in json.loads((SITE/'data/review-campaign.json').read_text(encoding='utf-8'))['cases'])
assert not blocked.intersection(profile_hash(c['profile']) for c in cases)
assert len({profile_hash(c['profile']) for c in cases})==len(cases)
b={'protocol':'huicaitong-ai-prereview-v1','batch_id':'hz-ai-development-12-v1','purpose':'development_only','cases':cases};b['sha256']=digest(b)
target=SITE/'data/ai-prereview-development.json'
data=(json.dumps(b,ensure_ascii=False,indent=2)+'\n').encode()
if target.exists() and target.read_bytes()!=data:raise RuntimeError('开发批次已存在且内容不同，请创建新版本，不要覆盖既有记录')
target.write_bytes(data)
print('Created 12 answer-free development inputs; reserved profile fingerprints excluded.')
