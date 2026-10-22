"""Training-only augmentation: one-field edits, balanced per policy and label.

Development/test prompts and labels are never used to construct targets. Only
their scenario identifiers are read to prevent identical development profiles.
"""
import argparse
import copy
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from core import assess_policy, validate_profile
from guidance import reference_fields
from llm import messages_for
from store import DATA, ROOT
from training.build_dataset import model_answer, reference_answer


def digest(profile):
    return hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()[:16]


def explain(policy, profile, gold):
    result=assess_policy(policy,profile)
    checks=result["checks"]
    decisive=[c for c in checks if c["status"]==("fail" if gold["conclusion"]=="ineligible" else "unknown")]
    if not decisive:
        return gold["explanation"]
    parts=[c["label"]+"（"+("尚未确认" if c["status"]=="unknown" else "所填条件不满足")+"，依据 "+c["citation"]+"）" for c in decisive[:3]]
    return "；".join(parts)+"。"+gold["explanation"]


def build(output, per_class=64, seed=73):
    if per_class<1:
        raise ValueError("per_class 必须为正整数")
    folder=ROOT/"data"/"generated"
    train=[json.loads(x) for x in (folder/"train_grpo.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    validation_ids={json.loads(x)["scenario_group"] for x in (folder/"validation_grpo.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    policies={p["id"]:p for p in json.loads(DATA.read_text(encoding="utf-8"))["policies"] if p["status"]=="included" and p["family"]=="hz-living"}
    rng=random.Random(seed)
    pool={}
    rejected=0

    def add(policy,profile,kind,parent):
        nonlocal rejected
        try:
            profile=validate_profile(profile)
        except ValueError:
            return
        group=digest(profile)
        if group in validation_ids:
            rejected+=1
            return
        key=group+"-"+policy["id"]
        if key in pool:
            return
        gold=reference_answer(policy,profile)
        gold["explanation"]=explain(policy,profile,gold)
        pool[key]={"case_id":key,"scenario_group":group,"policy_family":policy["family"],"source_url":policy["source_url"],"source_type":"synthetic_rule_weak_label","human_reviewed":False,"augmentation":kind,"parent_case_id":parent,"prompt":messages_for(policy,profile),"ground_truth":json.dumps(gold,ensure_ascii=False)}

    edits={"degree":["college"],"employed_hangzhou":[False,None],"employer_qualified":[False,None],"insurance_current":[False,None],"insurance_without_backpay":[False,None],"prior_other_degree_subsidy":[True,None],"degree_while_employed":[True,None],"insurance_months":[0,1,5,None],"school_region":["overseas",None],"study_mode":["parttime",None],"first_installment_received":[True,False,None]}
    for row in train:
        policy=policies[row["case_id"].split("-",1)[1]]
        profile=json.loads(row["prompt"][1]["content"])["applicant"]
        add(policy,profile,"original_training",row["case_id"])
        if json.loads(row["ground_truth"])["conclusion"]!="eligible":
            continue
        for field,values in edits.items():
            for value in values:
                if profile.get(field)==value:
                    continue
                candidate={**profile,field:value}
                add(policy,candidate,"one_field:"+field,row["case_id"])
    selected=[]
    counts={}
    for policy_id in policies:
        for label in ("eligible","ineligible","insufficient"):
            rows=[r for r in pool.values() if json.loads(r["ground_truth"])["policy_id"]==policy_id and json.loads(r["ground_truth"])["conclusion"]==label]
            if not rows:
                raise ValueError("训练样本类别为空")
            counts[policy_id+":"+label]=len(rows)
            # Retain hard negatives while making class priors equal within each
            # policy. Duplicates introduced by oversampling get explicit IDs.
            rng.shuffle(rows)
            for i in range(per_class):
                row=copy.deepcopy(rows[i%len(rows)])
                row["original_case_id"]=row["case_id"]
                row["case_id"]+="-cf-"+str(i)
                selected.append(row)
    rng.shuffle(selected)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    grpo=output/"train_counterfactual_grpo.jsonl"
    grpo.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in selected)+"\n",encoding="utf-8")
    sft=output/"train_counterfactual_sft.jsonl"
    sft.write_text("\n".join(json.dumps({"case_id":r["case_id"],"messages":r["prompt"]+[{"role":"assistant","content":json.dumps(model_answer(json.loads(r["ground_truth"])),ensure_ascii=False)}],"source_type":r["source_type"],"human_reviewed":False},ensure_ascii=False) for r in selected)+"\n",encoding="utf-8")
    manifest={"seed":seed,"train_only":True,"source_family":"hz-living","counts":len(selected),"unique_tasks":len({r["original_case_id"] for r in selected}),"per_policy_per_class":per_class,"candidate_pool_counts":counts,"excluded_development_duplicates":rejected,"development_profile_overlap":len({r["scenario_group"] for r in selected}&validation_ids),"augmentation_counts":dict(Counter(r["augmentation"] for r in selected)),"source_train_sha256":hashlib.sha256((folder/"train_grpo.jsonl").read_bytes()).hexdigest(),"source_policy_sha256":hashlib.sha256(DATA.read_bytes()).hexdigest(),"files_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (sft,grpo)},"warning":"训练集内单字段编辑与按政策类别平衡抽样；少数类有重复。全部标签仍由规则生成，不是人工数据，也不证明跨政策泛化。验证只读取人物标识用于排除重复，未读取测试集。"}
    (output/"counterfactual_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=str(ROOT/"data"/"generated"))
    parser.add_argument("--per-class",type=int,default=64)
    args=parser.parse_args()
    print(json.dumps(build(args.output,args.per_class),ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
