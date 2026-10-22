"""Rule-derived follow-ups and an explicit audit of independent model output.

This layer never rewrites a model prediction or claims to verify its prose.
"""
from datetime import date, timedelta

from core import FIELD_LABELS, add_months, assess_policy
from policy_time import available


QUESTIONS = {
    "insurance_months": "从有效连续起算月开始，已经完整缴纳了几个月？请剔除补缴和未完成月份。",
    "insurance_start_date": "毕业当月或以后，符合条件且不含补缴的连续参保从哪个月开始？",
    "employer_qualified": "单位是否满足原指南中的税务或登记要求？可请单位人事核对，不能只看办公地址。",
    "family_has_home": "按政策的家庭口径，申请家庭在杭州是否有房？请核对原文中的家庭范围。",
    "other_housing_benefit": "是否正在享受其他租房优惠？请核对政策所列互斥待遇。",
    "first_installment_received": "本次学历的生活补贴首笔是否已经领取？不同笔次的要求不同。",
    "rent_first_received": "是否已经领取过此次租房补贴的首笔？",
}


def reference_fields(policy, result):
    """The public structured contract, also used for synthetic weak labels."""
    decisive = result["checks"]
    if result["conclusion"] == "ineligible":
        decisive = [r for r in decisive if r["status"] == "fail"]
    elif result["conclusion"] == "insufficient":
        decisive = [r for r in decisive if r["status"] == "unknown"]
    return {
        "policy_id": policy["id"], "conclusion": result["conclusion"],
        "evidence_ids": sorted({r["citation"] for r in decisive}),
        "missing_fields": result["missing_fields"],
        "materials": sorted(m["id"] for m in policy["materials"]) if result["conclusion"] != "ineligible" else [],
        "explanation": result["reason"],
    }


def audit_model(policy, profile, prediction):
    """Compare structured fields with the local reference, without editing them."""
    from presentation import field_value
    baseline = assess_policy(policy, profile)
    expected = reference_fields(policy, baseline)
    issues = []
    if prediction["conclusion"] != expected["conclusion"]:
        issues.append({"field": "conclusion", "severity": "review", "code": "conclusion_conflict", "message": "模型结论与已录入规则不一致，请逐条核对。"})
    for field, label in (("evidence_ids", "依据条款"), ("missing_fields", "缺失信息"), ("materials", "准备清单")):
        actual, wanted = set(prediction[field]), set(expected[field])
        missing, extra = sorted(wanted-actual), sorted(actual-wanted)
        if not missing and not extra:
            continue
        # Additional existing citations and preparation items are informational;
        # missing decisive citations or differing missing fields require review.
        severity = "review" if field == "missing_fields" or (field == "evidence_ids" and missing) else "note"
        issues.append({"field": field, "severity": severity, "code": field+"_difference", "message": label+"与规则参考不完全一致。", "missing": missing, "extra": extra})
    return {
        "status": "needs_review" if any(i["severity"] == "review" for i in issues) else "aligned",
        "reference_conclusion": baseline["conclusion"], "issues": issues,
        "blocking_checks": [{**r, "actual_label": field_value(r["field"], profile.get(r["field"], r["actual"]))} for r in baseline["checks"] if r["status"] in {"fail", "unknown"}],
        "next_action": "先核对下列具体条件和原文，再向受理系统确认；本次模型输出不作为通过建议。" if any(i["severity"] == "review" for i in issues) else "结构化字段与规则参考一致，解释文字和现行资格仍需核验。",
        "reference": expected,
        "notice": "这是与人工整理规则的结构化对照，不验证解释文字，也不证明政策资格正确；模型原始结果完整保留。",
    }


def timeline_for(policy, profile):
    """Dates from already encoded rules; no prediction of approval/payment."""
    rules = {r["field"]: r for r in policy["rules"]}
    grad = date.fromisoformat(profile["graduation_date"]) if profile.get("graduation_date") else None
    start = date.fromisoformat(profile["insurance_start_date"]).replace(day=1) if profile.get("insurance_start_date") else None
    app = date.fromisoformat(profile["application_date"])
    rows = []
    if grad and "within_24_months" in rules:
        end = add_months(grad, 24)
        rows.append({"label": "毕业后两年边界", "date": end.isoformat(), "days_from_reference": (end-app).days, "citation": rules["within_24_months"]["citation"]})
    if start:
        for field, n, label in (("six_months_within_18", 6, "连续参保第 6 个月月末"), ("twelve_months_within_24", 12, "连续参保第 12 个月月末")):
            if field in rules:
                end = add_months(start, n)-timedelta(days=1)
                rows.append({"label": label, "date": end.isoformat(), "days_from_reference": (end-app).days, "citation": rules[field]["citation"]})
        if "first_payment_ready" in rules:
            end = add_months(start, 6)
            rows.append({"label": "满 6 个月后的申领月份起点", "date": end.isoformat(), "days_from_reference": (end-app).days, "citation": rules["first_payment_ready"]["citation"]})
    return rows


def build_guidance(policies, profile, results):
    questions = {}
    for result in results:
        # Do not ask unnecessary questions for a policy already ruled out.
        if result["conclusion"] != "insufficient":
            continue
        policy = next(p for p in policies if p["id"] == result["policy_id"])
        if not available(policy, profile["application_date"]):
            continue
        if any(c["kind"] == "scope" and c["status"] == "unknown" and c["actual"] is not None for c in result["checks"]):
            continue
        for field in result["missing_fields"]:
            q = questions.setdefault(field, {"field": field, "label": FIELD_LABELS.get(field, field), "question": QUESTIONS.get(field, "请补充或确认"+FIELD_LABELS.get(field, field)+"。"), "policy_ids": []})
            q["policy_ids"].append(result["policy_id"])
    return {"followups": sorted(questions.values(), key=lambda q: (-len(q["policy_ids"]), q["field"])), "notice": "优先补充影响多项待核验政策的信息；已有不满足条件的事项不重复追问。"}
