"""User-facing explanations of existing snapshot data, separate from rule labels."""
from datetime import date
from decimal import Decimal
import re

from core import FIELD_LABELS, add_months

DEGREES = {"college": "大专", "bachelor": "本科", "master": "硕士", "phd": "博士"}


def readable(value):
    if value is None:
        return "待确认"
    if type(value) is bool:
        return "是" if value else "否"
    return DEGREES.get(value, str(value)) if isinstance(value, str) else str(value)


def field_value(field, value):
    meanings = {
        "first_installment_received": ("尚未领取本次学历生活补贴首笔", "已领取本次学历生活补贴首笔"),
        "rent_first_received": ("尚未领取租房补贴首笔", "已领取租房补贴首笔"),
        "prior_other_degree_subsidy": ("未以其他学历享受生活补贴", "已以其他学历享受生活补贴"),
        "degree_while_employed": ("非在职取得本次学历", "在职取得本次学历"),
        "family_has_home": ("申请家庭在杭州无房", "申请家庭在杭州有房"),
        "other_housing_benefit": ("未享受其他租房优惠", "已享受其他租房优惠"),
        "insurance_without_backpay": ("所填连续时长包含补缴", "所填连续时长不包含补缴"),
        "employed_hangzhou": ("未在杭州就业或创业", "已在杭州就业或创业"),
        "employer_qualified": ("已填单位不符合指南要求", "已填单位符合指南要求"),
        "insurance_current": ("已填当前未在合格杭州单位参保", "已填当前在合格杭州单位参保"),
    }
    return meanings[field][int(value)] if field in meanings and type(value) is bool else readable(value)


def benefit_for(policy, profile, policies):
    """Compute only explicit, unambiguous shares from the recorded notes."""
    summary = {"label": policy["amount_label"], "basis": policy["amount_note"],
               "standard_note": policy["amount_note"], "reference_yuan": None,
               "notice": "按已收录资料口径展示，不是获批或实际到账金额；现行标准仍需官方确认。"}
    degree = DEGREES.get(profile.get("degree"))
    if policy["id"] in {"hz-living-first-2024", "hz-living-second-2024"}:
        first = next((p for p in policies if p["id"] == "hz-living-first-2024" and p["source_url"] == policy["source_url"] and p["published_on"] == policy["published_on"]), None)
        note = first["amount_note"] if first else policy["amount_note"]
        summary["standard_note"] = note.split("本卡核对首笔")[0] if policy["id"] == "hz-living-second-2024" else note
        # The snapshot explicitly mentions exceptions for older doctorate dates.
        # Do not infer their cutoff or calculate an unconditional doctorate amount.
        match = re.search(re.escape(degree) + r"\s*(\d+(?:\.\d+)?)\s*万元", note) if degree in {"本科", "硕士"} else None
        if match and "50%" in policy["amount_label"]:
            total = Decimal(match[1]) * 10000
            amount = total / 2
            summary.update(label=f"本笔参考 {amount:,.0f} 元", reference_yuan=int(amount),
                           basis=f"收录资料中{degree}总标准 {total:,.0f} 元 × 50%。首笔与第二笔属于同一补贴，不重复累计总额。")
        elif degree == "博士":
            summary["basis"] = "博士标准存在毕业时间例外，需按原文核定；此处不自动计算本笔金额。"
    elif policy["id"] == "hz-rent-first-2026" and "每笔 50%" in policy["amount_note"]:
        match = re.fullmatch(r"每户每年\s*(\d+(?:\.\d+)?)\s*万元", policy["amount_label"])
        if match:
            annual = Decimal(match[1]) * 10000
            amount = annual / 2
            summary.update(label=f"首笔参考 {amount:,.0f} 元 / 户", reference_yuan=int(amount),
                           basis=f"收录答复的每户每年 {annual:,.0f} 元 × 每笔 50%。后续笔次、续领与延长保障需另行核验。")
    return summary


def display_for(policy, profile, result, policies):
    grad = date.fromisoformat(profile["graduation_date"]) if profile.get("graduation_date") else None
    app = date.fromisoformat(profile["application_date"])
    has_24_month_limit = any(r["field"] == "within_24_months" and r["op"] == "eq" and r["value"] is True for r in policy["rules"])
    needs_graduation = has_24_month_limit or any(r["field"] == "graduated" and r["op"] == "eq" and r["value"] is True for r in policy["rules"])
    phase = "not_applicable" if not needs_graduation else "unknown" if not grad else "not_started" if grad > app else "expired" if has_24_month_limit and app > add_months(grad, 24) else "open"
    scope_ok = all(c["status"] == "pass" for c in result["checks"] if c["kind"] == "scope")
    from policy_time import available
    planning = phase == "not_started" and scope_ok and available(policy, profile["application_date"])
    expired = phase == "expired" and scope_ok and available(policy, profile["application_date"])
    timing_fields = {"graduated", "within_24_months", "insurance_months", "insurance_start_within_12", "six_months_within_18", "twelve_months_within_24", "first_payment_ready"}
    other_blockers = [r for r in result["checks"] if planning and r["status"] == "fail" and r["field"] not in timing_fields]
    rows = []
    for check in result["checks"]:
        row = {"field": check["field"], "status": check["status"], "label": check["label"], "note": ""}
        if phase == "not_started" and check["field"] in {"graduated", "within_24_months"}:
            row.update(status="not_started", label="尚未毕业" if check["field"] == "graduated" else "毕业后申请期尚未开始",
                       note=f"所填预计毕业日为 {grad.isoformat()}，不是已错过申请期限。")
        elif phase == "expired" and check["field"] == "within_24_months":
            row.update(label="已超过所列毕业后两年期限", note=f"按所填日期计算，边界为 {add_months(grad, 24).isoformat()}；特殊情形需官方核验。")
        rows.append(row)
    blockers = [{**r, "actual_label": field_value(r["field"], profile.get(r["field"], r["actual"]))} for r in result["checks"] if r["status"] in {"fail", "unknown"}]
    return {"phase": phase, "planning": planning,
            "label": ("尚未到申请阶段 · 另有条件需核对" if other_blockers else "尚未到申请阶段") if planning else "已超过所列申请期" if expired else None,
            "reason": ("尚未毕业，当前未进入毕业后申领阶段；这不代表已经超期。毕业后须重新核对全部条件。" + (f"另有 {len(other_blockers)} 项非时间条件当前不满足，不能仅等待毕业。" if other_blockers else "")) if planning else f"按所填日期，毕业后两年边界为 {add_months(grad, 24).isoformat()}，早于参考日期 {app.isoformat()}。特殊情形及现行规则请向受理系统核验。" if expired else result["reason"],
            "other_blockers": other_blockers,
            "checks": rows, "blockers": blockers,
            "preparation": ["确认实际毕业日期与学历记录。", "毕业后核对在杭就业、单位资格和有效连续参保记录。", "达到所列条件后，在申请期内重新核验并向受理系统确认。"] if planning else [],
            "benefit": benefit_for(policy, profile, policies),
            "source": {k: policy.get(k) for k in ("published_on", "checked_on", "source_org", "legal_status")}}
