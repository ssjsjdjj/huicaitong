"""Synthetic software fixtures only. These annotations are NOT research gold labels."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest
import zipfile

SITE=Path(__file__).resolve().parent.parent
WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='human-eval-tests-',dir=WORK)).resolve()
assert ROOT.is_relative_to(WORK.resolve())
with zipfile.ZipFile(SITE/'dist'/'python-app.zip') as archive:
    assert all(not Path(i.filename).is_absolute() and '..' not in Path(i.filename).parts for i in archive.infolist())
    archive.extractall(ROOT)
sys.path.insert(0,str(ROOT))
from human_evaluation import new_case, freeze_dataset, verify_dataset, evaluate_dataset, profile_hash
from fixtures import BASE

POLICIES=json.loads((ROOT/'data'/'policies.json').read_text(encoding='utf-8'))['policies']
DRAFT=json.loads((ROOT/'data'/'review_draft.json').read_text(encoding='utf-8'))['cases']
STAMP='2026-10-30T08:00:00+00:00'
def confirmed(row,label='insufficient'):
    row=copy.deepcopy(row)
    policy=next(p for p in POLICIES if p['id']==row['policy_id'])
    row['expected']={'policy_id':policy['id'],'conclusion':label,'evidence_ids':[] if label=='insufficient' else [policy['clauses'][0]['id']],'missing_fields':[],'materials':[],'explanation':'Software test fixture; not an actual human policy judgment.'}
    row['review']={'status':'reviewed','reviewer':'software-test-fixture','reviewed_at':STAMP}
    return row
def fresh(index=1,profile=None):
    return new_case({'case_id':f'unit-new-{index}','title':'Software fixture','policy_id':POLICIES[0]['id'],'profile':profile or {'city':'杭州','application_date':f'2026-11-{index:02d}'},'provenance':{'kind':'user_authored_synthetic','training_use':'not_used'}},POLICIES)
def freeze(rows,purpose='development',**extra):
    return freeze_dataset({'cases':rows,'name':'Software fixture only','dataset_id':'software-fixture-v1','purpose':purpose,'frozen_at':STAMP,**extra},POLICIES)
class EvaluationTests(unittest.TestCase):
    def test_pending_is_not_gold(self):
        with self.assertRaisesRegex(ValueError,'待复核'):freeze([fresh()])
    def test_practice_is_development_only(self):
        dataset=freeze([confirmed(DRAFT[0])]);self.assertEqual(dataset['summary']['reviewed'],1)
        with self.assertRaisesRegex(ValueError,'内置'):freeze([confirmed(DRAFT[0])],'test',independence_confirmed=True)
    def test_new_id_does_not_hide_training_overlap(self):
        row=confirmed(fresh(profile=BASE))
        with self.assertRaisesRegex(ValueError,'重复'):freeze([row],'test',independence_confirmed=True)
    def test_test_use_requires_explicit_declaration(self):
        with self.assertRaisesRegex(ValueError,'确认'):freeze([confirmed(fresh())],'test')
    def test_unknown_training_use_blocks_test(self):
        row=confirmed(fresh());row['provenance']['training_use']='unknown'
        with self.assertRaisesRegex(ValueError,'逐条声明'):freeze([row],'test',independence_confirmed=True)
    def test_new_declared_test_retains_limits(self):
        dataset=freeze([confirmed(fresh())],'test',independence_confirmed=True)
        self.assertFalse(dataset['independence']['external_training_history_verified']);verify_dataset(dataset)
    def test_duplicate_task_cannot_inflate_sample_size(self):
        one=confirmed(fresh());two=copy.deepcopy(one);two['case_id']='other-id'
        with self.assertRaisesRegex(ValueError,'重复任务'):freeze([one,two])
    def test_policy_snapshot_mismatch_rejected(self):
        row=confirmed(fresh());row['source_policy_sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'版本'):freeze([row])
    def test_tampering_invalidates_fingerprint(self):
        dataset=freeze([confirmed(fresh())]);dataset['cases'][0]['expected']['conclusion']='eligible'
        with self.assertRaisesRegex(ValueError,'SHA-256'):verify_dataset(dataset)
    def test_profile_hash_normalizes_omitted_null_fields(self):
        self.assertEqual(profile_hash({'application_date':'2026-11-01'}),profile_hash({'city':'杭州','application_date':'2026-11-01','degree':None}))
    def test_profile_refuses_identity_fields(self):
        with self.assertRaisesRegex(ValueError,'未知字段'):fresh(profile={'application_date':'2026-11-01','private_name':'test-only'})
    def test_new_case_requires_an_explicit_reference_date(self):
        with self.assertRaisesRegex(ValueError,'参考日期'):fresh(profile={'city':'杭州'})
    def test_case_number_cannot_impersonate_builtin(self):
        with self.assertRaisesRegex(ValueError,'前缀'):new_case({'case_id':'review-draft-fake','title':'test','policy_id':POLICIES[0]['id'],'profile':{}},POLICIES)
    def score(self,predictions,binding=True):
        rows=[confirmed(fresh(1)),confirmed(fresh(2),'ineligible')];dataset=freeze(rows)
        return evaluate_dataset({'dataset':dataset,'predictions':predictions(rows),'model_name':'software fixture only','prediction_dataset_sha256':dataset['sha256'] if binding else None,'binding_confirmed':binding})
    def test_missing_predictions_count_in_denominator(self):
        result=self.score(lambda rows:[{'case_id':rows[0]['case_id'],'completion':rows[0]['expected']}])
        self.assertEqual(result['metrics']['cases'],2);self.assertEqual(result['metrics']['missing_predictions'],1);self.assertEqual(result['metrics']['conclusion_accuracy'],.5)
        self.assertTrue(result['details'][1]['missing_prediction'])
    def test_invalid_output_is_not_silently_dropped(self):
        result=self.score(lambda rows:[{'case_id':rows[0]['case_id'],'completion':'broken'}])
        self.assertEqual(result['metrics']['valid_output_rate'],0);self.assertEqual(result['metrics']['cases'],2)
    def test_duplicate_predictions_rejected(self):
        with self.assertRaisesRegex(ValueError,'重复'):self.score(lambda rows:[{'case_id':rows[0]['case_id'],'completion':''}]*2)
    def test_unknown_prediction_case_rejected(self):
        with self.assertRaisesRegex(ValueError,'未知'):self.score(lambda rows:[{'case_id':'unknown','completion':''}])
    def test_mixed_dataset_fingerprints_rejected(self):
        dataset=freeze([confirmed(fresh())])
        with self.assertRaisesRegex(ValueError,'指纹'):evaluate_dataset({'dataset':dataset,'predictions':[],'model_name':'test','prediction_dataset_sha256':'another-set'})
    def test_unbound_file_requires_user_declaration(self):
        with self.assertRaisesRegex(ValueError,'确认'):self.score(lambda rows:[],binding=False)

if __name__=='__main__':unittest.main(verbosity=1)
