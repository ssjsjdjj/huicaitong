"""Check exported human annotations; optionally score actual model predictions."""
import argparse
import json
from pathlib import Path
from review import reviewed_tasks
from store import DATA
from training.evaluate import evaluate_predictions


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--annotations",required=True)
    parser.add_argument("--predictions")
    parser.add_argument("--export-tasks",help="export reviewed prompts for training.predict, not for training by default")
    parser.add_argument("--output",default="training-runs/manual-evaluation.json")
    args=parser.parse_args()
    payload=json.loads(Path(args.annotations).read_text(encoding="utf-8-sig"))
    policies=json.loads(DATA.read_text(encoding="utf-8"))["policies"]
    rows=payload.get("cases") if isinstance(payload,dict) else payload
    try:
        tasks=reviewed_tasks(rows,policies)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    if args.export_tasks:
        from llm import messages_for
        catalogue={p["id"]:p for p in policies}
        path=Path(args.export_tasks)
        path.parent.mkdir(parents=True,exist_ok=True)
        exported=[{**row,"prompt":messages_for(catalogue[row["policy_id"]],row["profile"])} for row in tasks]
        path.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in exported)+"\n",encoding="utf-8")
    result={"reviewed_cases":len(tasks),"prediction_evaluation_executed":False,"notice":"仅验证复核者填写的记录结构和政策快照；程序不能代替判断标注质量。"}
    if args.predictions:
        predictions=[json.loads(x) for x in Path(args.predictions).read_text(encoding="utf-8").splitlines() if x.strip()]
        result,details=evaluate_predictions(tasks,predictions)
        result.update(label_source="reviewer_declared_annotation",prediction_evaluation_executed=True,warning="复核者自行声明的人工标注；请另行检查标注质量和独立性，不与旧弱标签评测混报。")
        target=Path(args.output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.with_suffix(".details.jsonl").write_text("\n".join(json.dumps(d,ensure_ascii=False) for d in details)+"\n",encoding="utf-8")
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
