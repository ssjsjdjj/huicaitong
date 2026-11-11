"""Software fixtures only: no actual model answers or human reference labels."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest,zipfile
SITE=Path(__file__).resolve().parent.parent;WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='ai-prereview-tests-',dir=WORK))
with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:z.extractall(ROOT)
sys.path.insert(0,str(ROOT))
import ai_prereview as ai
from browser_backend import request
from human_evaluation import known_profiles,profile_hash,provenance

NOW='2026-11-11T12:00:00+08:00'
class PreReview(unittest.TestCase):
    def setUp(self):
        self.req=ai.request('ai-dev-01');p=self.req['input']['evidence'][0]
        self.response={'protocol':ai.PROTOCOL,'case_id':'ai-dev-01','request_sha256':self.req['request_sha256'],'result':{'judgment':'needs_info','summary':'软件测试输出，不是模型实际回答或人工参考。','missing_fields':['extra.graduation_record_precision'],'next_questions':['请核对毕业记录日期精度。'],'citations':[{'passage_id':p['id'],'quote':p['text'][:30],'reason':'软件流程测试引用，不是已核验政策判断。'}]}}
        self.body={'case_id':'ai-dev-01','response':self.response,'model':{'name':'SOFTWARE TEST FIXTURE ONLY','generated_at':NOW,'source':'user_declared_external_model'},'imported_at':NOW}
    def row(self):return ai.import_response(self.body)
    def packet(self,rows=None):return ai.packet({'records':rows or [self.row()],'saved_at':NOW})
    def check(self,row=None,status='checked_with_ai'):
        return ai.check({'record':row or self.row(),'human_check':{'status':status,'reviewer':'software-checker','checked_at':NOW,'source_checked':True,'note':'软件测试核查记录，不是人工参考。'}})
    def test_blank_development_inputs(self):
        c=ai.catalogue();self.assertEqual(len(c['cases']),12);self.assertTrue(all(x['expected'] is None for x in c['cases']));self.assertFalse(c['online_inference'])
    def test_no_reserved_profiles(self):
        blocked=set(ai.read('v08-reserved-profiles.json')['profile_sha256']);self.assertFalse(blocked & {profile_hash(c['profile']) for c in ai.batch()['cases']})
    def test_no_reserved_tasks_in_requests(self):
        for c in ai.batch()['cases']:
            req=ai.request(c['case_id']);self.assertEqual(req['input']['case']['case_id'],c['case_id']);self.assertNotIn('review-v08',req['prompt_text']);self.assertTrue(req['input']['evidence']);self.assertTrue(all(p['id'].startswith('rent-platform-2026' if c['intent']=='rent' else 'living-guide-2024') for p in req['input']['evidence']))
    def test_hash_binds_input(self):self.assertEqual(self.req['request_sha256'],ai.digest(self.req['input']))
    def test_request_deterministic(self):self.assertEqual(ai.request('ai-dev-01'),self.req)
    def test_reject_reserved_case(self):
        with self.assertRaises(ValueError):ai.request('v08-any')
    def test_import_defaults_unreviewed(self):
        r=self.row();self.assertIsNone(r['human_check']);self.assertTrue(r['citation_checks'][0]['quote_matches'])
    def test_model_is_required(self):
        self.body['model']['name']='';self.assertEqual(request('/api/ai-review/import',self.body)['status'],400)
    def test_model_source_required(self):
        self.body['model']['source']='verified';self.assertEqual(request('/api/ai-review/import',self.body)['status'],400)
    def test_timestamp_requires_timezone(self):
        self.body['model']['generated_at']='2026-11-11T12:00:00';self.assertEqual(request('/api/ai-review/import',self.body)['status'],400)
    def test_wrong_case(self):
        self.response['case_id']='ai-dev-02';self.assertEqual(request('/api/ai-review/import',self.body)['status'],400)
    def test_wrong_context(self):
        self.response['request_sha256']='0'*64;self.assertEqual(request('/api/ai-review/import',self.body)['status'],400)
    def test_unknown_fields_rejected(self):
        self.response['result']['expected']={};self.assertEqual(request('/api/ai-review/import',self.body)['status'],400)
    def test_unknown_missing_field(self):
        self.response['result']['missing_fields']=['passport'];self.assertEqual(request('/api/ai-review/import',self.body)['status'],400)
    def test_wrong_quote_is_visible(self):
        self.response['result']['citations'][0]['quote']='软件虚构引文-not-in-source';self.assertFalse(self.row()['citation_checks'][0]['quote_matches'])
    def test_unknown_citation_is_visible(self):
        self.response['result']['citations'][0]['passage_id']='not-found';self.assertFalse(self.row()['citation_checks'][0]['found'])
    def test_bad_quote_cannot_be_checked(self):
        self.response['result']['citations'][0]['quote']='软件虚构引文-not-in-source'
        with self.assertRaises(ValueError):self.check()
    def test_bad_quote_can_be_needs_revision(self):
        self.response['result']['citations'][0]['passage_id']='not-found';self.assertEqual(self.check(status='needs_revision')['human_check']['status'],'needs_revision')
    def test_no_citation_not_checked(self):
        self.response['result']['citations']=[]
        with self.assertRaises(ValueError):self.check()
    def test_no_citation_can_be_unable(self):
        self.response['result']['citations']=[];self.assertEqual(self.check(status='unable_to_verify')['human_check']['status'],'unable_to_verify')
    def test_check_keeps_model_response(self):
        row=self.row();checked=self.check(row);self.assertEqual(row['response'],checked['response']);self.assertIsNone(row['human_check'])
    def test_check_requires_real_inputs(self):
        for key,value in [('reviewer',''),('source_checked',False),('note','短')]:
            checked=self.check();checked['human_check'][key]=value
            with self.assertRaises(ValueError):ai.checked_record(checked)
    def test_new_response_resets_human_check(self):self.check();self.assertIsNone(self.row()['human_check'])
    def test_packet_is_development_only(self):
        p=self.packet();self.assertEqual(p['purpose'],'development_only');self.assertFalse(p['independent_human_reference']);self.assertNotIn('dataset',p)
    def test_restore_roundtrip(self):
        p=self.packet([self.row(),self.check()]);self.assertEqual(ai.restore({'packet':p}),p)
    def test_restore_refuses_human_protocol(self):
        with self.assertRaises(ValueError):ai.restore({'packet':{'protocol':'huicaitong-v08-human-v1','type':'v08_assignment'}})
    def test_tampered_packet(self):
        p=self.packet();p['records'][0]['model']['name']='tampered'
        with self.assertRaises(ValueError):ai.restore({'packet':p})
    def test_forged_purpose_even_when_resigned(self):
        p=self.packet();p['independent_human_reference']=True;p['sha256']=ai.digest({k:v for k,v in p.items() if k!='sha256'})
        with self.assertRaises(ValueError):ai.restore({'packet':p})
    def test_recomputes_citation_checks(self):
        row=self.row();row['citation_checks'][0]['quote_matches']=False
        with self.assertRaises(ValueError):ai.checked_record(row)
    def test_limits_and_duplicates(self):
        for rows in ([self.row()]*241,[self.row(),self.row()]):
            with self.assertRaises(ValueError):ai.packet({'records':rows,'saved_at':NOW})
    def test_download_remains_importable_within_size_limit(self):
        self.response['result']['summary']='测'*4000
        citation=self.response['result']['citations'][0];citation['reason']='测'*2000
        self.response['result']['citations']=[copy.deepcopy(citation) for _ in range(8)]
        rows=[]
        for i in range(80):
            self.body['model']['name']='software-size-fixture-'+str(i);rows.append(self.row())
        with self.assertRaisesRegex(ValueError,'4MB'):ai.packet({'records':rows,'saved_at':NOW})
    def test_human_protocol_rejects_ai_prefix(self):
        with self.assertRaises(ValueError):provenance({'case_id':'ai-dev-01','provenance':{'kind':'user_authored_synthetic','training_use':'not_used'}})
    def test_ai_profiles_are_known_development(self):
        known=set(known_profiles()['profile_sha256']);self.assertTrue(all(profile_hash(c['profile']) in known for c in ai.batch()['cases']))
    def test_reserved_hash_and_answers_unchanged(self):
        raw=(SITE/'data/review-v08.json').read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),'3e8ab7b9f4bbc9602b78c49c7c84fa083fcab2465000fb4b8b2067902fe6aca1');self.assertEqual(json.loads(raw)['sha256'],'c4f496e4fa399e8c5374a6c74c661c99cf76d8c9ffbccb823c810672819d425f');self.assertTrue(all(c['expected'] is None for c in json.loads(raw)['cases']))
    def test_material_pack_unchanged(self):
        self.assertEqual(hashlib.sha256((SITE/'.work/huicaitong-v08-review-materials.zip').read_bytes()).hexdigest(),'ed48fac829de3e3588aba74a5c2b65454f3f27aef0a317ea9155da11c11a3b2d')
    def test_all_new_routes(self):
        self.assertEqual(request('/api/ai-review/catalogue')['status'],200)
        for route,body in [('request',{'case_id':'ai-dev-01'}),('import',self.body),('packet',{'records':[self.row()],'saved_at':NOW}),('restore',{'packet':self.packet()}),('check',{'record':self.row(),'human_check':self.check()['human_check']})]:self.assertEqual(request('/api/ai-review/'+route,body)['status'],200)
    def test_bad_requests_are_client_errors(self):
        self.assertEqual(request('/api/ai-review/request',{'case_id':[]})['status'],400);self.assertEqual(request('/api/ai-review/import',{})['status'],400)

if __name__=='__main__':unittest.main()
