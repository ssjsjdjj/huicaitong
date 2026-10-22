import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from app import Handler
from core import add_months, assess_all, assess_policy, validate_profile
from datetime import date
from fixtures import BASE, FIRST, SECOND, RENT, evaluate
from llm import parse_completion, validate_completion, model_config
from rag import retrieve
from store import PolicyStore, validate_policy
from training.build_dataset import build, reference_answer, model_answer
from training.rewards import score_completion, evidence_reward
from training.train import inspect_data


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.store=PolicyStore(Path(cls.temp.name)/"test.sqlite3")
        cls.policies=cls.store.all()
        cls.first=next(p for p in cls.policies if p["id"]==FIRST)
        cls.rent=next(p for p in cls.policies if p["id"]==RENT)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def result(self, profile, policy_id=FIRST):
        return next(r for r in assess_all(self.policies,profile)["results"] if r["policy_id"]==policy_id)

    def test_synthetic_acceptance_scenarios(self):
        report=evaluate(self.policies)
        self.assertEqual((report["passed"],report["total"],report["checks"]),(10,10,30))

    def test_false_is_known_not_missing(self):
        result=self.result(BASE,RENT)
        self.assertEqual(result["conclusion"],"eligible")
        self.assertNotIn("family_has_home",result["missing_fields"])

    def test_missing_housing_requires_more_information(self):
        result=self.result({**BASE,"family_has_home":None},RENT)
        self.assertEqual(result["conclusion"],"insufficient")
        self.assertIn("family_has_home",result["missing_fields"])

    def test_scope_is_not_rejection(self):
        result=self.result({**BASE,"school_region":"overseas"})
        self.assertEqual(result["conclusion"],"insufficient")
        self.assertIn("覆盖范围",result["reason"])

    def test_reference_published_in_future_is_unavailable(self):
        profile={**BASE,"application_date":"2025-12-01","insurance_months":5}
        result=self.result(profile,RENT)
        self.assertEqual(result["conclusion"],"insufficient")
        self.assertIn("发布时间",result["reason"])

    def test_not_graduated(self):
        result=self.result({**BASE,"graduation_date":"2027-06-30","insurance_start_date":None,"insurance_months":0})
        self.assertEqual(result["conclusion"],"ineligible")

    def test_first_and_second_are_distinct(self):
        profile={**BASE,"first_installment_received":True}
        self.assertEqual(self.result(profile)["conclusion"],"ineligible")
        self.assertEqual(self.result(profile,SECOND)["conclusion"],"eligible")

    def test_insurance_first_month_too_late(self):
        profile={**BASE,"insurance_start_date":"2026-08-01","insurance_months":2}
        failed=[c["field"] for c in self.result(profile)["checks"] if c["status"]=="fail"]
        self.assertIn("insurance_start_within_12",failed)

    def test_six_complete_months_next_month(self):
        profile={**BASE,"graduation_date":"2026-03-31","insurance_start_date":"2026-04-01","insurance_months":6,"application_date":"2026-10-01"}
        self.assertEqual(self.result(profile)["conclusion"],"eligible")
        profile.update(application_date="2026-09-30",insurance_months=5)
        self.assertEqual(self.result(profile)["conclusion"],"ineligible")

    def test_invalid_months_rejected(self):
        for v in (True,-1,1.5,"6",601):
            with self.subTest(v=v),self.assertRaises(ValueError):
                validate_profile({**BASE,"insurance_months":v})

    def test_inconsistent_insurance_duration_rejected(self):
        with self.assertRaises(ValueError):
            validate_profile({**BASE,"insurance_start_date":"2026-10-01","insurance_months":6})

    def test_pregraduation_insurance_rejected(self):
        with self.assertRaises(ValueError):
            validate_profile({**BASE,"insurance_start_date":"2024-01-01"})

    def test_str_boolean_rejected(self):
        with self.assertRaises(ValueError):
            validate_profile({**BASE,"family_has_home":"false"})

    def test_other_city_rejected(self):
        with self.assertRaises(ValueError):
            validate_profile({**BASE,"city":"上海"})

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            validate_profile({**BASE,"graduation_date":"2025-02-30"})

    def test_compact_date_rejected_before_lexical_comparison(self):
        for value in ("20250630","2025-6-30",20250630):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_profile({**BASE,"graduation_date":value})

    def test_leap_month_arithmetic(self):
        self.assertEqual(add_months(date(2024,2,29),12),date(2025,2,28))

    def test_archived_not_retrieved_by_default(self):
        rows=retrieve(self.policies,"2017 硕士 高学历 生活补贴",limit=12)
        self.assertTrue(rows)
        self.assertFalse(any(r["status"]=="archived" for r in rows))

    def test_historical_opt_in(self):
        rows=retrieve(self.policies,"2017 历史 高学历",limit=12,include_archived=True)
        self.assertTrue(any(r["status"]=="archived" for r in rows))

    def test_retrieval_respects_as_of_date(self):
        rows=retrieve(self.policies,"租房补贴",as_of="2025-01-01",limit=12)
        self.assertFalse(any(r["policy_id"]==RENT for r in rows))

    def test_empty_retrieval(self):
        self.assertEqual(retrieve(self.policies,""),[])

    def test_invalid_policy_reference(self):
        p=json.loads(json.dumps(self.first))
        p["rules"][0]["citation"]="made-up"
        with self.assertRaises(ValueError):
            validate_policy(p)

    def test_import_collision_is_atomic(self):
        before=len(self.store.all())
        with self.assertRaises(ValueError):
            self.store.import_policies({"city":"杭州","policies":[self.first]})
        self.assertEqual(len(self.store.all()),before)

    def test_parse_fenced_json(self):
        self.assertEqual(parse_completion('```json\n{"a":1}\n```'),{"a":1})

    def test_reward_gold_and_wrong_conclusion(self):
        gold=reference_answer(self.first,BASE)
        answer=model_answer(gold)
        self.assertEqual(score_completion(json.dumps(answer),gold)["total"],1)
        answer["conclusion"]="ineligible"
        self.assertEqual(score_completion(json.dumps(answer),gold)["total"],.05)

    def test_reward_rejects_fake_citation(self):
        gold=reference_answer(self.first,BASE)
        answer=model_answer(gold)
        answer["evidence_ids"].append("fabricated")
        self.assertEqual(score_completion(json.dumps(answer),gold)["total"],0)

    def test_reward_rejects_duplicate_citations(self):
        gold=reference_answer(self.first,BASE)
        answer=model_answer(gold)
        answer["evidence_ids"]*=2
        self.assertEqual(score_completion(json.dumps(answer),gold)["total"],0)

    def test_reward_invalid_json(self):
        self.assertEqual(score_completion("hello",reference_answer(self.first,BASE))["total"],0)

    def test_reward_malformed_field_types_do_not_crash_training(self):
        gold=reference_answer(self.first,BASE)
        for field,value in (("conclusion",[]),("materials",{}),("evidence_ids",[{}]),("missing_fields",None)):
            answer=model_answer(gold)
            answer[field]=value
            with self.subTest(field=field):
                self.assertEqual(score_completion(json.dumps(answer),gold)["total"],0)
        self.assertEqual(score_completion(None,gold)["total"],0)

    def test_chat_reward_adapter(self):
        gold=reference_answer(self.first,BASE)
        answers=[[{"role":"assistant","content":json.dumps(model_answer(gold))}]]
        self.assertEqual(evidence_reward(answers,[json.dumps(gold)]),[1.0])

    def test_model_output_cannot_invent_ids(self):
        answer=model_answer(reference_answer(self.first,BASE))
        answer["evidence_ids"]=["x"]
        with self.assertRaises(ValueError):
            validate_completion(answer,self.first,BASE.keys())

    def test_remote_model_requires_explicit_configuration(self):
        with patch.dict(os.environ,{"HCT_LLM_BASE_URL":"http://example.com/v1","HCT_LLM_MODEL":"m","HCT_ALLOW_REMOTE_LLM":"0"}):
            with self.assertRaises(ValueError):
                model_config()

    def test_dataset_test_source_is_held_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=build(tmp,count=60)
            train=inspect_data(Path(tmp)/"train_grpo.jsonl","grpo")
            test=inspect_data(Path(tmp)/"test_grpo.jsonl","grpo")
            self.assertFalse({r["source_url"] for r in train} & {r["source_url"] for r in test})
            self.assertTrue(all(not r["human_reviewed"] for r in train+test))
            self.assertIn("eligible",manifest["label_counts"]["train"])
            self.assertIn("insufficient",manifest["label_counts"]["train"])
            balanced=inspect_data(Path(tmp)/"train_balanced_grpo.jsonl","grpo")
            from collections import Counter
            counts=Counter(json.loads(r["ground_truth"])["conclusion"] for r in balanced)
            self.assertEqual(len(set(counts.values())),1)
            self.assertEqual(set(counts),{"eligible","ineligible","insufficient"})


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        cls.server.store=PolicyStore(Path(cls.temp.name)/"http.sqlite3")
        cls.port=cls.server.server_address[1]
        cls.base=f"http://127.0.0.1:{cls.port}"
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self,path,body=None,headers=None):
        h={"Content-Type":"application/json"}
        h.update(headers or {})
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
        return urllib.request.urlopen(req)

    def test_health_and_html(self):
        with self.request("/api/health") as r:
            self.assertTrue(json.load(r)["ok"])
        with self.request("/") as r:
            self.assertIn("惠才通",r.read().decode())
            self.assertIn("frame-ancestors 'none'",r.headers["Content-Security-Policy"])

    def test_examples_include_in_school(self):
        with self.request("/api/examples") as r:
            self.assertEqual(len(json.load(r)["examples"]),10)

    def test_assess_http(self):
        with self.request("/api/assess",{"profile":BASE}) as r:
            self.assertEqual(json.load(r)["mode"],"rule_baseline")

    def test_cross_origin_post_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("/api/evaluate",{},headers={"Origin":"https://example.com"})
        self.assertEqual(e.exception.code,403)

    def test_host_header_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("/api/meta",headers={"Host":"evil.example"})
        self.assertEqual(e.exception.code,403)

    def test_static_files_whitelisted(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("/data/policies.json")
        self.assertEqual(e.exception.code,404)

    def test_malformed_profile_returns_400(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("/api/assess",{"profile":{"insurance_months":-1}})
        self.assertEqual(e.exception.code,400)


if __name__=="__main__":
    unittest.main()
