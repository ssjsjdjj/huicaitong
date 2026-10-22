"""Create reproducible SYNTHETIC weak-supervision data, not expert annotations."""
import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from core import RAW_FIELDS, assess_policy, validate_profile
from fixtures import BASE
from llm import messages_for
from guidance import reference_fields
from store import ROOT, DATA


def reference_answer(policy, profile):
    result = assess_policy(policy,validate_profile(profile))
    gold=reference_fields(policy,result)
    gold["allowed_evidence_ids"]=[c["id"] for c in policy["clauses"]]
    gold["allowed_missing_fields"]=sorted(RAW_FIELDS)
    gold["allowed_materials"]=[m["id"] for m in policy["materials"]]
    return gold


def model_answer(gold):
    return {k:v for k,v in gold.items() if not k.startswith("allowed_")}


def build(output, count=240, seed=42):
    if count < 30:
        raise ValueError("至少生成 30 个人物条件组，以覆盖开发场景")
    rng=random.Random(seed)
    policies=[p for p in json.loads(DATA.read_text(encoding="utf-8"))["policies"] if p["status"]=="included"]
    buckets={s:[] for s in ("train","validation","test")}
    seen=set()
    i=0
    while len(seen)<count:
        p=dict(BASE)
        p["degree"]=rng.choice(["bachelor","master","phd","college"])
        p["graduation_date"]=rng.choice(["2025-06-30","2024-06-30","2026-06-30"])
        if p["graduation_date"].startswith("2026"):
            p["insurance_start_date"],p["insurance_months"]="2026-07-01",rng.choice([0,1,2,3,None])
        else:
            p["insurance_start_date"],p["insurance_months"]="2025-07-01",rng.choice([0,5,6,11,12,15,None])
        for field in ["family_has_home","other_housing_benefit","employer_qualified","insurance_current","first_installment_received","rent_first_received","prior_other_degree_subsidy","degree_while_employed"]:
            p[field]=rng.choices([BASE[field],not BASE[field],None],[8,1,1])[0]
        # Deliberately include clean positive and missing-information groups;
        # purely random Boolean perturbations overwhelmingly produce negatives.
        if i%4 in (0,1):
            p=dict(BASE)
            p["degree"]=rng.choice(["bachelor","master","phd"])
            p["graduation_date"]=rng.choice(["2025-03-31","2025-04-30","2025-05-31","2025-06-30","2025-07-31"])
            p["insurance_start_date"]=rng.choice(["2025-08-01","2025-09-01","2025-10-01"])
            p["insurance_months"]=12
            p["first_installment_received"]=rng.choice([True,False])
            if i%4==1:
                p["insurance_months"]=None
                p["first_installment_received"]=None
                p["family_has_home"]=None
        if i%5==0 and i%4 not in (0,1):
            p[rng.choice(["graduation_date","insurance_start_date","study_mode","school_region"])]=None
        digest=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]
        i+=1
        if digest in seen:
            continue
        validate_profile(p)
        seen.add(digest)
        # Source-family isolation for the held-out test. Validation only isolates
        # applicant groups, NOT source documents; this is stated in the manifest.
        dev_split="validation" if int(digest[:4],16)%5==0 else "train"
        for policy in policies:
            split="test" if policy["family"]=="hz-rent" else dev_split
            gold=reference_answer(policy,p)
            row={"case_id":digest+"-"+policy["id"],"scenario_group":digest,"policy_family":policy["family"],"source_url":policy["source_url"],"source_type":"synthetic_rule_weak_label","human_reviewed":False,"prompt":messages_for(policy,p),"ground_truth":json.dumps(gold,ensure_ascii=False)}
            buckets[split].append(row)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    manifest={"seed":seed,"scenario_groups":count,"policy_snapshot_sha256":hashlib.sha256(DATA.read_bytes()).hexdigest(),"label_source":"synthetic_rule_weak_label","human_reviewed":False,"test_holdout_family":"hz-rent","validation_isolation":"applicant scenario groups only; living policy sources overlap with training","test_isolation":"rental source family excluded from training; input policy text is available at inference","warning":"开发用弱监督数据，不是人工标注评测集，单一测试文件族不足以证明广泛政策泛化。正式实验需人工复核并扩充独立文件。","counts":{},"label_counts":{}}
    for split,rows in buckets.items():
        (output/f"{split}_grpo.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n",encoding="utf-8")
        sft=[]
        for row in rows:
            gold=json.loads(row["ground_truth"])
            sft.append({"case_id":row["case_id"],"messages":row["prompt"]+[{"role":"assistant","content":json.dumps(model_answer(gold),ensure_ascii=False)}],"source_type":row["source_type"],"human_reviewed":False})
        (output/f"{split}_sft.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in sft)+"\n",encoding="utf-8")
        manifest["counts"][split]=len(rows)
        manifest["label_counts"][split]=dict(Counter(json.loads(r["ground_truth"])["conclusion"] for r in rows))
    groups={label:[r for r in buckets["train"] if json.loads(r["ground_truth"])["conclusion"]==label] for label in ("eligible","ineligible","insufficient")}
    minimum=min(map(len,groups.values()))
    balanced=[]
    for rows in groups.values():
        balanced.extend(rng.sample(rows,minimum))
    rng.shuffle(balanced)
    (output/"train_balanced_grpo.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in balanced)+"\n",encoding="utf-8")
    (output/"train_balanced_sft.jsonl").write_text("\n".join(json.dumps({"case_id":r["case_id"],"messages":r["prompt"]+[{"role":"assistant","content":json.dumps(model_answer(json.loads(r["ground_truth"])),ensure_ascii=False)}],"source_type":r["source_type"],"human_reviewed":False},ensure_ascii=False) for r in balanced)+"\n",encoding="utf-8")
    manifest["balanced_training"]={"strategy":"deterministic undersampling of training split only","total":len(balanced),"per_class":minimum,"warning":"负例下采样减少覆盖，仅为开发中的类别偏差修正；验证与测试不平衡抽样，也不改变标签。"}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=str(ROOT/"data"/"generated"))
    parser.add_argument("--count",type=int,default=240)
    parser.add_argument("--seed",type=int,default=42)
    args=parser.parse_args()
    result=build(args.output,args.count,args.seed)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
