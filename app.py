"""Huicaitong local MVP. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import assess_all, validate_profile, TODAY
from fixtures import CASES, evaluate
from llm import model_config, run_model
from rag import retrieve
from store import PolicyStore
from core import FIELD_LABELS
from materials import extract_material, material_capabilities
from policy_time import available
from review import reviewed_tasks, restore_drafts

ROOT = Path(__file__).resolve().parent


def training_status():
    status={}
    for phase in ("sft","grpo"):
        for folder in (phase,phase+"-smoke"):
            report=ROOT/"checkpoints"/folder/"run_summary.json"
            if report.exists():
                try:
                    data=json.loads(report.read_text(encoding="utf-8"))
                    status[phase]={k:data.get(k) for k in ("steps_completed","smoke_run","nonzero_gradient_steps","reward_signal_steps","max_gpu_allocated_gb")}
                    break
                except (OSError,ValueError):
                    continue
    return status


def selected_model():
    path=ROOT/"checkpoints"/"selection.json"
    if path.exists():
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            return {k:data.get(k) for k in ("model_id","experiment_adapter","criterion","selected_metrics","warning")}
        except (OSError,ValueError):
            pass
    return None


def model_evaluations():
    reports=[]
    for label,scope,filename in (
        ("初始未平衡 GRPO","开发验证前 12 条","grpo-validation-smoke-evaluation.json"),
        ("平衡 SFT · 300 步","同一开发验证前 12 条","sft-balanced-validation-smoke-evaluation.json"),
        ("平衡 GRPO · 20 步","同一开发验证前 12 条","grpo-balanced-validation-smoke-evaluation.json"),
        ("平衡 GRPO · 留出资料","租房文件族前 12 条","grpo-heldout-smoke-evaluation.json"),
        ("原平衡 GRPO · 完整开发集","全部 92 条开发验证","grpo-development-full-evaluation.json"),
        ("单字段对照 SFT · 500 步","同一完整开发集","sft-counterfactual-development-evaluation.json"),
        ("单字段对照 GRPO · 20 步","同一完整开发集","grpo-counterfactual-development-evaluation.json"),
        ("冻结默认模型 · 后续检查","此前未预测的租房 48 条","selected-v2-heldout-evaluation.json"),
    ):
        path=ROOT/"training-runs"/filename
        if path.exists():
            try:
                data=json.loads(path.read_text(encoding="utf-8"))
                reports.append({"label":label,"scope":scope,"cases":data["cases"],"correct":round(data["cases"]*data["conclusion_accuracy"]),"valid_output_rate":data["valid_output_rate"],"evidence_f1":data["mean_evidence_f1"],"structured_exact_match":data.get("structured_exact_match"),"per_class":data.get("per_class"),"per_policy":data.get("per_policy"),"error_counts":data.get("error_counts")})
            except (OSError,ValueError,KeyError):
                continue
    return reports


def load_env():
    file = ROOT / ".env.local"
    if file.exists():
        for line in file.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key,value = line.split("=",1)
            if key.strip().startswith("HCT_"):
                os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))


class Handler(BaseHTTPRequestHandler):
    server_version = "Huicaitong/0.4"

    def log_message(self, fmt, *args):
        # Do not write questions or applicant profiles to access logs.
        pass

    def send_json(self, data, status=200):
        raw = json.dumps(data,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(raw)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def trusted_request(self):
        host = urlparse("http://"+self.headers.get("Host","")).hostname
        if host not in {"127.0.0.1","localhost","::1"}:
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme != "http" or parsed.netloc != self.headers.get("Host"):
                return False
        return True

    def do_GET(self):
        if not self.trusted_request():
            self.send_json({"error":"仅允许本机访问"},403)
            return
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                self.api_get(parsed)
            except (ValueError,TypeError) as e:
                self.send_json({"error":str(e)},400)
            return
        public = {"/":"index.html", "/index.html":"index.html", "/styles.css":"styles.css", "/app.js":"app.js", "/workflow.js":"workflow.js", "/workflow.css":"workflow.css", "/ux.js":"ux.js", "/ux.css":"ux.css", "/icon.svg":"icon.svg"}
        if parsed.path not in public:
            self.send_json({"error":"页面不存在"},404)
            return
        path = ROOT / "web" / public[parsed.path]
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(str(path))[0] or "application/octet-stream")+"; charset=utf-8")
        self.send_header("Content-Length",str(len(raw)))
        self.send_header("Cache-Control","no-cache")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)

    def api_get(self, parsed):
        policies = self.server.store.all()
        if parsed.path == "/api/health":
            self.send_json({"ok":True,"version":"0.4.0"})
        elif parsed.path == "/api/meta":
            cfg = model_config()
            self.send_json({"city":"杭州","snapshot_date":TODAY,"checked_on":self.server.store.seed["checked_on"],"policies":len([p for p in policies if p["status"]=="included"]),"clauses":sum(len(p["clauses"]) for p in policies if p["status"]=="included"),"retriever":"中文字词 BM25（本地词法检索）","model_configured":cfg["configured"],"model_name":cfg["model"],"training":training_status(),"selected_model":selected_model(),"model_evaluations":model_evaluations(),"notice":self.server.store.seed["notice"]})
        elif parsed.path == "/api/policies":
            self.send_json({"policies":policies})
        elif parsed.path == "/api/examples":
            self.send_json({"examples":[{"name":c["id"],"profile":c["profile"]} for c in CASES]})
        elif parsed.path == "/api/materials/capabilities":
            self.send_json(material_capabilities())
        elif parsed.path == "/api/materials/examples":
            self.send_json({"examples":[{"id":"graduation","title":"毕业材料 · 合成 PDF","filename":"graduation-demo.pdf"},{"id":"insurance","title":"连续参保 · 合成 PDF","filename":"insurance-demo.pdf"},{"id":"gap","title":"参保中断 · 合成 TXT","filename":"insurance-gap-demo.txt"}]})
        elif parsed.path == "/api/materials/example":
            key=parse_qs(parsed.query).get("id",[""])[0]
            names={"graduation":"graduation-demo.pdf","insurance":"insurance-demo.pdf","gap":"insurance-gap-demo.txt"}
            if key not in names:
                raise ValueError("请选择已提供的合成材料")
            path=ROOT/"data"/"material_examples"/names[key]
            self.send_json({"filename":path.name,"content_base64":base64.b64encode(path.read_bytes()).decode(),"synthetic":True})
        elif parsed.path == "/api/review/draft":
            draft=json.loads((ROOT/"data"/"review_draft.json").read_text(encoding="utf-8"))
            self.send_json({**draft,"field_labels":FIELD_LABELS})
        elif parsed.path == "/api/search":
            params = parse_qs(parsed.query)
            as_of = params.get("as_of",[TODAY])[0]
            date.fromisoformat(as_of)
            query=params.get("q",[""])[0]
            hits=retrieve(policies,query,as_of,include_archived=params.get("history",["0"])[0]=="1")
            summaries=[]
            if any(word in query for word in ("多少","金额","标准","怎么领","哪里","渠道","办理","申报")):
                seen=set()
                for hit in hits:
                    policy=next(p for p in policies if p["id"]==hit["policy_id"])
                    family=policy.get("family",policy["id"])
                    if family in seen:
                        continue
                    seen.add(family)
                    summaries.append({**{k:policy.get(k) for k in ("id","title","amount_label","amount_note","application_channel","source_url","published_on","legal_status")},"outside_reference_period":hit["outside_reference_period"]})
            self.send_json({"results":hits,"policy_summaries":summaries,"method":"bm25","as_of":as_of})
        else:
            self.send_json({"error":"接口不存在"},404)

    def do_POST(self):
        if not self.trusted_request():
            self.send_json({"error":"请求来源不受信任"},403)
            return
        if self.headers.get("Content-Type","").split(";")[0].strip() != "application/json":
            self.send_json({"error":"请使用 application/json"},415)
            return
        try:
            size = int(self.headers.get("Content-Length","0"))
            route = urlparse(self.path).path
            maximum=2_900_000 if route=="/api/materials/extract" else 512_000
            if not 0 < size <= maximum:
                raise ValueError("请求体超过该接口的大小限制")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body,dict):
                raise ValueError("请求须为 JSON 对象")
            policies = self.server.store.all()
            route = urlparse(self.path).path
            if route == "/api/assess":
                result = assess_all(policies,body.get("profile",{}))
                question = body.get("question") or "杭州应届毕业生生活补贴 租房补贴 申请条件 社保 材料"
                result["evidence"] = retrieve(policies,question,result["as_of"])
                self.send_json(result)
            elif route == "/api/model-assess":
                p = validate_profile(body.get("profile",{}))
                policy = next((x for x in policies if x["id"]==body.get("policy_id") and available(x,p["application_date"])),None)
                if not policy:
                    raise ValueError("请选择在所选日期可用的政策")
                self.send_json(run_model(policy,p,question=body.get("question"),evidence_mode=body.get("evidence_mode","retrieval")))
            elif route == "/api/materials/extract":
                self.send_json(extract_material(body,validate_profile(body.get("profile",{}))))
            elif route == "/api/profile/validate":
                self.send_json({"profile":validate_profile(body.get("profile",{}))})
            elif route == "/api/review/validate":
                tasks=reviewed_tasks(body.get("cases"),policies)
                self.send_json({"reviewed_cases":len(tasks),"notice":"记录结构与政策快照验证通过；复核内容质量仍由复核者负责。"})
            elif route == "/api/review/restore":
                if body.get("schema_version") != 1:
                    raise ValueError("草稿格式版本无效，当前支持 schema_version 1")
                cases=restore_drafts(body.get("cases"),policies)
                self.send_json({"cases":cases,"notice":"草稿已恢复。待复核记录仍为待复核，不计入人工基准。"})
            elif route == "/api/evaluate":
                self.send_json(evaluate(policies))
            elif route == "/api/import":
                count = self.server.store.import_policies(body)
                self.send_json({"imported":count})
            else:
                self.send_json({"error":"接口不存在"},404)
        except (ValueError,TypeError,KeyError,OverflowError) as e:
            self.send_json({"error":str(e)},400)
        except Exception:
            self.send_json({"error":"服务内部错误，请在本机终端检查后重试。"},500)


def main():
    parser = argparse.ArgumentParser(description="惠才通 · 杭州人才服务研究原型")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--open-browser",action="store_true")
    args = parser.parse_args()
    load_env()
    model_config()
    server = ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    server.store = PolicyStore()
    print(f"Huicaitong ready: http://127.0.0.1:{args.port}",flush=True)
    print("Local only. Applicant profiles are not saved. Ctrl+C to stop.",flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
