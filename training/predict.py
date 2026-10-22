"""Save genuine local model predictions for reproducible offline scoring."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from store import ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",default=str(ROOT/"data"/"generated"/"test_grpo.jsonl"))
    parser.add_argument("--model",default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--adapter",default=str(ROOT/"checkpoints"/"grpo"))
    parser.add_argument("--limit",type=int,default=0,help="0 = entire set; positive limits are smoke tests, not full benchmark")
    parser.add_argument("--output",default=str(ROOT/"training-runs"/"predictions.jsonl"))
    parser.add_argument("--evidence-mode",choices=["full_document","retrieval"],default="full_document",help="default preserves historical fixed-document prompts")
    args=parser.parse_args()
    rows=[json.loads(x) for x in Path(args.data).read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.limit<0:
        raise SystemExit("limit 必须为 0 或正整数")
    if args.limit:
        rows=rows[:args.limit]
    if args.evidence_mode=="retrieval":
        from store import DATA
        from rag import evidence_context
        from llm import messages_for
        catalogue={p["id"]:p for p in json.loads(DATA.read_text(encoding="utf-8"))["policies"]}
        for row in rows:
            context=json.loads(row["prompt"][1]["content"])
            policy=catalogue[context["policy_id"]]
            bundle=evidence_context(policy,context["applicant"],context.get("question"))
            row["prompt"]=messages_for(policy,context["applicant"],bundle)
            row["retrieval_trace"]=bundle["trace"]
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from peft import PeftModel
    if not torch.cuda.is_available():
        raise SystemExit("没有可用 CUDA")
    tokenizer=AutoTokenizer.from_pretrained(args.model)
    dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model=AutoModelForCausalLM.from_pretrained(args.model,torch_dtype=dtype).to("cuda")
    if args.adapter:
        model=PeftModel.from_pretrained(model,args.adapter)
    model.eval()
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.with_suffix(".gold.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n",encoding="utf-8")
    with output.open("w",encoding="utf-8") as handle,torch.inference_mode():
        for i,row in enumerate(rows,1):
            try:
                inputs=tokenizer.apply_chat_template(row["prompt"],tokenize=True,add_generation_prompt=True,return_tensors="pt").to("cuda")
                if inputs.shape[1]>4096:
                    raise ValueError("input exceeds token budget")
                answer=model.generate(inputs,attention_mask=torch.ones_like(inputs),max_new_tokens=512,do_sample=False,pad_token_id=tokenizer.eos_token_id)
                text=tokenizer.decode(answer[0,inputs.shape[1]:],skip_special_tokens=True)
                result={"case_id":row["case_id"],"completion":text,"error":None}
            except Exception as e:
                result={"case_id":row["case_id"],"completion":"","error":type(e).__name__}
            handle.write(json.dumps(result,ensure_ascii=False)+"\n")
            handle.flush()
            print(f"Predicted {i}/{len(rows)}",flush=True)
    metadata={"model":args.model,"adapter":args.adapter,"cases":len(rows),"limited_smoke_test":bool(args.limit),"full_source_dataset":str(Path(args.data).resolve()),"predictions_path":str(output),"gold_path":str(output.with_suffix('.gold.jsonl')),"finished_at":datetime.now(timezone.utc).isoformat(),"generation":{"max_new_tokens":512,"do_sample":False},"source_dataset_sha256":hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),"predictions_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),"torch":torch.__version__}
    metadata["evidence_mode"]=args.evidence_mode
    adapter_file=Path(args.adapter)/"adapter_model.safetensors"
    if args.adapter and adapter_file.exists():
        metadata["adapter_sha256"]=hashlib.sha256(adapter_file.read_bytes()).hexdigest()
    output.with_suffix(".metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
