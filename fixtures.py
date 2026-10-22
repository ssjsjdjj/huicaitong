"""Synthetic acceptance scenarios, not human-reviewed policy benchmark data."""
from copy import deepcopy

BASE = {
    "city":"杭州", "application_date":"2026-10-21", "degree":"master", "study_mode":"fulltime", "school_region":"mainland", "nationality":"cn", "graduation_date":"2025-06-30", "insurance_start_date":"2025-07-01", "insurance_months":15,
    "employed_hangzhou":True, "employer_qualified":True, "insurance_current":True, "insurance_without_backpay":True, "prior_other_degree_subsidy":False, "degree_while_employed":False, "first_installment_received":False, "family_has_home":False, "other_housing_benefit":False, "rent_first_received":False,
}
FIRST = "hz-living-first-2024"
SECOND = "hz-living-second-2024"
RENT = "hz-rent-first-2026"


def case(name, changes, expected):
    return {"id":name, "profile":{**deepcopy(BASE),**changes}, "expected":dict(zip((FIRST, SECOND, RENT),expected)), "source_type":"synthetic_fixture", "human_reviewed":False}


CASES = [
    case("已就业硕士，尚未领首笔", {}, ["eligible","ineligible","eligible"]),
    case("已领取首笔，核对第二笔", {"first_installment_received":True}, ["ineligible","eligible","eligible"]),
    case("申请家庭有房", {"family_has_home":True}, ["eligible","ineligible","ineligible"]),
    case("住房信息缺失", {"family_has_home":None}, ["eligible","ineligible","insufficient"]),
    case("毕业已超两年", {"graduation_date":"2022-06-30", "insurance_start_date":"2022-07-01", "insurance_months":51}, ["ineligible","ineligible","ineligible"]),
    case("境外学历须人工核验", {"school_region":"overseas"}, ["insufficient","insufficient","insufficient"]),
    case("尚在读，未到毕业时间", {"graduation_date":"2027-06-30", "insurance_start_date":None, "insurance_months":0}, ["ineligible","ineligible","ineligible"]),
    case("连续参保起算过晚", {"insurance_start_date":"2026-08-01", "insurance_months":2}, ["ineligible","ineligible","ineligible"]),
    case("单位资格未确认", {"employer_qualified":None}, ["insufficient","ineligible","eligible"]),
    case("毕业未满半年，社保信息不足", {"graduation_date":"2026-06-30", "insurance_start_date":None, "insurance_months":None, "first_installment_received":None}, ["insufficient","insufficient","insufficient"]),
]


def evaluate(policies):
    from core import assess_all
    rows = []
    for c in CASES:
        actual = {r["policy_id"]: r["conclusion"] for r in assess_all(policies,c["profile"])["results"]}
        details = [{"policy_id":pid,"expected":target,"actual":actual.get(pid),"passed":actual.get(pid)==target} for pid,target in c["expected"].items()]
        rows.append({"name":c["id"],"passed":all(d["passed"] for d in details),"details":details})
    return {"mode":"rule_baseline", "cases":rows, "passed":sum(r["passed"] for r in rows), "total":len(rows), "checks":sum(len(r["details"]) for r in rows), "notice":"仅为合成场景的规则验收结果，不代表真实政策准确率，也不是 GRPO 模型结果。", "model_trained":False}
