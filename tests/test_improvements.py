import copy
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from collections import Counter
from pathlib import Path

from core import assess_all, assess_policy, validate_profile
from fixtures import BASE, FIRST, SECOND, RENT
from guidance import audit_model, reference_fields
from launcher import selected_checkpoint
from llm import run_model
from store import DATA, ROOT
from training.build_counterfactual import build
from training.build_dataset import model_answer, reference_answer
from training.evaluate import evaluate_predictions
from training.rewards import score_completion


class ImprovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies=json.loads(DATA.read_text(encoding="utf-8"))["policies"]
        cls.first=next(p for p in cls.policies if p["id"]==FIRST)

    def test_followups_merge_relevant_policies(self):
        report=assess_all(self.policies,{**BASE,"insurance_months":None,"first_installment_received":None})
        q=next(q for q in report["guidance"]["followups"] if q["field"]=="insurance_months")
        self.assertEqual(set(q["policy_ids"]),{FIRST,SECOND,RENT})
        self.assertEqual(len([q for q in report["guidance"]["followups"] if q["field"]=="insurance_months"]),1)

    def test_rejected_policy_does_not_ask_irrelevant_questions(self):
        report=assess_all(self.policies,{**BASE,"degree":"college","insurance_months":None})
        self.assertEqual(report["guidance"]["followups"],[])

    def test_future_source_does_not_ask_questions(self):
        report=assess_all(self.policies,{**BASE,"application_date":"2025-12-01","insurance_months":None,"family_has_home":None})
        self.assertFalse(any(RENT in q["policy_ids"] for q in report["guidance"]["followups"]))

    def test_calendar_timeline_does_not_invent_insurance_count(self):
        report=assess_all(self.policies,{**BASE,"insurance_months":None})
        first=next(r for r in report["results"] if r["policy_id"]==FIRST)
        self.assertEqual(first["conclusion"],"insufficient")
        self.assertIn("2025-12-31",[t["date"] for t in first["timeline"]])
        self.assertIn("2026-01-01",[t["date"] for t in first["timeline"]])
        self.assertIn("2027-06-30",[t["date"] for t in first["timeline"]])

    def test_unsupported_scope_does_not_display_automatic_deadline(self):
        report=assess_all(self.policies,{**BASE,"school_region":"overseas"})
        self.assertTrue(all(not r["timeline"] for r in report["results"]))

    def answer(self,profile=BASE):
        return reference_fields(self.first,assess_policy(self.first,validate_profile(profile)))

    def test_audit_does_not_rewrite_model_prediction(self):
        answer=self.answer()
        answer["conclusion"]="ineligible"
        before=copy.deepcopy(answer)
        audit=audit_model(self.first,validate_profile(BASE),answer)
        self.assertEqual(audit["status"],"needs_review")
        self.assertEqual(answer,before)
        self.assertIn("conclusion_conflict",[i["code"] for i in audit["issues"]])

    def test_same_verdict_can_still_have_missing_evidence(self):
        answer=self.answer()
        answer["evidence_ids"]=["living-scope"]
        audit=audit_model(self.first,validate_profile(BASE),answer)
        self.assertEqual(audit["status"],"needs_review")
        self.assertIn("living-insurance",next(i for i in audit["issues"] if i["field"]=="evidence_ids")["missing"])

    def test_missing_field_disagreement_requires_review(self):
        profile={**BASE,"employer_qualified":None}
        answer=self.answer(profile)
        answer["missing_fields"]=[]
        audit=audit_model(self.first,validate_profile(profile),answer)
        self.assertEqual(audit["status"],"needs_review")

    def test_audit_aligned_is_not_prose_verification(self):
        answer=self.answer()
        answer["explanation"]="This prose has not been verified."
        audit=audit_model(self.first,validate_profile(BASE),answer)
        self.assertEqual(audit["status"],"aligned")
        self.assertIn("不验证解释文字",audit["notice"])

    def test_material_difference_is_preparation_note(self):
        answer=self.answer()
        answer["materials"]=[]
        audit=audit_model(self.first,validate_profile(BASE),answer)
        self.assertEqual(audit["status"],"aligned")
        self.assertEqual(audit["issues"][0]["severity"],"note")

    def test_full_evaluation_exposes_majority_prediction(self):
        cases=[]
        predictions=[]
        for i,profile in enumerate((BASE,{**BASE,"degree":"college"},{**BASE,"employer_qualified":None})):
            gold=reference_answer(self.first,profile)
            cases.append({"case_id":str(i),"ground_truth":gold})
            answer=model_answer(gold)
            answer["conclusion"]="ineligible"
            predictions.append({"case_id":str(i),"completion":json.dumps(answer)})
        result,details=evaluate_predictions(cases,predictions)
        self.assertAlmostEqual(result["conclusion_accuracy"],1/3)
        self.assertEqual(result["per_class"]["eligible"]["recall"],0)
        self.assertEqual(result["confusion_matrix"]["eligible"]["ineligible"],1)
        self.assertEqual(len(details),3)

    def test_missing_prediction_counts_as_failure(self):
        result,details=evaluate_predictions([{"case_id":"a","ground_truth":reference_answer(self.first,BASE)}],[])
        self.assertEqual(result["missing_predictions"],1)
        self.assertEqual(result["conclusion_accuracy"],0)
        self.assertEqual(details[0]["predicted"],"invalid")

    def test_duplicate_gold_rejected(self):
        row={"case_id":"a","ground_truth":reference_answer(self.first,BASE)}
        with self.assertRaises(ValueError):
            evaluate_predictions([row,row],[])

    def test_reward_matches_serving_schema_for_empty_decisive_evidence(self):
        gold=reference_answer(self.first,BASE)
        answer=model_answer(gold)
        answer["evidence_ids"]=[]
        self.assertFalse(score_completion(json.dumps(answer),gold)["valid"])

    def test_scope_already_requires_manual_review_without_more_questions(self):
        report=assess_all(self.policies,{**BASE,"school_region":"overseas","insurance_months":None})
        self.assertEqual(report["guidance"]["followups"],[])

    def test_gateway_returns_raw_model_and_separate_audit_without_teacher_verdict(self):
        answer=self.answer()
        answer["conclusion"]="ineligible"
        payload={"choices":[{"message":{"content":json.dumps(answer)}}]}
        with patch("llm.model_config",return_value={"configured":True,"base":"http://127.0.0.1:8766/v1","model":"test"}),patch("llm.urllib.request.urlopen",return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            response=run_model(self.first,validate_profile(BASE))
        self.assertEqual(response["result"],answer)
        self.assertEqual(response["audit"]["status"],"needs_review")
        sent=json.loads(request.call_args.args[0].data)
        context=json.loads(sent["messages"][1]["content"])
        self.assertNotIn("conclusion",context)
        self.assertNotIn("checks",context)
        self.assertEqual(context["applicant"],validate_profile(BASE))

    def test_selected_checkpoint_checks_weight_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            adapter=root/"checkpoints"/"sft"
            adapter.mkdir(parents=True)
            (adapter/"adapter_model.safetensors").write_bytes(b"test-weights")
            config={"adapter":"sft","model_id":"huicaitong-test","adapter_sha256":hashlib.sha256(b"test-weights").hexdigest()}
            (root/"checkpoints"/"selection.json").write_text(json.dumps(config))
            self.assertEqual(selected_checkpoint(root),(adapter.resolve(),"huicaitong-test"))
            (adapter/"adapter_model.safetensors").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                selected_checkpoint(root)

    def test_selected_checkpoint_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"checkpoints").mkdir()
            (root/"checkpoints"/"selection.json").write_text(json.dumps({"adapter":"../outside","model_id":"m","adapter_sha256":"x"}))
            with self.assertRaises(ValueError):
                selected_checkpoint(root)

    def test_augmentation_never_reads_rental_targets_or_overlaps_dev_profiles(self):
        before=(ROOT/"data"/"generated"/"validation_grpo.jsonl").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            manifest=build(tmp,per_class=4)
            rows=[json.loads(x) for x in (Path(tmp)/"train_counterfactual_grpo.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(manifest["development_profile_overlap"],0)
            self.assertTrue(all(r["policy_family"]=="hz-living" for r in rows))
            counts=Counter((json.loads(r["ground_truth"])["policy_id"],json.loads(r["ground_truth"])["conclusion"]) for r in rows)
            self.assertEqual(set(counts.values()),{4})
            self.assertEqual(len(counts),6)
            self.assertEqual(len({r["case_id"] for r in rows}),len(rows))
        self.assertEqual(before,(ROOT/"data"/"generated"/"validation_grpo.jsonl").read_bytes())


if __name__=="__main__":
    unittest.main()
