"""Retrieval/provenance and observable-error tests. Software fixtures are not human gold."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest,zipfile
SITE=Path(__file__).resolve().parent.parent;WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='research-tests-',dir=WORK)).resolve()
assert ROOT.is_relative_to(WORK.resolve())
with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:
    assert all(not Path(x.filename).is_absolute() and '..' not in Path(x.filename).parts for x in z.infolist());z.extractall(ROOT)
sys.path.insert(0,str(ROOT))
import primary_evidence as primary
from diagnostics import analyze
from training.evaluate import evaluate_predictions
from browser_backend import request
from fixtures import BASE
POLICIES=json.loads((ROOT/'data/policies.json').read_text(encoding='utf-8'))['policies'];P=POLICIES[0]
def tasks(labels):
    return [{'case_id':f'unit-{i}','policy_id':P['id'],'profile':BASE,'ground_truth':{'policy_id':P['id'],'conclusion':label,'evidence_ids':[P['clauses'][0]['id']],'materials':[],'missing_fields':[],'explanation':'Software test fixture only, not human policy labels.'}} for i,label in enumerate(labels)]
def predictions(ts,labels):
    return [{'case_id':t['case_id'],'completion':json.dumps({**{k:v for k,v in t['ground_truth'].items() if not k.startswith('allowed_')},'conclusion':label})} for t,label in zip(ts,labels)]
def diagnostic(ts,ps):
    _,ds=evaluate_predictions(ts,ps);return analyze(ts,ps,ds,POLICIES)
class RetrievalTests(unittest.TestCase):
    def test_exact_extracted_substrings_and_fingerprints(self):
        c=primary.corpus();docs={d['id']:d for d in c['documents']}
        for d in docs.values():self.assertEqual(hashlib.sha256((SITE/d['local_url'].lstrip('/')).read_bytes()).hexdigest(),d['source_sha256'])
        for p in c['passages']:
            page=next(pg for pg in docs[p['document_id']]['pages'] if pg['page']==p['page']);self.assertEqual(page['text'][p['start']:p['end']],p['text'])
    def test_scans_and_background_not_claimed_indexed(self):
        c=primary.catalogue();self.assertEqual(c['indexed_documents'],3);self.assertEqual(len(c['excluded_documents']),3);self.assertEqual(c['searchable_passages'],34)
    def test_housing_transaction_history_can_be_found_in_raw_source(self):
        data=primary.search('房产交易记录','2026-11-11');self.assertTrue(any('房产交易记录' in r['text'] for r in data['results'][:3]))
    def test_application_materials_search_returns_exact_source(self):
        data=primary.search('银行卡号申请材料','2026-11-11');self.assertTrue(any(r['document_id']=='living-guide-2024' and r['page']==4 for r in data['results'][:4]))
    def test_historical_qa_is_opt_in(self):
        self.assertFalse(any(r['role']=='historical_qa' for r in primary.search('租房补贴','2026-11-11')['results']))
        self.assertTrue(any(r['role']=='historical_qa' for r in primary.search('房产交易记录','2026-11-11',True,12)['results']))
    def test_capture_is_not_projected_into_past(self):
        data=primary.search('租房补贴','2026-10-21',True,12);self.assertFalse(any(r['document_id']=='rent-platform-2026' for r in data['results']))
        self.assertTrue(any(r['id']=='rent-platform-2026' for r in data['excluded_by_filter']))
    def test_future_guide_is_excluded_even_in_history_mode(self):
        self.assertEqual(primary.search('生活补贴','2020-01-01',True)['results'],[])
    def test_highlighting_is_lossless_plain_text(self):
        text='<script>alert("x")</script>申请家庭房产交易记录 😀';parts=primary.highlight(text,'房产交易记录');self.assertEqual(''.join(p['text'] for p in parts),text);self.assertTrue(any(p['matched'] for p in parts));self.assertTrue(all(set(p)=={'text','matched'} for p in parts))
    def test_table_layout_warning_and_page_anchor_preserved(self):
        p=primary.passage('living-guide-2024-p2','非全日制')['passage'];self.assertTrue(p['layout_note']);self.assertTrue(p['original_file_url'].endswith('#page=2'))
    def test_context_is_entire_page_or_snapshot(self):
        p=next(p for p in primary.corpus()['passages'] if p['document_id']=='rent-platform-2026' and '房产交易记录' in p['text']);d=primary.passage(p['id'],'交易记录');self.assertGreater(len(''.join(x['text'] for x in d['context_parts'])),len(p['text']))
    def test_anchor_mapping_points_to_existing_raw_source(self):
        for p in POLICIES[:3]:
            for c in p['clauses']:self.assertTrue(primary.clause_evidence(c['id'])['results'],c['id'])
    def test_empty_and_unknown_queries_do_not_return_fabricated_answers(self):
        self.assertEqual(primary.search('','2026-11-11')['results'],[]);self.assertEqual(primary.search('ZXQVV12345','2026-11-11')['results'],[])
        with self.assertRaises(ValueError):primary.passage('unknown-id')
    def test_input_validation(self):
        for args in [('x','bad-date'),('x'*4001,'2026-11-11'),('x','2026-02-30')]:
            with self.assertRaises(ValueError):primary.search(*args)
        with self.assertRaises(ValueError):primary.search('x','2026-11-11',limit=50)
    def test_changed_corpus_fails_closed(self):
        path=ROOT/'data/primary-corpus.json';original=path.read_bytes();changed=json.loads(original);changed['passages'][0]['text']='tampered software fixture'
        try:
            path.write_text(json.dumps(changed),encoding='utf-8');primary.corpus.cache_clear()
            with self.assertRaisesRegex(ValueError,'指纹不匹配'):primary.corpus()
        finally:path.write_bytes(original);primary.corpus.cache_clear()
    def test_api_routes_and_invalid_filters(self):
        self.assertEqual(request('/api/primary/catalogue')['status'],200);self.assertEqual(request('/api/primary/search?q=补贴&as_of=2026-11-11')['status'],200);self.assertEqual(request('/api/primary/search?q=x&as_of=2026-11-11&history=bad')['status'],400)
class DiagnosticTests(unittest.TestCase):
    def test_false_pass_distinguishes_ineligible_and_unknown(self):
        ts=tasks(['eligible','ineligible','insufficient']);d=diagnostic(ts,predictions(ts,['eligible']*3));s=d['summary'];self.assertEqual(s['false_pass'],2);self.assertEqual(s['false_pass_from_ineligible'],1);self.assertEqual(s['false_pass_from_insufficient'],1);self.assertEqual(s['pass_precision'],1/3);self.assertEqual(s['reference_nonpass'],2)
    def test_missing_and_supplied_invalid_are_disjoint(self):
        ts=tasks(['eligible','ineligible']);d=diagnostic(ts,[{'case_id':'unit-0','completion':'not json'}]);self.assertEqual(d['summary']['missing_predictions'],1);self.assertEqual(d['summary']['invalid_outputs_supplied'],1);self.assertEqual(d['summary']['false_pass'],0)
    def test_no_denominator_is_undefined_not_fake_zero(self):
        ts=tasks(['eligible']);s=diagnostic(ts,[])['summary'];self.assertIsNone(s['false_pass_rate']);self.assertIsNone(s['pass_precision'])
    def test_correct_conclusion_still_exposes_field_errors(self):
        ts=tasks(['ineligible']);ts[0]['ground_truth']['allowed_evidence_ids']=[c['id'] for c in P['clauses']];ps=predictions(ts,['ineligible']);p=json.loads(ps[0]['completion']);p['evidence_ids']=[P['clauses'][1]['id']];ps[0]['completion']=json.dumps(p);d=diagnostic(ts,ps);self.assertIn('evidence_ids',d['cases'][0]['categories']);self.assertEqual(d['summary']['false_pass'],0)
    def test_all_wrong_conclusion_directions_are_classified(self):
        ts=tasks(['eligible','eligible','ineligible','insufficient']);d=diagnostic(ts,predictions(ts,['ineligible','insufficient','insufficient','ineligible']));cats=d['summary']['category_counts'];self.assertTrue(all(cats[k]==1 for k in ('false_reject','unnecessary_abstention','missed_rejection','premature_reject')))
    def test_actual_raw_output_and_reference_are_kept(self):
        ts=tasks(['eligible']);ps=predictions(ts,['eligible']);row=diagnostic(ts,ps)['cases'][0];self.assertEqual(row['raw_output'],ps[0]['completion']);self.assertEqual(row['reference'],ts[0]['ground_truth'])
    def test_history_numbers_reproduce_saved_report(self):
        h=request('/api/diagnostics/history')['data'];s=h['diagnostics']['summary'];self.assertEqual(s['cases'],92);self.assertEqual(s['false_pass'],24);self.assertEqual(s['false_pass_from_ineligible'],22);self.assertEqual(s['false_pass_from_insufficient'],2);self.assertEqual(s['predicted_pass'],36);self.assertEqual(s['correct_pass'],12);self.assertEqual(h['metrics']['confusion_matrix'],s['confusion_matrix'])
    def test_reserved_54_remain_unannotated(self):
        batch=json.loads((ROOT/'data/review-campaign.json').read_text(encoding='utf-8'));self.assertTrue(all(r['expected'] is None and r['review']['status']=='pending' for r in batch['cases']));self.assertTrue(set(r['case_id'] for r in batch['cases']).isdisjoint(r['case_id'] for r in request('/api/diagnostics/history')['data']['diagnostics']['cases']))
if __name__=='__main__':unittest.main(verbosity=1)
