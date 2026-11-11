"""Software fixtures ONLY. Never write these answers into shipped human task packs."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest,zipfile
SITE=Path(__file__).resolve().parent.parent;WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='v08-software-tests-',dir=WORK)).resolve()
with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:
    assert all(not Path(i.filename).is_absolute() and '..' not in Path(i.filename).parts for i in z.infolist());z.extractall(ROOT)
sys.path.insert(0,str(ROOT))
import v08_evaluation as v
from browser_backend import request
STAMP='2026-11-11T12:00:00+08:00'

def fixture_answer(c):return {'screening':'insufficient','qualification':'pending','missing_fields':[],'next_questions':[],'materials':[],'evidence_ids':[c['evidence_probe']['passage_id']],'evidence_support':'not_assessable','evidence_reason':'Software fixture only, not a human evidence judgment.','explanation':'Software fixture only, not a human policy judgment.'}
def fixture_draft(slot='A',complete=True):
    p=v.assignment(slot);cs={c['case_id']:c for c in p['cases']};rows=p['records']
    for r in rows:
        if complete:r.update(answer=fixture_answer(cs[r['case_id']]),confirmed=True,source_checked=True,reviewer='software-fixture-'+slot,reviewed_at=STAMP)
    return v.draft({'slot':slot,'reviewer_id':'software-fixture-'+slot,'records':rows,'saved_at':STAMP})
def fixture_submission(slot='A'):return v.submit({'packet':fixture_draft(slot),'independent_confirmed':True,'submitted_at':STAMP})
def fixture_body():
    body={'a':fixture_submission('A'),'b':fixture_submission('B'),'adjudicator_id':'software-fixture-C','source_checked':True,'independence_confirmed':True,'frozen_at':STAMP}
    body['pair_sha256']=v.compare(body)['pair_sha256'];body['decisions']=[{'case_id':c['case_id'],'choice':'A','reason':'Software fixture only; not an actual adjudication.','checked':True} for c in v.batch()['cases']]
    return body
class Tests(unittest.TestCase):
    def test_60_blank_new_cases_and_balanced_task_counts(self):
        b=v.check_batch(v.batch());self.assertEqual(b['audit']['blank_answers'],60);self.assertEqual(sorted(b['audit']['policy_tasks'].values()),[20,20,20]);self.assertTrue(all(c['expected'] is None for c in b['cases']))
    def test_engine_matches_v08_application_snapshot(self):self.assertEqual(v.batch()['engine_sha256'],hashlib.sha256((ROOT/'application_flow.py').read_bytes()).hexdigest())
    def test_old54_fingerprint_and_answers_retained(self):
        b=json.loads((ROOT/'data/review-campaign.json').read_text(encoding='utf-8'));self.assertEqual(b['sha256'],'abac6cf9b139f6353e42f303de4140932aaa963dcd5b4676cac069ccecd3d4b6');self.assertTrue(all(c['expected'] is None for c in b['cases']))
    def test_assignment_orders_are_distinct_and_labels_blank(self):
        a,b=v.assignment('A'),v.assignment('B');self.assertNotEqual([c['case_id'] for c in a['cases']],[c['case_id'] for c in b['cases']]);self.assertEqual({c['case_id'] for c in a['cases']},{c['case_id'] for c in b['cases']});self.assertTrue(all(r['answer'] is None and not r['confirmed'] for r in a['records']+b['records']))
    def test_assignment_tamper_rejected(self):
        p=v.assignment('A');p['cases'][0]['supplementary']['has_dispatch_history']=True
        with self.assertRaises(ValueError):v.restore(p)
    def test_input_binding_cannot_be_replaced_in_notes(self):
        p=fixture_draft(complete=False);p['records'][0]['input_sha256']='0'*64
        with self.assertRaises(ValueError):v.draft(p)
    def test_partial_notes_restore_without_confirming(self):
        p=fixture_draft(complete=False);a={k:[] if k in v.LISTS else '' for k in v.KEYS};a['explanation']='unconfirmed note';p['records'][0]['answer']=a;p=v.draft(p);r=v.restore(p);self.assertEqual(r['records'][0]['answer']['explanation'],'unconfirmed note');self.assertFalse(r['records'][0]['confirmed'])
    def test_unconfirmed_cannot_retain_a_person_or_timestamp(self):
        p=fixture_draft(complete=False);p['records'][0]['reviewer']='stale'
        with self.assertRaises(ValueError):v.draft(p)
    def test_pending_cannot_submit(self):
        with self.assertRaises(ValueError):v.submit({'packet':fixture_draft(complete=False),'independent_confirmed':True,'submitted_at':STAMP})
    def test_review_requires_reading_and_reasons(self):
        p=fixture_draft();p['records'][0]['source_checked']=False
        with self.assertRaises(ValueError):v.draft(p)
        p=fixture_draft();p['records'][0]['answer']['evidence_reason']=''
        with self.assertRaises(ValueError):v.draft(p)
    def test_unknown_fields_or_source_refs_rejected(self):
        p=fixture_draft();p['records'][0]['answer']['missing_fields']=['identity_number']
        with self.assertRaises(ValueError):v.draft(p)
        p=fixture_draft();p['records'][0]['answer']['evidence_ids']=['invented']
        with self.assertRaises(ValueError):v.draft(p)
    def test_duplicate_record_rejected(self):
        p=fixture_draft();p['records'][1]=copy.deepcopy(p['records'][0])
        with self.assertRaises(ValueError):v.draft(p)
    def test_whole_batch_is_required(self):
        p=fixture_draft();p['records'].pop()
        with self.assertRaises(ValueError):v.draft(p)
    def test_global_reviewer_change_does_not_relabel_past_work(self):
        p=fixture_draft();p['reviewer_id']='different-person';p=v.draft(p)
        with self.assertRaises(ValueError):v.submit({'packet':p,'independent_confirmed':True,'submitted_at':STAMP})
    def test_independent_declaration_required(self):
        with self.assertRaises(ValueError):v.submit({'packet':fixture_draft(),'independent_confirmed':False,'submitted_at':STAMP})
    def test_cross_batch_and_old_files_rejected(self):
        p=fixture_draft();p['batch_sha256']='0'*64;p=v.signed({k:x for k,x in p.items() if k!='sha256'})
        with self.assertRaises(ValueError):v.restore(p)
        with self.assertRaises(ValueError):v.restore({'schema_version':1,'cases':[]})
    def test_same_person_and_wrong_slots_rejected(self):
        a=fixture_submission();b=fixture_submission('B');b['reviewer_id']=a['reviewer_id']
        for r in b['records']:r['reviewer']=a['reviewer_id']
        b=v.signed({k:x for k,x in b.items() if k!='sha256'})
        with self.assertRaises(ValueError):v.compare({'a':a,'b':b})
        with self.assertRaises(ValueError):v.compare({'a':a,'b':a})
    def test_third_person_and_all_60_decisions_required(self):
        body=fixture_body();body['adjudicator_id']=body['a']['reviewer_id']
        with self.assertRaises(ValueError):v.freeze(body)
        body=fixture_body();body['decisions'].pop()
        with self.assertRaises(ValueError):v.freeze(body)
    def test_unchanged_answers_still_require_explicit_adjudication(self):
        body=fixture_body();body['decisions'][0]['checked']=False
        with self.assertRaises(ValueError):v.freeze(body)
    def test_changed_pair_blocks_stale_decisions(self):
        body=fixture_body();body['pair_sha256']='0'*64
        with self.assertRaises(ValueError):v.freeze(body)
        with self.assertRaises(ValueError):v.adjudication_draft(body)
    def test_partial_adjudication_roundtrip_keeps_sources(self):
        p=v.adjudication_draft({'a':fixture_submission(),'b':None,'decisions':[],'adjudicator_id':''});self.assertIsNone(v.restore_adjudication(p)['b'])
    def test_partial_and_complete_decisions_restore_with_their_pair(self):
        body=fixture_body();body['decisions']=body['decisions'][:1];p=v.adjudication_draft(body);self.assertEqual(len(v.restore_adjudication(p)['decisions']),1)
        body=fixture_body();p=v.adjudication_draft(body);self.assertEqual(len(v.restore_adjudication(p)['decisions']),60)
    def test_frozen_audit_is_self_contained_and_tamper_checked(self):
        d=v.freeze(fixture_body());self.assertEqual(len(v.verify_dataset(d)['cases']),60);d['cases'][0]['expected']['screening']='conditions_met';d=v.signed({k:x for k,x in d.items() if k!='sha256'})
        with self.assertRaises(ValueError):v.verify_dataset(d)
    def test_probe_quote_must_be_original_substring(self):
        b=v.batch();b['cases'][0]['evidence_probe']['quote']='invented quote';b['cases'][0]['input_sha256']=v.digest(v.input_of(b['cases'][0]));b=v.signed({k:x for k,x in b.items() if k!='sha256'})
        with self.assertRaises(ValueError):v.check_batch(b)
    def test_template_never_contains_human_answers(self):
        t=v.prediction_input(v.freeze(fixture_body()));self.assertNotIn('expected',json.dumps(t));self.assertTrue(all(set(r)=={'case_id','policy_id','intent','profile','supplementary','evidence_probe'} for r in t['requests']))
    def test_missing_and_invalid_predictions_keep_denominator(self):
        d=v.freeze(fixture_body());r=v.evaluate({'dataset':d,'model_name':'Software fixture only','dataset_sha256':d['sha256'],'predictions':[{'case_id':d['cases'][0]['case_id'],'completion':'broken'}]});self.assertEqual(r['cases'],60);self.assertEqual(r['missing_predictions'],59);self.assertEqual(r['valid_outputs'],0);self.assertTrue(all(x==0 for x in r['metrics'].values()))
    def test_unknown_duplicate_predictions_and_wrong_binding_rejected(self):
        d=v.freeze(fixture_body());body={'dataset':d,'model_name':'Software fixture only','dataset_sha256':d['sha256'],'predictions':[{'case_id':'unknown','completion':{}}]}
        with self.assertRaises(ValueError):v.evaluate(body)
        body.update(predictions=[],dataset_sha256='0'*64)
        with self.assertRaises(ValueError):v.evaluate(body)
    def test_material_packs_are_blank_and_have_offline_sources(self):
        for slot in ('A','B'):
            with zipfile.ZipFile(SITE/f'dist/review-packs-v08/reviewer-{slot}.zip') as z:
                p=json.loads(z.read('task-'+slot+'.json'));self.assertTrue(all(r['answer'] is None for r in p['records']));self.assertIn('primary-context.html',z.namelist());self.assertNotIn('coordinator-only-design.json',z.namelist());self.assertEqual(len([n for n in z.namelist() if n.startswith('sources/')]),6)
    def test_routes_expose_no_predicted_reference(self):
        self.assertEqual(request('/api/v08/meta')['data']['audit']['blank_answers'],60);self.assertEqual(request('/api/v08/submit',{'packet':fixture_draft(complete=False),'independent_confirmed':True,'submitted_at':STAMP})['status'],400)
        self.assertTrue(all('safe' not in d for d in v.meta()['supplementary'].values()))
    def test_old_freeze_cannot_bypass_v08_protocol(self):
        from human_evaluation import new_case,freeze_dataset
        b=v.batch();c=b['cases'][0];r=new_case({'case_id':'legacy-bypass-software-fixture','title':'Software fixture only','policy_id':c['policy_id'],'profile':c['profile'],'provenance':{'kind':'user_authored_synthetic','training_use':'not_used'}},b['policies'])
        with self.assertRaisesRegex(ValueError,'v0.8'):freeze_dataset({'cases':[r]},b['policies'])
    def test_valid_wrong_prediction_reports_false_passes_and_all_60_denominator(self):
        d=v.freeze(fixture_body());p={'screening':'conditions_met','qualification':'recorded','missing_fields':[],'materials':[],'evidence_ids':d['cases'][0]['expected']['evidence_ids'],'next_question':None,'evidence_support':'not_assessable','explanation':'Software fixture only, not actual inference.'}
        r=v.evaluate({'dataset':d,'model_name':'Software fixture only','dataset_sha256':d['sha256'],'predictions':[{'case_id':d['cases'][0]['case_id'],'completion':p}]});self.assertEqual(r['valid_outputs'],1);self.assertEqual(r['false_conditions_met'],1);self.assertEqual(r['false_recorded'],1);self.assertEqual(r['metrics']['evidence_support'],1/60)
if __name__=='__main__':unittest.main()
