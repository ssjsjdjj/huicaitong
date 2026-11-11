"""Software-only application guidance, partial draft and version-isolation fixtures."""
from pathlib import Path
import copy,json,sys,tempfile,unittest,zipfile
SITE=Path(__file__).resolve().parent.parent;WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='application-tests-',dir=WORK)).resolve()
assert ROOT.is_relative_to(WORK.resolve())
with zipfile.ZipFile(SITE/'dist/python-app.zip') as z:
    assert all(not Path(x.filename).is_absolute() and '..' not in Path(x.filename).parts for x in z.infolist());z.extractall(ROOT)
sys.path.insert(0,str(ROOT))
import application_flow as flow
from browser_backend import request
from fixtures import BASE,CASES
from core import assess_all,RAW_FIELDS
POLICIES=json.loads((ROOT/'data/policies.json').read_text(encoding='utf-8'))['policies']
SAFE={'graduation_record_precision':'day','has_dispatch_history':False,'family_scope_confirmed':True,'housing_scope_confirmed':True,'family_property_history':False,'prior_rent_degree_subsidy':False}
STAMP='2026-11-11T08:00:00+08:00'
def body(**changes):return {'profile':copy.deepcopy(BASE),'supplementary':copy.deepcopy(SAFE),'intent':'all',**changes}
def first(report,id='hz-living-first-2024'):return next(r for r in report['results'] if r['policy_id']==id)
class FlowTests(unittest.TestCase):
    def test_original_rule_snapshot_and_labels_are_unchanged(self):
        before=assess_all(POLICIES,BASE);after=flow.assess(body(supplementary={}),POLICIES)
        self.assertEqual([r['conclusion'] for r in before['results']],[r['conclusion'] for r in after['results']]);self.assertNotIn('qualification_review',before['results'][0])
    def test_missing_supplement_is_not_presented_as_complete(self):
        r=first(flow.assess(body(supplementary={}),POLICIES));self.assertEqual(r['qualification_review']['status'],'pending');self.assertIn('补充资格待核验',r['display']['label'])
    def test_housing_history_requires_review_without_changing_living_result(self):
        e={**SAFE,'family_property_history':True};r=flow.assess(body(supplementary=e),POLICIES)
        self.assertEqual(first(r,'hz-rent-first-2026')['qualification_review']['status'],'manual');self.assertEqual(first(r)['qualification_review']['status'],'recorded')
    def test_missing_or_unconfirmed_family_scope_is_explicit(self):
        for value,stage in [(None,'pending'),(False,'manual')]:
            r=flow.assess(body(supplementary={**SAFE,'family_scope_confirmed':value},intent='rent'),POLICIES);self.assertEqual(r['results'][0]['qualification_review']['status'],stage)
    def test_month_precision_does_not_invent_a_graduation_day(self):
        r=flow.assess(body(supplementary={**SAFE,'graduation_record_precision':'month'}),POLICIES);self.assertEqual(r['profile']['graduation_date'],BASE['graduation_date']);self.assertEqual(first(r)['qualification_review']['status'],'manual')
    def test_dispatch_requires_manual_confirmation(self):
        self.assertEqual(first(flow.assess(body(supplementary={**SAFE,'has_dispatch_history':True}),POLICIES))['qualification_review']['status'],'manual')
    def test_rent_checks_qualified_employer_not_covered_by_old_short_rules(self):
        b=body(intent='rent');b['profile']['employer_qualified']=None;r=flow.assess(b,POLICIES);self.assertEqual(r['results'][0]['conclusion'],'eligible');self.assertEqual(r['results'][0]['qualification_review']['status'],'pending');self.assertEqual(flow.guide(b,POLICIES)['question']['key'],'employer_qualified')
    def test_clear_blocker_does_not_trigger_unnecessary_questions(self):
        g=flow.guide(body(intent='living-second'),POLICIES);self.assertIsNone(g['question']);self.assertEqual(g['remaining'],0)
    def test_rent_learning_mode_and_current_insurance_gaps_are_gated(self):
        for key,value,stage in [('study_mode',None,'pending'),('study_mode','parttime','manual'),('insurance_current',False,'manual')]:
            b=body(intent='rent');b['profile'][key]=value;r=flow.assess(b,POLICIES)['results'][0]
            self.assertEqual(r['qualification_review']['status'],stage);self.assertEqual(r['conclusion'],'eligible')
    def test_outside_scope_is_not_rejected_as_ineligible(self):
        b=body(intent='living-first');b['profile']['study_mode']='parttime';r=flow.assess(b,POLICIES);self.assertEqual(r['results'][0]['conclusion'],'insufficient');self.assertEqual(r['results'][0]['qualification_review']['status'],'outside_scope');self.assertIsNone(flow.guide(b,POLICIES)['question'])
    def test_student_planning_stops_insurance_interview(self):
        b=body(profile=CASES[6]['profile'],intent='living-first');g=flow.guide(b,POLICIES);self.assertIsNone(g['question']);self.assertEqual(g['results'][0]['qualification_status'],'planning')
    def test_skip_unknown_does_not_loop_or_fill_false(self):
        b=body(profile={'application_date':'2026-11-11'},supplementary={},intent='rent',deferred=[])
        for n in range(50):
            g=flow.guide(b,POLICIES)
            if not g['question']:break
            b['deferred'].append(g['question']['key'])
        self.assertLess(n,40);self.assertGreater(g['remaining'],0);self.assertEqual(g['remaining'],g['deferred_count']);self.assertIsNone(b['profile'].get('family_has_home'))
    def test_focus_question_can_edit_a_previous_answer(self):
        q=flow.guide(body(focus_question='degree'),POLICIES)['question'];self.assertEqual(q['key'],'degree');self.assertEqual(q['value'],'master')
    def test_family_and_region_are_asked_before_property_history(self):
        b=body(supplementary={},intent='rent');keys=[]
        for _ in range(6):
            q=flow.guide(b,POLICIES)['question'];keys.append(q['field']);b['supplementary'][q['field']]=SAFE[q['field']]
        self.assertEqual(keys,list(flow.EXTRA))
    def test_unknown_fields_are_never_stored(self):
        for data in [body(profile={**BASE,'id_number':'not-allowed'}),body(supplementary={**SAFE,'bank_account':'not-allowed'})]:
            with self.assertRaises(ValueError):flow.packet(data,POLICIES)
    def test_partial_and_cross_field_draft_roundtrip(self):
        b=body(profile={'application_date':None,'graduation_date':'2026-10-01','insurance_start_date':'2025-01-01'},supplementary={});p=flow.packet(b,POLICIES);r=flow.restore(p,POLICIES);self.assertIsNone(r['packet']['profile']['application_date']);self.assertEqual(r['packet']['profile']['insurance_start_date'],'2025-01-01')
        with self.assertRaises(ValueError):flow.assess(b,POLICIES)
    def test_incorrect_types_and_approval_states_rejected(self):
        for p in [{'insurance_months':True},{'city':False},{'graduation_date':'2026-02-30'},{'degree':['master']}]:
            with self.assertRaises(ValueError):flow.draft_profile(p)
        with self.assertRaises(ValueError):flow.packet(body(preparation={'context_sha256':'x','items':{'hz-living-first-2024/identity_info':'approved'}}),POLICIES)
    def test_preparation_progress_restores_in_same_context(self):
        b=body(intent='living-first');sha=flow.context(b['profile'],b['supplementary'],b['intent'],POLICIES);b['preparation']={'context_sha256':sha,'items':{'hz-living-first-2024/identity_info':'ready'}}
        p=flow.packet(b,POLICIES);self.assertEqual(flow.restore(p,POLICIES)['packet']['preparation']['items'],b['preparation']['items'])
    def test_profile_change_resets_preparation_state(self):
        b=body(intent='living-first');sha=flow.context(b['profile'],b['supplementary'],b['intent'],POLICIES);b['preparation']={'context_sha256':sha,'items':{'hz-living-first-2024/identity_info':'ready'}};b['profile']['graduation_date']='2025-07-01'
        self.assertEqual(flow.packet(b,POLICIES)['preparation']['items'],{})
    def test_changed_policy_restores_fields_but_resets_preparation(self):
        b=body(intent='living-first');b['preparation']={'context_sha256':flow.context(b['profile'],b['supplementary'],b['intent'],POLICIES),'items':{'hz-living-first-2024/identity_info':'ready'}};p=flow.packet(b,POLICIES);changed=copy.deepcopy(POLICIES);changed[0]['title']+=' software version fixture';r=flow.restore(p,changed);self.assertTrue(r['stale']);self.assertEqual(r['packet']['preparation']['items'],{});self.assertEqual(r['packet']['profile']['degree'],'master')
    def test_changed_source_registry_resets_preparation(self):
        p=flow.packet(body(),POLICIES);p['source_registry_sha256']='0'*64;p['sha256']=flow.digest({k:v for k,v in p.items() if k!='sha256'});self.assertTrue(flow.restore(p,POLICIES)['stale'])
    def test_tampered_packet_is_rejected(self):
        p=flow.packet(body(),POLICIES);p['profile']['degree']='phd'
        with self.assertRaisesRegex(ValueError,'指纹'):flow.restore(p,POLICIES)
    def test_wrong_file_type_is_rejected(self):
        with self.assertRaises(ValueError):flow.restore({'schema_version':1,'type':'independent_review_submission'},POLICIES)
    def test_deferrals_and_source_references_validate(self):
        for deferred in [['bank_info'],['degree','degree'],[{}]]:
            with self.assertRaises(ValueError):flow.packet(body(deferred=deferred),POLICIES)
    def test_new_routes_and_bad_input_return_clear_errors(self):
        self.assertEqual(request('/api/application/meta')['status'],200);self.assertEqual(request('/api/application/guide',body())['status'],200);self.assertEqual(request('/api/application/restore',{'packet':{'schema_version':99}})['status'],400)
    def test_reserved_benchmark_unchanged(self):
        p=json.loads((ROOT/'data/review-campaign.json').read_text(encoding='utf-8'));self.assertEqual(p['sha256'],'abac6cf9b139f6353e42f303de4140932aaa963dcd5b4676cac069ccecd3d4b6');self.assertTrue(all(r['expected'] is None for r in p['cases']))
if __name__=='__main__':unittest.main(verbosity=1)
