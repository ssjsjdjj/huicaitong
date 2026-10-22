"""Freeze a default adapter using development metrics, before held-out inference."""
import argparse
import hashlib
import json
from datetime import datetime, timezone

from store import ROOT


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",help="freeze selection without modifying any adapter weights")
    args=parser.parse_args()
    destination=ROOT/"checkpoints"/"selection.json"
    if destination.exists():
        raise SystemExit("模型选择记录已冻结。保留此记录，不根据后续检查重新选择。")
    candidates=[]
    for phase,folder,filename in (
        ("grpo","grpo-balanced","grpo-development-full-evaluation.json"),
        ("sft","sft-counterfactual","sft-counterfactual-development-evaluation.json"),
        ("grpo","grpo-counterfactual","grpo-counterfactual-development-evaluation.json"),
    ):
        path=ROOT/"training-runs"/filename
        report=json.loads(path.read_text(encoding="utf-8"))
        if report["cases"]!=92 or report["missing_predictions"]:
            raise SystemExit("需要完整且未缺失的 92 条开发集预测（无效输出仍计为失败）")
        weights=ROOT/"checkpoints"/folder/"adapter_model.safetensors"
        metadata=ROOT/"training-runs"/(filename.replace("-evaluation.json",".metadata.json"))
        meta=json.loads(metadata.read_text(encoding="utf-8"))
        if meta.get("adapter_sha256")!=sha(weights):
            raise SystemExit("候选权重与预测元数据散列不一致："+folder)
        candidates.append({"phase":phase,"folder":folder,"report":filename,"report_sha256":sha(path),"adapter_sha256":sha(weights),"structured_exact_match":report["structured_exact_match"],"conclusion_accuracy":report["conclusion_accuracy"],"gold_sha256":report["input_sha256"]["gold"]})
    if len({c["gold_sha256"] for c in candidates})!=1:
        raise SystemExit("候选模型的开发集参考文件不一致")
    selected=max(candidates,key=lambda c:(c["structured_exact_match"],c["conclusion_accuracy"],c["phase"]=="sft"))
    is_v2=selected["folder"].endswith("counterfactual")
    adapter=selected["folder"] if is_v2 else selected["phase"]
    if sha(ROOT/"checkpoints"/adapter/"adapter_model.safetensors")!=selected["adapter_sha256"]:
        raise SystemExit("启动目录权重与候选记录不一致")
    record={"version":"0.2.0","frozen_at":datetime.now(timezone.utc).isoformat(),"adapter":adapter,"experiment_adapter":selected["folder"],"adapter_sha256":selected["adapter_sha256"],"model_id":"huicaitong-"+selected["phase"]+("-counterfactual-v2" if is_v2 else "-balanced-v1"),"criterion":"full 92 development structured exact match; then conclusion accuracy; tie favors SFT","selected_metrics":selected,"candidates":candidates,"holdout_subset_sha256":sha(ROOT/"data"/"generated"/"test_v2_unseen_grpo.jsonl"),"warning":"开发集参与调参，选择不是独立测试结果。默认模型在后续48条租房检查前冻结。"}
    if args.apply:
        if (ROOT/"training-runs"/"selected-v2-heldout.jsonl").exists():
            raise SystemExit("发现后续检查结果，不能再按本流程改选模型")
        destination.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(record,ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
