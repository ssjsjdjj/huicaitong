import base64
import copy
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import urllib.error
import urllib.request

from app import Handler
from core import add_months, assess_policy, validate_profile
from fixtures import BASE,FIRST
from llm import messages_for, run_model
from materials import parse_fields, extract_material, material_capabilities
from policy_time import available
from rag import evidence_context, retrieve
from review import policy_hash, reviewed_tasks
from store import DATA,ROOT,PolicyStore,validate_policy


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies=json.loads(DATA.read_text(encoding="utf-8"))["policies"]
        cls.first=next(p for p in cls.policies if p["id"]==FIRST)

    def test_retrieval_expands_exclusions_and_materials(self):
        result=evidence_context(self.first,BASE,"连续参保")
        required={r["citation"] for key in ("scope","rules","materials") for r in self.first[key]}
        self.assertTrue(required<=set(result["trace"]["context_ids"]))
        self.assertIn("living-exclusion",result["trace"]["context_ids"])
        self.assertLessEqual(len(result["trace"]["hits"]),3)
        self.assertEqual(len(result["trace"]["context_ids"]),len(set(result["trace"]["context_ids"])))

    def test_no_keyword_hit_is_explicit_and_required_evidence_still_supplied(self):
        result=evidence_context(self.first,BASE,"zzqxx998877")
        self.assertEqual(result["trace"]["hits"],[])
        self.assertTrue(result["trace"]["expanded_ids"])

    def test_unlinked_appendix_not_silently_given_to_model(self):
        policy=copy.deepcopy(self.first)
        policy["clauses"].append({"id":"unrelated-appendix","section":"附录","text":"完全无关资料"})
        result=evidence_context(policy,BASE,"zzqxx998877")
        self.assertNotIn("unrelated-appendix",result["trace"]["context_ids"])
        prompt=json.loads(messages_for(policy,BASE,result)[1]["content"])
        self.assertNotIn("checks",prompt)
        self.assertNotIn("conclusion",prompt)
        self.assertEqual([c["id"] for c in prompt["clauses"]],result["trace"]["context_ids"])

    def test_missing_required_citation_blocks_model_context(self):
        policy=copy.deepcopy(self.first)
        policy["clauses"]=[c for c in policy["clauses"] if c["id"]!="living-exclusion"]
        with self.assertRaises(ValueError):
            evidence_context(policy,BASE)

    def test_effective_period_filters_rules_and_retrieval_consistently(self):
        policy={**self.first,"effective_until":"2026-01-01"}
        self.assertFalse(available(policy,BASE["application_date"]))
        self.assertEqual(retrieve([policy],"生活补贴"),[])
        self.assertEqual(assess_policy(policy,BASE)["conclusion"],"insufficient")
        hits=retrieve([policy],"生活补贴",include_archived=True)
        self.assertTrue(hits)
        self.assertTrue(all(h["outside_reference_period"] for h in hits))
        with self.assertRaises(ValueError):
            evidence_context(policy,BASE)

    def test_effective_period_order_is_validated(self):
        with self.assertRaises(ValueError):
            validate_policy({**self.first,"effective_from":"2027-01-01","effective_until":"2026-01-01"})

    def test_compact_search_date_cannot_bypass_temporal_comparison(self):
        with self.assertRaises(ValueError):
            retrieve(self.policies,"生活补贴",as_of="20261021")

    def test_model_cannot_cite_unsupplied_appendix(self):
        policy=copy.deepcopy(self.first)
        policy["clauses"].append({"id":"unrelated-appendix","section":"附录","text":"完全无关资料"})
        answer={"policy_id":FIRST,"conclusion":"ineligible","evidence_ids":["unrelated-appendix"],"missing_fields":[],"materials":[],"explanation":"test only"}
        response={"choices":[{"message":{"content":json.dumps(answer)}}]}
        with patch("llm.model_config",return_value={"configured":True,"base":"http://127.0.0.1:8766/v1","model":"test"}),patch("llm.urllib.request.urlopen",return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaises(ValueError):
                run_model(policy,BASE,question="zzqxx998877")

    def test_text_extraction_records_source_and_conflict_without_modifying_profile(self):
        profile={**BASE,"degree":"bachelor"}
        before=copy.deepcopy(profile)
        fields,_=parse_fields(["学历：硕士\n毕业日期：2025年6月30日"],profile)
        degree=next(c for c in fields if c["field"]=="degree")
        self.assertEqual(degree["value"],"master")
        self.assertTrue(degree["conflict"])
        self.assertEqual(degree["evidence"]["line"],1)
        self.assertTrue(all(c["requires_confirmation"] for c in fields))
        self.assertEqual(profile,before)

    def ledger(self):
        lines=["记录范围：2025-06 至 2026-09"]
        for i in range(16):
            month=add_months(date(2025,6,1),i).strftime("%Y-%m")
            lines.append(month+" "+("未参保" if i==0 else "正常"))
        return "\n".join(lines)

    def test_complete_ledger_ignores_unfinished_current_month(self):
        fields,_=parse_fields([self.ledger()+"\n2026-10 正常"],BASE)
        self.assertEqual(next(c["value"] for c in fields if c["field"]=="insurance_months"),15)
        self.assertEqual(next(c["value"] for c in fields if c["field"]=="insurance_start_date"),"2025-07-01")

    def test_missing_month_does_not_become_unpaid(self):
        fields,issues=parse_fields([self.ledger().replace("2026-08 正常\n","")],BASE)
        self.assertFalse(any(c["field"]=="insurance_months" for c in fields))
        self.assertTrue(any("缺行" in x for x in issues))

    def test_backpay_breaks_continuity(self):
        fields,_=parse_fields([self.ledger().replace("2026-08 正常","2026-08 补缴")],BASE)
        self.assertEqual(next(c["value"] for c in fields if c["field"]=="insurance_months"),1)

    def test_conflicting_month_status_blocks_calculation(self):
        fields,_=parse_fields([self.ledger()+"\n2026-08 补缴"],BASE)
        self.assertFalse(any(c["field"]=="insurance_months" for c in fields))

    def test_coverage_after_graduation_month_is_not_complete(self):
        fields,_=parse_fields([self.ledger().replace("记录范围：2025-06","记录范围：2025-07")],BASE)
        self.assertFalse(any(c["field"]=="insurance_months" for c in fields))

    def test_missing_graduation_requires_confirmation_first(self):
        fields,issues=parse_fields([self.ledger()],{**BASE,"graduation_date":None})
        self.assertFalse(fields)
        self.assertTrue(any("先确认" in i for i in issues))

    def test_ambiguous_graduation_dates_not_cherry_picked(self):
        fields,issues=parse_fields(["毕业日期：2025-06-30\n毕业日期：2024-06-30"],BASE)
        self.assertFalse(fields)
        self.assertTrue(issues)

    def test_invalid_material_encoding_rejected(self):
        with self.assertRaises(ValueError):
            extract_material({"filename":"test.pdf","content_base64":"!!!!"},BASE)

    def test_txt_works_without_optional_document_environment(self):
        with patch("materials.document_python",side_effect=ValueError("not configured")):
            result=extract_material({"filename":"example.txt","content_base64":base64.b64encode("学历：硕士".encode()).decode()},BASE)
        self.assertEqual(result["candidates"][0]["value"],"master")

    def test_real_sample_pdf_text_extraction(self):
        if not material_capabilities().get("pdf"):
            self.skipTest("optional PDF environment not configured")
        path=ROOT/"data/material_examples/insurance-demo.pdf"
        result=extract_material({"filename":path.name,"content_base64":base64.b64encode(path.read_bytes()).decode()},BASE)
        self.assertEqual(result["method"],"local_pdf_text")
        self.assertEqual(next(c["value"] for c in result["candidates"] if c["field"]=="insurance_months"),15)

    def annotation(self):
        # An artificial validator fixture, never exported as a human benchmark.
        return {"case_id":"unit-only","policy_id":FIRST,"profile":BASE,"source_policy_sha256":policy_hash(self.first),"expected":{"policy_id":FIRST,"conclusion":"insufficient","evidence_ids":[],"missing_fields":[],"materials":[],"explanation":"Unit fixture; not a real human annotation."},"review":{"status":"reviewed","reviewer":"test fixture","reviewed_at":"2026-10-21T08:00:00+08:00"}}

    def test_pending_drafts_cannot_be_scored_as_human(self):
        draft=json.loads((ROOT/"data/review_draft.json").read_text(encoding="utf-8"))
        self.assertEqual(len(draft["cases"]),36)
        self.assertTrue(all(r["expected"] is None and r["review"]["status"]=="pending" for r in draft["cases"]))
        with self.assertRaises(ValueError):
            reviewed_tasks(draft["cases"],self.policies)

    def test_reviewed_annotation_retains_provenance(self):
        tasks=reviewed_tasks([self.annotation()],self.policies)
        self.assertEqual(tasks[0]["source_type"],"reviewer_declared_annotation")

    def test_changed_policy_snapshot_rejected(self):
        row=self.annotation();row["source_policy_sha256"]="old"
        with self.assertRaises(ValueError):
            reviewed_tasks([row],self.policies)

    def test_missing_reviewer_rejected(self):
        row=self.annotation();row["review"]["reviewer"]=""
        with self.assertRaises(ValueError):
            reviewed_tasks([row],self.policies)

    def test_duplicate_review_case_ids_rejected(self):
        row=self.annotation()
        with self.assertRaises(ValueError):
            reviewed_tasks([row,row],self.policies)


class WorkflowHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        cls.server.store=PolicyStore(Path(cls.temp.name)/"http.sqlite3")
        cls.base="http://127.0.0.1:"+str(cls.server.server_port)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def call(self,path,body=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body else None,headers={"Content-Type":"application/json"})
        return urllib.request.urlopen(req,timeout=15)

    def test_material_text_upload(self):
        with self.call("/api/materials/extract",{"filename":"test.txt","content_base64":base64.b64encode("学历：硕士".encode()).decode(),"profile":BASE}) as response:
            self.assertEqual(json.load(response)["candidates"][0]["value"],"master")

    def test_draft_annotations_not_accepted_as_reviewed(self):
        draft=json.loads((ROOT/"data/review_draft.json").read_text(encoding="utf-8"))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call("/api/review/validate",{"cases":[draft["cases"][0]]})
        self.assertEqual(error.exception.code,400)

    def test_partial_draft_restore_uses_separate_endpoint(self):
        draft=json.loads((ROOT/"data/review_draft.json").read_text(encoding="utf-8"))
        with self.call("/api/review/restore",{"schema_version":1,"cases":[draft["cases"][0]]}) as response:
            restored=json.load(response)
        self.assertEqual(restored["cases"][0]["review"]["status"],"pending")

    def test_restore_checks_schema_version(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call("/api/review/restore",{"schema_version":2,"cases":[]})
        self.assertEqual(error.exception.code,400)

    def test_money_search_shows_policy_metadata_separate_from_clauses(self):
        from urllib.parse import urlencode
        with self.call("/api/search?"+urlencode({"q":"硕士生活补贴能领多少钱","as_of":"2026-10-21"})) as response:
            result=json.load(response)
        self.assertIn("硕士 3 万元",result["policy_summaries"][0]["amount_note"])
        self.assertTrue(result["results"])
        self.assertTrue(all("section" in r for r in result["results"]))

    def test_date_edit_validation_preserves_consistency(self):
        with self.call("/api/profile/validate",{"profile":BASE}) as response:
            self.assertEqual(json.load(response)["profile"],BASE)
        with self.assertRaises(urllib.error.HTTPError):
            self.call("/api/profile/validate",{"profile":{**BASE,"graduation_date":"2027-06-30"}})

    def test_sample_download_is_whitelisted(self):
        with self.call("/api/materials/example?id=graduation") as response:
            self.assertTrue(json.load(response)["synthetic"])
        with self.assertRaises(urllib.error.HTTPError):
            self.call("/api/materials/example?id=../../app.py")


if __name__=="__main__":
    unittest.main()
