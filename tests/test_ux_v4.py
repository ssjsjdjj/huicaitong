"""Regression cases from the user-perspective audit; not a human benchmark."""
import copy
import json
import unittest

from core import assess_all, validate_profile
from fixtures import BASE, FIRST, SECOND, RENT
from guidance import audit_model, reference_fields
from materials import parse_fields
from review import restore_drafts, reviewed_tasks
from store import DATA, ROOT


class UsabilityRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies=json.loads(DATA.read_text(encoding='utf-8'))['policies']
        cls.first=next(p for p in cls.policies if p['id']==FIRST)
        cls.draft=json.loads((ROOT/'data/review_draft.json').read_text(encoding='utf-8'))['cases'][0]

    def result(self,profile=BASE,policy_id=FIRST):
        return next(r for r in assess_all(self.policies,profile)['results'] if r['policy_id']==policy_id)

    def test_conflict_explains_received_first_without_rewriting_prediction(self):
        profile=validate_profile({**BASE,'first_installment_received':True})
        prediction=reference_fields(self.first,self.result(profile))
        prediction['conclusion']='eligible'
        before=copy.deepcopy(prediction)
        audit=audit_model(self.first,profile,prediction)
        conflict=next(c for c in audit['blocking_checks'] if c['field']=='first_installment_received')
        self.assertEqual(conflict['actual_label'],'已领取本次学历生活补贴首笔')
        self.assertEqual(conflict['citation'],'living-payment')
        self.assertEqual(audit['status'],'needs_review')
        self.assertIn('不作为通过建议',audit['next_action'])
        self.assertEqual(prediction,before)

    def test_benefit_displays_first_and_second_shares_without_double_total(self):
        for policy in (FIRST,SECOND):
            benefit=self.result(policy_id=policy)['display']['benefit']
            self.assertEqual(benefit['reference_yuan'],15000)
            self.assertIn('不重复累计',benefit['basis'])
            self.assertIn('3 万元',benefit['standard_note'])

    def test_bachelor_share_is_derived_from_snapshot(self):
        self.assertEqual(self.result({**BASE,'degree':'bachelor'})['display']['benefit']['reference_yuan'],5000)

    def test_doctorate_exception_not_given_unconditional_amount(self):
        benefit=self.result({**BASE,'degree':'phd'})['display']['benefit']
        self.assertIsNone(benefit['reference_yuan'])
        self.assertIn('例外',benefit['basis'])

    def test_rent_first_is_half_annual_recorded_amount(self):
        benefit=self.result(policy_id=RENT)['display']['benefit']
        self.assertEqual(benefit['reference_yuan'],5000)
        self.assertIn('每户每年 10,000',benefit['basis'])

    def test_future_graduation_not_described_as_expired(self):
        result=self.result({**BASE,'graduation_date':'2027-06-30','insurance_start_date':None,'insurance_months':0})
        self.assertEqual(result['conclusion'],'ineligible')  # Frozen rule semantics retained.
        self.assertEqual(result['display']['phase'],'not_started')
        self.assertTrue(result['display']['preparation'])
        shown=next(c for c in result['display']['checks'] if c['field']=='within_24_months')
        self.assertEqual(shown['status'],'not_started')
        self.assertIn('尚未开始',shown['label'])

    def test_expired_graduation_has_a_different_explanation(self):
        result=self.result({**BASE,'graduation_date':'2022-06-30'})
        self.assertEqual(result['display']['phase'],'expired')
        self.assertFalse(result['display']['planning'])
        self.assertEqual(result['display']['label'],'已超过所列申请期')
        self.assertIn('已超过',next(c for c in result['display']['checks'] if c['field']=='within_24_months')['label'])

    def test_future_planning_does_not_hide_other_failed_conditions(self):
        result=self.result({**BASE,'degree':'college','graduation_date':'2027-06-30','insurance_start_date':None,'insurance_months':0})
        self.assertIn('degree_rank',[c['field'] for c in result['display']['other_blockers']])
        self.assertIn('不能仅等待毕业',result['display']['reason'])

    def test_imported_policy_without_graduation_requirement_has_no_invented_gate(self):
        policy=copy.deepcopy(self.first)
        policy.update(id='unit-custom-policy',rules=[r for r in policy['rules'] if r['field']=='degree_rank'])
        report=assess_all([policy],{**BASE,'graduation_date':'2027-06-30','insurance_start_date':None,'insurance_months':0})
        self.assertEqual(report['results'][0]['conclusion'],'eligible')
        self.assertEqual(report['results'][0]['display']['phase'],'not_applicable')
        self.assertIsNone(report['results'][0]['display']['label'])

    def test_unsupported_scope_does_not_present_automatic_future_planning(self):
        result=self.result({**BASE,'school_region':'overseas','graduation_date':'2027-06-30','insurance_start_date':None,'insurance_months':0})
        self.assertFalse(result['display']['planning'])

    def pending(self):
        row=copy.deepcopy(self.draft)
        row['draft_annotation']={'conclusion':'','evidence_ids':['living-payment'],'missing_fields':[],'materials':[],
                                 'explanation':'Incomplete unit-test note; not a human annotation.','reviewer':''}
        return row

    def test_pending_roundtrip_preserves_partial_note_without_human_promotion(self):
        original=self.pending()
        restored=restore_drafts([original],self.policies)[0]
        self.assertEqual(restored['draft_annotation'],original['draft_annotation'])
        self.assertEqual(restored['review']['status'],'pending')
        self.assertIsNone(restored['expected'])
        with self.assertRaises(ValueError):
            reviewed_tasks([restored],self.policies)

    def test_legacy_blank_draft_can_be_restored(self):
        self.assertEqual(restore_drafts([self.draft],self.policies)[0]['review']['status'],'pending')

    def test_restore_rejects_old_policy_snapshot(self):
        row=self.pending();row['source_policy_sha256']='stale'
        with self.assertRaises(ValueError):restore_drafts([row],self.policies)

    def test_restore_rejects_unrecognized_evidence(self):
        row=self.pending();row['draft_annotation']['evidence_ids']=['invented-clause']
        with self.assertRaises(ValueError):restore_drafts([row],self.policies)

    def test_restore_rejects_unknown_annotation_fields_and_invalid_profile(self):
        for change in ('annotation','profile'):
            row=self.pending()
            if change=='annotation':row['draft_annotation']['ground_truth']='fabricated'
            else:row['profile']['insurance_months']=-3
            with self.assertRaises(ValueError):restore_drafts([row],self.policies)

    def test_duplicate_case_ids_cannot_overwrite_earlier_import(self):
        row=self.pending()
        with self.assertRaises(ValueError):restore_drafts([row,row],self.policies)

    def test_unconfirmed_expected_label_is_cleared_on_restore(self):
        row=self.pending();row['expected']={'conclusion':'eligible'}
        restored=restore_drafts([row],self.policies)[0]
        self.assertIsNone(restored['expected'])

    def test_missing_graduation_is_context_block_not_read_failure(self):
        text=(ROOT/'data/material_examples/insurance-gap-demo.txt').read_text(encoding='utf-8')
        detail={}
        candidates,_=parse_fields([text],{**BASE,'graduation_date':None},detail)
        self.assertEqual(detail['status'],'needs_context')
        self.assertEqual(detail['required_context'],['graduation_date'])
        self.assertTrue(detail['ledger'])
        self.assertFalse(any(c['field']=='insurance_months' for c in candidates))

    def test_gap_ledger_explains_which_months_counted(self):
        text=(ROOT/'data/material_examples/insurance-gap-demo.txt').read_text(encoding='utf-8')
        detail={}
        fields,_=parse_fields([text],BASE,detail)
        self.assertEqual(detail['continuous_months'],1)
        self.assertEqual([m['month'] for m in detail['ledger'] if m['counted']],['2026-09'])
        self.assertEqual(next(m for m in detail['ledger'] if m['month']=='2026-08')['state'],'excluded')
        self.assertEqual(next(c['value'] for c in fields if c['field']=='insurance_months'),1)


if __name__=='__main__':unittest.main()
