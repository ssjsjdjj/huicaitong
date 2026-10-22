"""SQLite policy catalogue; applicant profiles are never persisted."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from core import RAW_FIELDS, DERIVED_DEPENDENCIES

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "policies.json"


def validate_policy(p):
    if not isinstance(p, dict):
        raise ValueError("政策须为对象")
    required = {"id", "family", "title", "category", "summary", "amount_label", "amount_note", "status", "published_on", "source_title", "source_org", "source_url", "checked_on", "coverage", "application_channel", "scope", "rules", "materials", "clauses"}
    if required - p.keys():
        raise ValueError("政策缺少字段：" + ", ".join(sorted(required-p.keys())))
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,79}", p["id"]):
        raise ValueError("政策 id 须为 3—80 位英文小写、数字、下划线或短横线")
    for k in required - {"scope","rules","materials","clauses"}:
        if not isinstance(p[k], str) or len(p[k]) > 4000:
            raise ValueError("政策文本字段无效："+k)
    if p["status"] not in {"included", "archived", "reference"}:
        raise ValueError("无效的收录状态")
    for key in ("published_on", "checked_on"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",p[key]):
            raise ValueError("政策日期须为 YYYY-MM-DD")
        date.fromisoformat(p[key])
    source = urlparse(p["source_url"])
    for key in ("effective_from","effective_until"):
        value=p.get(key)
        if value is not None:
            if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):
                raise ValueError("政策适用期间须为 YYYY-MM-DD 或 null")
            date.fromisoformat(value)
    if p.get("effective_from") and p.get("effective_until") and p["effective_from"]>p["effective_until"]:
        raise ValueError("政策适用期间顺序错误")
    if source.scheme not in {"http","https"} or not source.hostname or source.username:
        raise ValueError("来源必须是有效 HTTP(S) 链接")
    for key in ("clauses", "materials", "scope", "rules"):
        if not isinstance(p[key], list) or len(p[key]) > 100:
            raise ValueError("无效的政策列表："+key)
    ids = set()
    for c in p["clauses"]:
        if not isinstance(c,dict) or set(c) != {"id","section","text"} or not all(isinstance(v,str) for v in c.values()):
            raise ValueError("证据条款需要 id、section、text")
        if not re.fullmatch(r"[a-z0-9_-]{2,100}",c["id"]) or c["id"] in ids or len(c["text"]) > 5000:
            raise ValueError("条款 id 重复或条款过长")
        ids.add(c["id"])
    for r in p["scope"] + p["rules"]:
        if not isinstance(r,dict) or set(r) != {"field","op","value","label","citation"}:
            raise ValueError("规则需要 field、op、value、label、citation")
        if r["field"] not in RAW_FIELDS | set(DERIVED_DEPENDENCIES) or r["op"] not in {"eq","gte","lte","in"}:
            raise ValueError("规则字段或运算符不受支持")
        if r["citation"] not in ids or not isinstance(r["label"],str):
            raise ValueError("规则引用了不存在的条款")
        if r["op"] == "in" and not isinstance(r["value"],list):
            raise ValueError("in 规则的 value 须为列表")
        if r["op"] in {"gte","lte"} and (type(r["value"]) not in {int,float,str}):
            raise ValueError("比较规则需要数字或日期字符串")
    material_ids = set()
    for m in p["materials"]:
        if not isinstance(m,dict) or set(m) != {"id","label","kind","citation"} or not all(isinstance(v,str) for v in m.values()):
            raise ValueError("准备清单需要 id、label、kind、citation")
        if m["citation"] not in ids or m["id"] in material_ids:
            raise ValueError("准备清单引用错误或编号重复")
        material_ids.add(m["id"])
    if p["status"] == "included" and not p["rules"]:
        raise ValueError("参与初筛的政策至少需要一条规则")
    return p


class PolicyStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else ROOT / "runtime" / "policies.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seed = json.loads(DATA.read_text(encoding="utf-8"))
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, body TEXT NOT NULL, origin TEXT NOT NULL)")
            for p in self.seed["policies"]:
                validate_policy(p)
                db.execute("INSERT INTO policies VALUES (?,?, 'seed') ON CONFLICT(id) DO UPDATE SET body=excluded.body WHERE policies.origin='seed'", (p["id"],json.dumps(p,ensure_ascii=False)))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM policies ORDER BY rowid")]

    def import_policies(self, payload):
        if not isinstance(payload,dict) or payload.get("city") != "杭州" or not isinstance(payload.get("policies"),list):
            raise ValueError("导入格式为 {city: 杭州, policies: [...]}，请参考 data/policies.json")
        incoming = payload["policies"]
        if not 1 <= len(incoming) <= 30:
            raise ValueError("每次可导入 1—30 份政策")
        for p in incoming:
            validate_policy(p)
        current = self.all()
        used_ids = {p["id"] for p in current}
        used_clauses = {c["id"] for p in current for c in p["clauses"]}
        for p in incoming:
            if p["id"] in used_ids:
                raise ValueError("政策 id 已存在，请为新版本使用新 id："+p["id"])
            for c in p["clauses"]:
                if c["id"] in used_clauses:
                    raise ValueError("证据编号须全库唯一："+c["id"])
                used_clauses.add(c["id"])
            used_ids.add(p["id"])
        with self.connect() as db:
            for p in incoming:
                db.execute("INSERT INTO policies VALUES (?,?,'import')", (p["id"],json.dumps(p,ensure_ascii=False)))
        return len(incoming)
