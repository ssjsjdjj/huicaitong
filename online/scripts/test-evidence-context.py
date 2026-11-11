"""Coverage/time/legacy compatibility tests; all answer fixtures are software only."""
from pathlib import Path
import copy,json,sys,tempfile,unittest,zipfile,hashlib
SITE=Path(__file__).resolve().parent.parent;WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='context-tests-',dir=WORK))
with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:z.extractall(ROOT)
sys.path.insert(0,str(ROOT))
import evidence_context as ec
import primary_evidence as primary
import ai_prereview as ai
from browser_backend import request

NOW='2026-11-11T12:00:00+08:00'
class ContextTests(unittest.TestCase):
    def query(self,q,date='2026-11-11',**kw):return ec.search(q,date,limit=8,**kw)
    def ids(self,data):return [r['id'] for r in data['results']]
    def old_row(self):
        req=ai.legacy_request('ai-dev-09');new_ids={p['id'] for p in ai.request('ai-dev-09')['input']['evidence']}
        p=next(p for p in req['input']['evidence'] if p['id'] not in new_ids)
        response={'protocol':ai.PROTOCOL,'case_id':req['case_id'],'request_sha256':req['request_sha256'],'result':{'judgment':'unable','summary':'SOFTWARE FIXTURE ONLY, not an actual model answer.','missing_fields':[],'next_questions':[],'citations':[{'passage_id':p['id'],'quote':p['text'][:30],'reason':'Software compatibility fixture only.'}]}}
        return ai.import_response({'case_id':req['case_id'],'response':response,'model':{'name':'SOFTWARE LEGACY FIXTURE ONLY','source':'user_declared_external_model','generated_at':NOW},'imported_at':NOW})
    def test_short_clause_index_adds_eight_not_contact_entries(self):
        meta=ec.catalogue();self.assertEqual(meta['searchable_passages'],34);self.assertEqual(meta['additional_short_passages'],8);self.assertEqual(meta['total_searchable_passages'],42)
    def test_reacquired_degree_is_found(self):
        d=self.query('租房补贴 已享受 更高学历 申请条件');self.assertIn('rent-platform-2026-l32',self.ids(d)[:3]);r=next(r for r in d['results'] if r['id'].endswith('-l32'));self.assertTrue(r['critical_short_clause']);self.assertIn('不纳入',r['text'])
    def test_paraphrase_reacquired_degree(self):self.assertEqual(self.ids(self.query('毕业后又取得硕士还能重新申请房补吗'))[0],'rent-platform-2026-l32')
    def test_insurance_and_window_both_present(self):
        d=self.query('租房补贴 社保 连续参保 补缴');self.assertTrue({'rent-platform-2026-l50','rent-platform-2026-l68'}<=set(self.ids(d)))
    def test_employed_degree_exclusion(self):self.assertIn('rent-platform-2026-l34',self.ids(self.query('在职取得学历可以领租房补贴吗'))[:3])
    def test_housing_benefit_overlap_short_clause(self):self.assertIn('rent-platform-2026-l36',self.ids(self.query('租房补贴和公租房同时享受吗')))
    def test_qualified_employers(self):self.assertTrue({'rent-platform-2026-l54','rent-platform-2026-l56','rent-platform-2026-l58'}<=set(self.ids(self.query('租房补贴企业税务行政事业单位条件'))))
    def test_declared_start_is_searchable(self):self.assertEqual(self.ids(self.query('租房补贴细则施行日期'))[0],'rent-platform-2026-l92')
    def test_clause_lookup_includes_previously_missing_exclusions(self):
        d=ec.clause_evidence('rent-eligibility');self.assertTrue({'rent-platform-2026-l40','rent-platform-2026-l48','rent-platform-2026-l32','rent-platform-2026-l34'}<=set(self.ids(d)))
    def test_clause_api_time_includes_original_and_extra_locators(self):
        d=request('/api/primary/clause?id=rent-time');self.assertEqual(d['status'],200);self.assertTrue({'rent-platform-2026-l50','rent-platform-2026-l68','rent-platform-2026-l92'}<=set(self.ids(d['data'])))
    def test_strict_reference_excludes_later_capture(self):
        d=self.query('租房补贴再次取得学历','2026-10-21');self.assertEqual(d['results'],[]);self.assertTrue(any(x['id']==ec.RENT for x in d['excluded_by_filter']))
    def test_history_does_not_implicitly_allow_later_capture(self):self.assertFalse(any(r['document_id']==ec.RENT for r in self.query('租房补贴','2026-10-21',include_history=True)['results']))
    def test_explicit_later_capture_is_only_a_clue(self):
        d=self.query('租房补贴再次取得学历','2026-10-21',include_later_capture=True);self.assertIn('rent-platform-2026-l32',self.ids(d));self.assertTrue(all(r['temporal']['captured_after_reference'] and r['temporal']['applicability']=='unverified' for r in d['results']))
    def test_issued_future_pdf_still_excluded_with_later_capture_option(self):self.assertFalse(any(r['document_id']=='living-guide-2024' for r in self.query('生活补贴','2020-01-01',include_later_capture=True)['results']))
    def test_declared_start_not_claimed_verified(self):
        t=ec.policy_time('hz-rent-first-2026','2026-10-21')['documents'][0];self.assertEqual(t['declared_effective_from'],'2021-10-15');self.assertIsNone(t['published_on']);self.assertEqual(t['captured_on'],'2026-10-30');self.assertFalse(t['effective_period_verified']);self.assertIn('后续补充',''.join(t['warnings']))
    def test_later_reference_does_not_verify_effect(self):
        t=ec.policy_time('hz-rent-first-2026','2026-11-11')['documents'][0];self.assertFalse(t['captured_after_reference']);self.assertEqual(t['applicability'],'unverified')
    def test_pdf_checked_on_is_not_publication_or_capture(self):
        t=ec.policy_time('hz-living-first-2024','2026-10-21')['documents'][0];self.assertEqual(t['published_on'],'2024-05-13');self.assertEqual(t['source_checked_on'],'2026-10-30');self.assertIsNone(t['captured_on']);self.assertFalse(t['captured_after_reference'])
    def test_custom_policy_does_not_inherit_stock_dates(self):self.assertTrue(ec.policy_time('hz-custom-example','2026-10-21')['unbound_source'])
    def test_empty_and_unknown_query(self):
        for q in ('','ZXQVV12345'):self.assertEqual(self.query(q)['results'],[])
    def test_exact_original_text_and_offsets_preserved(self):
        c=primary.corpus();allp={p['id']:p for p in c['passages']}
        for q in ('租房补贴再次取得学历','租房补贴企业单位条件','租房补贴生效日','租房补贴参保要求'):
            for r in self.query(q)['results']:
                self.assertEqual(r['text'],allp[r['id']]['text']);self.assertEqual(r['source_sha256'],next(d for d in c['documents'] if d['id']==r['document_id'])['source_sha256'])
    def test_rent_core_all_four_development_requests(self):
        for i in range(9,13):
            req=ai.request(f'ai-dev-{i:02}');self.assertTrue({'rent-platform-2026-l32','rent-platform-2026-l50','rent-platform-2026-l68','rent-platform-2026-l92'}<={p['id'] for p in req['input']['evidence']});self.assertEqual(req['input']['retrieval']['reference_date'],'2026-10-21');self.assertEqual(req['input']['retrieval']['input_version'],2)
    def test_prompt_carries_time_limits(self):
        req=ai.request('ai-dev-11');self.assertIn('取证日',req['messages'][0]['content']);self.assertTrue(req['input']['retrieval']['temporal_context']['documents'][0]['captured_after_reference'])
    def test_legacy_twelve_fingerprints_are_exact(self):
        hashes=json.loads((SITE/'scripts/fixtures/ai-v082-request-hashes.json').read_text(encoding='utf-8'))
        for cid,sha in hashes.items():self.assertEqual(ai.legacy_request(cid)['request_sha256'],sha);self.assertNotEqual(ai.request(cid)['request_sha256'],sha)
    def test_legacy_roundtrip_does_not_rebind(self):
        row=self.old_row();p=ai.packet({'records':[row],'saved_at':NOW});self.assertEqual(ai.restore({'packet':p}),p);self.assertEqual(p['records'][0]['request_sha256'],ai.legacy_request('ai-dev-09')['request_sha256'])
    def test_legacy_quote_uses_its_own_input(self):
        row=self.old_row();ctx=ai.context(row);self.assertFalse(ctx['is_current']);self.assertEqual(ctx['input_version'],1);self.assertEqual(ctx['request']['request_sha256'],row['request_sha256']);self.assertTrue(row['citation_checks'][0]['quote_matches'])
    def test_existing_historical_human_check_is_preserved(self):
        row=self.old_row();row['human_check']={'status':'checked_with_ai','reviewer':'SOFTWARE ONLY','checked_at':NOW,'source_checked':True,'note':'Software-only historical status fixture.'};self.assertEqual(ai.checked_record(row),row)
    def test_new_confirm_on_legacy_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'历史输入'):ai.check({'record':self.old_row(),'human_check':{'status':'checked_with_ai','reviewer':'SOFTWARE ONLY','checked_at':NOW,'source_checked':True,'note':'Software-only attempted new confirmation.'}})
    def test_unknown_hash_not_accepted_as_legacy(self):
        with self.assertRaises(ValueError):ai.context({'case_id':'ai-dev-09','request_sha256':'0'*64})
    def test_new_context_version_is_two(self):
        req=ai.request('ai-dev-09');ctx=ai.context(req);self.assertTrue(ctx['is_current']);self.assertEqual(ctx['input_version'],2)
    def test_mixed_old_and_current_history(self):
        row=self.old_row();req=ai.request('ai-dev-09');p=req['input']['evidence'][0];body=copy.deepcopy(row);body['response']['request_sha256']=req['request_sha256'];body['response']['result']['citations']=[{'passage_id':p['id'],'quote':p['text'][:30],'reason':'Software fixture only.'}];new=ai.import_response(body);packet=ai.packet({'records':[row,new],'saved_at':NOW});self.assertEqual(ai.restore({'packet':packet}),packet)
    def test_api_flags_and_primary_context(self):
        for url in ('/api/primary/search?q=租房补贴&as_of=2026-10-21&later_snapshot=1','/api/primary/passage?id=rent-platform-2026-l32&as_of=2026-10-21'):
            data=request(url);self.assertEqual(data['status'],200);self.assertEqual(data['data']['temporal_context']['reference_date'],'2026-10-21')
        self.assertEqual(request('/api/primary/search?q=租房&as_of=2026-10-21&later_snapshot=bad')['status'],400)
    def test_invalid_dates_and_options(self):
        for args in [('租房','2026-02-30'),('x'*4001,'2026-10-21')]:
            with self.assertRaises(ValueError):ec.search(*args)
        for kw in ({'include_later_capture':'1'},{'coverage':'fake'},{'document_id':'fake'}):
            with self.assertRaises(ValueError):self.query('租房',**kw)
    def test_reserved_source_batch_and_materials_unchanged(self):
        self.assertEqual(hashlib.sha256((SITE/'data/review-v08.json').read_bytes()).hexdigest(),'3e8ab7b9f4bbc9602b78c49c7c84fa083fcab2465000fb4b8b2067902fe6aca1');self.assertEqual(hashlib.sha256((SITE/'.work/huicaitong-v08-review-materials.zip').read_bytes()).hexdigest(),'ed48fac829de3e3588aba74a5c2b65454f3f27aef0a317ea9155da11c11a3b2d');self.assertEqual(primary.corpus()['sha256'],'6188b39712384697534fd5e7cfee56696d508b8f6b5ed8a8c839bea0cbc5c304')

if __name__=='__main__':unittest.main()
