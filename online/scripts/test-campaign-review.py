"""Software fixtures only: never publish these labels as research annotations."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest,zipfile
SITE=Path(__file__).resolve().parent.parent;WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='campaign-tests-',dir=WORK)).resolve()
assert ROOT.is_relative_to(WORK.resolve())
with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:
    assert all(not Path(x.filename).is_absolute() and '..' not in Path(x.filename).parts for x in z.infolist());z.extractall(ROOT)
sys.path.insert(0,str(ROOT))
from campaign_review import *
from human_evaluation import verify_dataset,evaluate_dataset
from browser_backend import request
POLICIES=read('policies.json')['policies'];STAMP='2026-10-30T10:00:00+00:00'
def fixtures(slot,change=False):
    rows=assignment(slot)['cases']
    for i,r in enumerate(rows):
        r['expected']={'policy_id':r['policy_id'],'conclusion':'insufficient','evidence_ids':[],'missing_fields':[],'materials':[],'explanation':'Software fixture only; NOT a human policy judgment.'}
        r['review']={'status':'reviewed','reviewer':'software-fixture-'+slot,'reviewed_at':STAMP,'source_checked':True}
    if change:
        p=next(p for p in POLICIES if p['id']==rows[0]['policy_id']);rows[0]['expected'].update(conclusion='ineligible',evidence_ids=[p['clauses'][0]['id']])
    return rows
def packet(slot,change=False):return submission({'cases':fixtures(slot,change),'reviewer_id':'software-fixture-'+slot,'independent_confirmed':True,'submitted_at':STAMP},POLICIES)
def body(change=False):return {'a':packet('A'),'b':packet('B',change),'adjudicator_id':'software-fixture-C','source_checked':True,'independence_confirmed':True,'name':'Software fixture only','dataset_id':'software-fixture-dual','frozen_at':STAMP,'decisions':[]}
class Tests(unittest.TestCase):
    def test_all_54_are_empty_distinct_and_unseen(self):
        a=audit_candidates();self.assertEqual(a['cases'],54);self.assertEqual(a['blank_answers'],54);self.assertEqual(a['unique_profiles'],54);self.assertEqual(a['known_exact_overlaps'],[])
        self.assertEqual(sorted(a['policy_tasks'].values()),[18,18,18])
    def test_source_files_not_in_initial_bundle(self):
        with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:self.assertFalse(any(n.startswith('sources/') for n in z.namelist()))
        for d in registry()['documents']:
            p=SITE/d['local_url'].lstrip('/');self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),d['sha256'])
    def test_assignment_never_copies_answers(self):
        a=assignment('A');b=assignment('B');self.assertTrue(all(r['expected'] is None for r in a['cases']+b['cases']));self.assertNotEqual(a['cases'][0]['case_id'],b['cases'][0]['case_id'])
    def test_restoring_preserves_assignment(self):
        rows=restore_rows(assignment('A')['cases'],POLICIES);self.assertEqual(rows[0]['campaign']['slot'],'A');self.assertIsNone(rows[0]['expected'])
    def test_changed_applicant_rejected(self):
        rows=fixtures('A');rows[0]['profile']['degree']='college'
        with self.assertRaisesRegex(ValueError,'改变'):submission({'cases':rows,'reviewer_id':'software-fixture-A','independent_confirmed':True},POLICIES)
    def test_wrong_source_registry_rejected(self):
        rows=assignment('A')['cases'];rows[0]['campaign']['source_registry_sha256']='bad'
        with self.assertRaisesRegex(ValueError,'改变'):restore_rows(rows,POLICIES)
    def test_incomplete_submission_rejected(self):
        with self.assertRaisesRegex(ValueError,'全部54'):submission({'cases':fixtures('A')[:-1],'reviewer_id':'software-fixture-A','independent_confirmed':True},POLICIES)
    def test_pending_submission_rejected(self):
        with self.assertRaisesRegex(ValueError,'尚未人工'):submission({'cases':assignment('A')['cases'],'reviewer_id':'software-fixture-A','independent_confirmed':True},POLICIES)
    def test_source_declaration_required_per_case(self):
        rows=fixtures('A');rows[0]['review']['source_checked']=False
        with self.assertRaisesRegex(ValueError,'每条'):submission({'cases':rows,'reviewer_id':'software-fixture-A','independent_confirmed':True},POLICIES)
    def test_uniform_identity_required(self):
        rows=fixtures('A');rows[1]['review']['reviewer']='another'
        with self.assertRaisesRegex(ValueError,'一致'):submission({'cases':rows,'reviewer_id':'software-fixture-A','independent_confirmed':True},POLICIES)
    def test_same_person_cannot_fill_both_slots(self):
        a=packet('A');rows=fixtures('B')
        for r in rows:r['review']['reviewer']='SOFTWARE-FIXTURE-a'
        b=submission({'cases':rows,'reviewer_id':'SOFTWARE-FIXTURE-a','independent_confirmed':True},POLICIES)
        with self.assertRaisesRegex(ValueError,'必须不同'):compare({'a':a,'b':b},POLICIES)
    def test_single_pass_cannot_freeze_reserved_batch(self):
        with self.assertRaisesRegex(ValueError,'双人'):freeze_dataset({'cases':fixtures('A'),'name':'test','dataset_id':'test-1','purpose':'test','independence_confirmed':True},POLICIES)
    def test_removing_campaign_metadata_does_not_bypass_workflow(self):
        rows=fixtures('A')
        for r in rows:r.pop('campaign')
        with self.assertRaisesRegex(ValueError,'移除任务元数据'):freeze_dataset({'cases':rows},POLICIES)
    def test_unresolved_disagreement_blocks_freeze(self):
        with self.assertRaisesRegex(ValueError,'分歧尚未处理'):reconcile(body(True),POLICIES)
    def test_third_identity_required(self):
        b=body();b['adjudicator_id']='software-fixture-A'
        with self.assertRaisesRegex(ValueError,'不同'):reconcile(b,POLICIES)
    def test_completed_audit_survives_offline_verification(self):
        b=body(True);b['decisions']=[{'case_id':campaign()['cases'][0]['case_id'],'choice':'B','reason':'Software test fixture decision only.'}]
        d=reconcile(b,POLICIES);rows,t,p=verify_dataset(d);self.assertEqual(len(rows),54);self.assertEqual(rows[0]['expected']['conclusion'],'ineligible');self.assertEqual(d['review_protocol']['version'],2)
        result=evaluate_dataset({'dataset':d,'predictions':[],'prediction_dataset_sha256':d['sha256'],'model_name':'software fixture only'});self.assertEqual(result['metrics']['missing_predictions'],54)
    def test_rehashed_answer_change_still_breaks_audit(self):
        d=reconcile(body(),POLICIES);d['cases'][0]['expected']['explanation']='Changed outside adjudication';d['sha256']=digest({k:v for k,v in d.items() if k!='sha256'})
        with self.assertRaisesRegex(ValueError,'终审记录'):verify_dataset(d)
    def test_json_stringify_integer_rates_do_not_change_fingerprint(self):
        for changed in (False,True):
            b=body(changed)
            if changed:b['decisions']=[{'case_id':campaign()['cases'][0]['case_id'],'choice':'B','reason':'Software fixture only, not human labels.'}]
            d=reconcile(b,POLICIES)
            # Emulate JS JSON.stringify converting integral floating point numbers.
            returned=json_browser_numbers(d);self.assertEqual(returned['sha256'],digest({k:v for k,v in returned.items() if k!='sha256'}));verify_dataset(returned)
    def test_single_class_kappa_not_fake_perfect(self):
        result=compare(body(),POLICIES);self.assertIsNone(result['summary']['cohen_kappa']);self.assertEqual(result['summary']['conclusion_agreement'],1)
    def test_new_browser_routes(self):
        self.assertEqual(request('/api/campaign')['status'],200);self.assertEqual(request('/api/sources')['status'],200);self.assertEqual(request('/api/campaign/assignment',{'slot':'C'})['status'],400)

if __name__=='__main__':unittest.main(verbosity=1)
