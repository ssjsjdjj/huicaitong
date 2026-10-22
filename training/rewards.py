"""Verifiable structured reward, with correctness gating and citation precision."""
import json
from llm import parse_completion


def f1(predicted, expected):
    p, g = set(predicted), set(expected)
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    return 2 * len(p & g) / (len(p) + len(g))


def score_completion(text, ground_truth):
    gold = json.loads(ground_truth) if isinstance(ground_truth,str) else ground_truth
    try:
        pred = parse_completion(text)
    except (ValueError,TypeError):
        return {"total":0.0,"valid":False,"correct":False,"evidence_f1":0.0,"missing_f1":0.0,"materials_f1":0.0}
    keys = {"policy_id","conclusion","evidence_ids","missing_fields","materials","explanation"}
    valid = set(pred)==keys and pred.get("policy_id")==gold["policy_id"] and isinstance(pred.get("conclusion"),str) and pred.get("conclusion") in {"eligible","ineligible","insufficient"} and isinstance(pred.get("explanation"),str)
    for key in ("evidence_ids","missing_fields","materials"):
        values = pred.get(key)
        if not isinstance(values,list) or not all(isinstance(v,str) for v in values) or len(values)!=len(set(values)):
            valid = False
    if isinstance(pred.get("conclusion"),str) and pred["conclusion"] in {"eligible","ineligible"} and not pred.get("evidence_ids"):
        valid = False
    if isinstance(pred.get("explanation"),str) and len(pred["explanation"])>3000:
        valid = False
    if not valid:
        return {"total":0.0,"valid":False,"correct":False,"evidence_f1":0.0,"missing_f1":0.0,"materials_f1":0.0}
    for key in ("evidence_ids","missing_fields","materials"):
        allowed = gold.get("allowed_"+key, gold[key])
        if not set(pred[key]) <= set(allowed):
            return {"total":0.0,"valid":False,"correct":False,"evidence_f1":0.0,"missing_f1":0.0,"materials_f1":0.0}
    correct = pred["conclusion"] == gold["conclusion"]
    evidence = f1(pred["evidence_ids"],gold["evidence_ids"])
    missing = f1(pred["missing_fields"],gold["missing_fields"])
    materials = f1(pred["materials"],gold["materials"])
    # Incorrect conclusions cannot gain a high reward by copying all citations.
    total = .05 + (0.55 + .20*evidence + .10*missing + .10*materials if correct else 0)
    return {"total":round(total,6),"valid":True,"correct":correct,"evidence_f1":evidence,"missing_f1":missing,"materials_f1":materials}


def evidence_reward(completions, ground_truth, **kwargs):
    scores=[]
    for completion,gold in zip(completions,ground_truth):
        text = completion[-1].get("content","") if isinstance(completion,list) else completion
        scores.append(score_completion(text,gold)["total"])
    return scores
