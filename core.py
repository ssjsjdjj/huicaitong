"""Auditable three-valued screening. No LLM is used in this reference evaluator."""
from __future__ import annotations

import calendar
import re
from datetime import date
from policy_time import available

TODAY = "2026-10-21"  # Reproducible competition snapshot; UI sends its chosen date.
DEGREES = {"college": 1, "bachelor": 2, "master": 3, "phd": 4}
BOOL_FIELDS = {"employed_hangzhou", "employer_qualified", "insurance_current", "insurance_without_backpay", "prior_other_degree_subsidy", "degree_while_employed", "first_installment_received", "family_has_home", "other_housing_benefit", "rent_first_received"}
DATE_FIELDS = {"graduation_date", "application_date", "insurance_start_date"}
ENUMS = {"degree": set(DEGREES), "study_mode": {"fulltime", "parttime"}, "school_region": {"mainland", "overseas"}, "nationality": {"cn", "other"}}
RAW_FIELDS = BOOL_FIELDS | DATE_FIELDS | set(ENUMS) | {"insurance_months", "city"}
DERIVED_DEPENDENCIES = {
    "degree_rank": ["degree"], "graduated": ["graduation_date"],
    "within_24_months": ["graduation_date"],
    "insurance_start_within_12": ["graduation_date", "insurance_start_date"],
    "six_months_within_18": ["graduation_date", "insurance_start_date"],
    "twelve_months_within_24": ["graduation_date", "insurance_start_date"],
    "first_payment_ready": ["insurance_start_date"],
}
FIELD_LABELS = {
    "degree":"学历", "study_mode":"学习形式", "school_region":"毕业高校类型", "nationality":"国籍", "graduation_date":"毕业日期", "application_date":"申请日期", "insurance_start_date":"毕业后有效连续参保首月", "insurance_months":"已完成的有效连续参保月数", "employed_hangzhou":"在杭就业或创业情况", "employer_qualified":"用人单位是否符合指南要求", "insurance_current":"当前在合格杭州单位参保情况", "insurance_without_backpay":"连续时长是否不含补缴", "prior_other_degree_subsidy":"是否曾以其他学历享受生活补贴", "degree_while_employed":"是否在职取得本次学历", "first_installment_received":"本次学历首笔领取情况", "family_has_home":"申请家庭在杭住房情况", "other_housing_benefit":"其他租房优惠享受情况", "rent_first_received":"租房补贴首笔领取情况"
}


def add_months(d: date, n: int) -> date:
    month = d.year * 12 + d.month - 1 + n
    y, m = divmod(month, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def validate_profile(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("申请信息必须为 JSON 对象")
    unknown = set(raw) - RAW_FIELDS
    if unknown:
        raise ValueError("未知字段：" + ", ".join(sorted(unknown)))
    p = {k: (None if v == "" else v) for k, v in raw.items()}
    p.setdefault("application_date", TODAY)
    p.setdefault("city", "杭州")
    if p["city"] != "杭州":
        raise ValueError("当前知识库仅支持杭州")
    for key in BOOL_FIELDS:
        if p.get(key) is not None and type(p[key]) is not bool:
            raise ValueError(FIELD_LABELS[key] + "须为 true、false 或 null")
    for key, options in ENUMS.items():
        if p.get(key) is not None and p[key] not in options:
            raise ValueError("无效的" + FIELD_LABELS[key])
    for key in DATE_FIELDS:
        if p.get(key) is not None:
            try:
                if not isinstance(p[key],str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",p[key]):
                    raise ValueError("invalid ISO date")
                date.fromisoformat(p[key])
            except (ValueError, TypeError):
                raise ValueError(FIELD_LABELS[key] + "须为 YYYY-MM-DD") from None
    if not p.get("application_date"):
        raise ValueError("请选择申请日期")
    app = date.fromisoformat(p["application_date"])
    months = p.get("insurance_months")
    if months is not None and (type(months) is not int or not 0 <= months <= 600):
        raise ValueError("连续参保月数须为 0—600 的整数")
    if p.get("insurance_start_date"):
        start = date.fromisoformat(p["insurance_start_date"]).replace(day=1)
        if start > app:
            raise ValueError("有效连续参保首月不能晚于申请日期")
        # Excludes the current unfinished insurance month.
        maximum = (app.year - start.year) * 12 + app.month - start.month
        if months is not None and months > maximum:
            raise ValueError("已完成的连续月数超过起算月至申请日前可完成的月数，请核对")
        if p.get("graduation_date"):
            grad_month = date.fromisoformat(p["graduation_date"]).replace(day=1)
            if start < grad_month:
                raise ValueError("请输入毕业当月或以后有效连续参保的首月，毕业前时长不能直接计入")
    return p


def features(p: dict) -> dict:
    f = dict(p)
    app = date.fromisoformat(p["application_date"])
    grad = date.fromisoformat(p["graduation_date"]) if p.get("graduation_date") else None
    start = date.fromisoformat(p["insurance_start_date"]).replace(day=1) if p.get("insurance_start_date") else None
    f["degree_rank"] = DEGREES.get(p.get("degree"))
    f["graduated"] = grad <= app if grad else None
    f["within_24_months"] = grad <= app <= add_months(grad, 24) if grad else None
    f["insurance_start_within_12"] = grad.replace(day=1) <= start <= add_months(grad, 12) if grad and start else None
    # Six insurance months finish on the last day of their sixth calendar month.
    six_end = date.fromordinal(add_months(start, 6).toordinal() - 1) if start else None
    twelve_end = date.fromordinal(add_months(start, 12).toordinal() - 1) if start else None
    f["six_months_within_18"] = six_end <= add_months(grad, 18) if grad and start else None
    f["twelve_months_within_24"] = twelve_end <= add_months(grad, 24) if grad and start else None
    f["first_payment_ready"] = app >= add_months(start, 6) if start else None
    return f


def compare(actual, op, expected):
    if actual is None:
        return None
    if op == "eq":
        return actual == expected
    if op == "gte":
        return actual >= expected
    if op == "lte":
        return actual <= expected
    if op == "in":
        return actual in expected
    raise ValueError("不支持的规则运算符")


def assess_policy(policy: dict, p: dict) -> dict:
    f = features(p)
    rows, missing, citations = [], set(), set()
    unavailable = not available(policy, p["application_date"])
    outside_scope = False
    for kind in ("scope", "rules"):
        for rule in policy.get(kind, []):
            value = f.get(rule["field"])
            ok = compare(value, rule["op"], rule["value"])
            if kind == "scope" and ok is False:
                outside_scope = True
            state = "unknown" if ok is None or (kind == "scope" and ok is False) else ("pass" if ok else "fail")
            if state == "unknown" and value is None:
                for dep in DERIVED_DEPENDENCIES.get(rule["field"], [rule["field"]]):
                    if p.get(dep) is None:
                        missing.add(dep)
            rows.append({"field": rule["field"], "label": rule["label"], "status": state, "actual": value, "citation": rule["citation"], "kind": kind})
            citations.add(rule["citation"])
    if unavailable:
        conclusion, reason = "insufficient", "该资料未纳入当前初筛，或发布时间／已记录的适用期间与申请日期不符。"
    elif outside_scope:
        conclusion, reason = "insufficient", "你的情形超出本版自动规则覆盖范围，需要按原指南人工核验；这不代表不符合政策。"
    elif any(r["status"] == "fail" for r in rows):
        conclusion, reason = "ineligible", "至少一项已录入条件暂不满足，可展开查看具体条款。"
    elif any(r["status"] == "unknown" for r in rows):
        conclusion, reason = "insufficient", "有决定性信息尚未提供，补充后可重新核对。"
    else:
        conclusion, reason = "eligible", "已录入条件初筛通过；文件现行效力及完整资格仍需受理系统确认。"
    return {"policy_id": policy["id"], "title": policy["title"], "conclusion": conclusion, "reason": reason, "checks": rows, "missing_fields": sorted(missing), "missing_labels": [FIELD_LABELS.get(k,k) for k in sorted(missing)], "evidence_ids": sorted(citations), "materials": policy.get("materials", []), "source_url": policy["source_url"], "scope_note": policy["coverage"], "amount_label": policy["amount_label"], "amount_note": policy["amount_note"], "application_channel": policy["application_channel"]}


def assess_all(policies: list[dict], raw: dict) -> dict:
    p = validate_profile(raw)
    results = [assess_policy(x, p) for x in policies if x["status"] == "included"]
    from guidance import build_guidance, timeline_for
    from presentation import display_for
    for result in results:
        policy = next(x for x in policies if x["id"] == result["policy_id"])
        applicable_scope = all(c["status"] == "pass" for c in result["checks"] if c["kind"] == "scope")
        result["timeline"] = timeline_for(policy, p) if applicable_scope and available(policy, p["application_date"]) else []
        result["display"] = display_for(policy, p, result, policies)
    return {"mode": "rule_baseline", "mode_label": "可审计规则基线 · 未使用大模型", "profile": p, "results": results, "guidance": build_guidance(policies, p, results), "as_of": p["application_date"], "notice": "初筛不是审批结论。当前为人工整理规则，未连接模型时不会声称由模型或 GRPO 生成。"}
