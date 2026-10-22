"""Validate reviewer-declared annotations; never turn generated labels into human data."""
from datetime import datetime
import hashlib
import json

from core import RAW_FIELDS, validate_profile
from llm import validate_completion


def restore_drafts(rows, policies):
    """Restore partial work; pending records never become human annotations."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("每次恢复 1—200 条复核草稿")
    catalogue = {p["id"]: p for p in policies}
    restored, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str) or not 1 <= len(row["case_id"]) <= 120 or row["case_id"] in seen:
            raise ValueError("复核案例编号无效或重复")
        seen.add(row["case_id"])
        policy = catalogue.get(row.get("policy_id"))
        if policy is None or row.get("source_policy_sha256") != policy_hash(policy):
            raise ValueError("草稿所依据的政策版本与当前快照不一致，请保留原文件并重新核对来源")
        profile = validate_profile(row.get("profile"))
        review = row.get("review")
        if not isinstance(review, dict) or review.get("status") not in {"pending", "reviewed"}:
            raise ValueError("草稿复核状态无效")
        title = row.get("title", policy["title"])
        if not isinstance(title, str) or len(title) > 200:
            raise ValueError("草稿标题过长或无效")
        clean = {"case_id": row["case_id"], "title": title, "policy_id": policy["id"], "profile": profile,
                 "source_policy_sha256": row["source_policy_sha256"]}
        if review["status"] == "reviewed":
            reviewed_tasks([row], policies)
            clean.update(expected=row["expected"], review=review)
        else:
            clean.update(expected=None, review={"status": "pending", "reviewer": None, "reviewed_at": None})
        annotation = row.get("draft_annotation")
        if annotation is not None:
            allowed = {"conclusion", "evidence_ids", "missing_fields", "materials", "explanation", "reviewer"}
            if not isinstance(annotation, dict) or set(annotation) - allowed:
                raise ValueError("草稿填写内容含未知字段")
            if annotation.get("conclusion", "") not in {"", "eligible", "ineligible", "insufficient"}:
                raise ValueError("草稿结论无效")
            for field, choices in (("evidence_ids", {c["id"] for c in policy["clauses"]}), ("materials", {m["id"] for m in policy["materials"]}), ("missing_fields", RAW_FIELDS - {"city"})):
                values = annotation.get(field, [])
                if not isinstance(values, list) or any(not isinstance(v, str) or v not in choices for v in values) or len(values) != len(set(values)):
                    raise ValueError("草稿的依据、缺失信息或准备清单无效")
            for field, limit in (("explanation", 3000), ("reviewer", 80)):
                if not isinstance(annotation.get(field, ""), str) or len(annotation.get(field, "")) > limit:
                    raise ValueError("草稿说明或复核者标识过长或无效")
            normalized = {"conclusion": "", "evidence_ids": [], "missing_fields": [], "materials": [], "explanation": "", "reviewer": "", **annotation}
            # A changed confirmed row must be pending. Never silently ignore edits.
            if review["status"] == "reviewed" and any(normalized[k] != row["expected"][k] for k in ("conclusion", "evidence_ids", "missing_fields", "materials", "explanation")):
                raise ValueError("已复核记录的草稿与确认内容不同，请先标为待复核再恢复")
            clean["draft_annotation"] = normalized
        restored.append(clean)
    return restored


def policy_hash(policy):
    return hashlib.sha256(json.dumps(policy,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def reviewed_tasks(rows, policies):
    if not isinstance(rows,list) or not 1<=len(rows)<=200:
        raise ValueError("每次导入 1—200 条已复核标注")
    catalogue={p["id"]:p for p in policies}
    tasks=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("case_id"),str) or not 1<=len(row["case_id"])<=120 or row["case_id"] in seen:
            raise ValueError("复核案例编号无效或重复")
        seen.add(row["case_id"])
        policy=catalogue.get(row.get("policy_id"))
        if policy is None or row.get("source_policy_sha256")!=policy_hash(policy):
            raise ValueError("复核所依据的政策版本与当前快照不一致")
        profile=validate_profile(row.get("profile"))
        review=row.get("review")
        if not isinstance(review,dict) or review.get("status")!="reviewed" or not isinstance(review.get("reviewer"),str) or not 1<=len(review["reviewer"].strip())<=80:
            raise ValueError("标注尚未人工确认，或未填写复核者")
        try:
            timestamp=datetime.fromisoformat(review["reviewed_at"].replace("Z","+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("missing timezone")
        except (ValueError,KeyError,AttributeError,TypeError):
            raise ValueError("复核时间须为带时区的 ISO 时间") from None
        expected=row.get("expected")
        if not isinstance(expected,dict):
            raise ValueError("复核结论未填写")
        validate_completion(expected,policy,RAW_FIELDS)
        if not expected["explanation"].strip():
            raise ValueError("请记录人工判断依据")
        gold={**expected,"allowed_evidence_ids":[c["id"] for c in policy["clauses"]],"allowed_materials":[m["id"] for m in policy["materials"]],"allowed_missing_fields":sorted(RAW_FIELDS)}
        tasks.append({"case_id":row["case_id"],"policy_id":policy["id"],"profile":profile,"source_policy_sha256":row["source_policy_sha256"],"source_type":"reviewer_declared_annotation","review":review,"ground_truth":gold})
    return tasks
