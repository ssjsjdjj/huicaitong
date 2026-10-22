"""Preselect previously unpredicted rental examples by ID hash, not labels."""
import argparse
import hashlib
import json
from pathlib import Path
from store import ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--count",type=int,default=48)
    parser.add_argument("--output",default=str(ROOT/"data"/"generated"/"test_v2_unseen_grpo.jsonl"))
    args=parser.parse_args()
    output=Path(args.output)
    if output.exists():
        raise SystemExit("冻结样本文件已存在；使用已有版本，避免改选样本。")
    rows=[json.loads(x) for x in (ROOT/"data"/"generated"/"test_grpo.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    seen={json.loads(x)["case_id"] for x in (ROOT/"training-runs"/"grpo-heldout-smoke.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    candidates=[r for r in rows if r["case_id"] not in seen]
    if not 1<=args.count<=len(candidates):
        raise SystemExit("样本数量超出剩余范围")
    selected=sorted(candidates,key=lambda r:hashlib.sha256(("huicaitong-v2-freeze:"+r["case_id"]).encode()).hexdigest())[:args.count]
    output.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in selected)+"\n",encoding="utf-8")
    manifest={"strategy":"sha256('huicaitong-v2-freeze:'+case_id), first N; no label-based selection","cases":len(selected),"remaining_before_selection":len(candidates),"excluded_previously_predicted":len(seen),"case_ids":[r["case_id"] for r in selected],"dataset_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),"model_selection":"Select by structured exact match on all 92 development examples, then conclusion accuracy; tie favors SFT. Freeze model before any inference on this subset.","warning":"仅指此前未运行模型预测的租房样本子集，仍是同一程序生成的弱标签，不是新建人工基准。此前12条已被查看，不放入本子集。"}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in manifest.items() if k!="case_ids"},ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
