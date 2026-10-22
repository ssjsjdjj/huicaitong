"""Score saved predictions against held-out synthetic labels. Never invent model runs."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from training.rewards import score_completion
from llm import parse_completion


LABELS = ("eligible", "ineligible", "insufficient")


def evaluate_predictions(gold, rows):
    """Missing/invalid predictions count as errors; preserve per-class failures."""
    predictions = {r["case_id"]: r["completion"] for r in rows}
    if len(predictions) != len(rows):
        raise ValueError("预测 case_id 重复")
    if len({r["case_id"] for r in gold}) != len(gold):
        raise ValueError("参考 case_id 重复")
    if set(predictions)-{r["case_id"] for r in gold}:
        raise ValueError("预测中存在未知 case_id")
    if not gold:
        raise ValueError("评测集为空")
    matrix = {label: {p: 0 for p in (*LABELS, "invalid")} for label in LABELS}
    details, scores = [], []
    per_policy = {}
    exact = 0
    for row in gold:
        target = json.loads(row["ground_truth"]) if isinstance(row["ground_truth"], str) else row["ground_truth"]
        text = predictions.get(row["case_id"], "")
        score = score_completion(text, target)
        scores.append(score)
        prediction = parse_completion(text) if score["valid"] else {}
        label = prediction.get("conclusion", "invalid")
        matrix[target["conclusion"]][label] += 1
        errors = []
        if not score["valid"]:
            errors.append("invalid_output")
        elif not score["correct"]:
            errors.append("conclusion")
        if score["valid"]:
            for field, metric in (("evidence_ids", "evidence_f1"), ("missing_fields", "missing_f1"), ("materials", "materials_f1")):
                if score[metric] != 1:
                    errors.append(field)
        exact += score["valid"] and not errors
        details.append({"case_id": row["case_id"], "policy_id": target["policy_id"], "expected": target["conclusion"], "predicted": label, "errors": errors, **score})
        policy = per_policy.setdefault(target["policy_id"], {"cases": 0, "correct": 0, "valid": 0})
        policy["cases"] += 1
        policy["correct"] += score["correct"]
        policy["valid"] += score["valid"]
    per_class = {}
    for label in LABELS:
        support = sum(matrix[label].values())
        predicted = sum(matrix[g][label] for g in LABELS)
        tp = matrix[label][label]
        per_class[label] = {"support": support, "predicted": predicted, "precision": tp/predicted if predicted else 0.0, "recall": tp/support if support else None, "f1": 2*tp/(support+predicted) if support+predicted else None}
    n = len(scores)
    observed = [v for v in per_class.values() if v["support"]]
    result = {"cases": n, "predictions": len(rows), "missing_predictions": n-len(rows), "conclusion_accuracy": sum(s["correct"] for s in scores)/n, "valid_output_rate": sum(s["valid"] for s in scores)/n, "mean_evidence_f1": sum(s["evidence_f1"] for s in scores)/n, "mean_missing_f1": sum(s["missing_f1"] for s in scores)/n, "mean_materials_f1": sum(s["materials_f1"] for s in scores)/n, "mean_reward": sum(s["total"] for s in scores)/n,
        "structured_exact_match": exact/n, "macro_f1_observed_classes": sum(v["f1"] for v in observed)/len(observed), "balanced_accuracy": sum(v["recall"] for v in observed)/len(observed), "per_class": per_class, "confusion_matrix": matrix, "per_policy": per_policy, "error_counts": dict(Counter(e for d in details for e in d["errors"])), "label_source": "synthetic weak supervision unless separately replaced and reviewed", "warning": "只评价提供的预测；不证明训练来源，不构成人工政策准确率。结构完全一致不评价解释文字。"}
    return result, details


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--gold",required=True)
    parser.add_argument("--predictions",required=True,help="JSONL: case_id, completion")
    parser.add_argument("--output",default="training-runs/evaluation.json")
    args=parser.parse_args()
    gold=[json.loads(x) for x in Path(args.gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    rows=[json.loads(x) for x in Path(args.predictions).read_text(encoding="utf-8").splitlines() if x.strip()]
    try:
        result, details = evaluate_predictions(gold,rows)
    except ValueError as e:
        raise SystemExit(str(e)) from None
    result["input_sha256"]={"gold":hashlib.sha256(Path(args.gold).read_bytes()).hexdigest(),"predictions":hashlib.sha256(Path(args.predictions).read_bytes()).hexdigest()}
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    path.with_suffix(".details.jsonl").write_text("\n".join(json.dumps(d,ensure_ascii=False) for d in details)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
