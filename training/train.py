"""Optional real SFT/GRPO entrypoint. Dry-run requires only Python stdlib."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from store import ROOT
from training.rewards import score_completion


def inspect_data(path, mode):
    rows=[json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        raise ValueError("训练文件为空")
    for row in rows:
        if mode=="sft":
            if not isinstance(row.get("messages"),list) or row["messages"][-1]["role"]!="assistant":
                raise ValueError("SFT 样本需要含 assistant 答案的 messages")
        else:
            if not isinstance(row.get("prompt"),list) or "ground_truth" not in row:
                raise ValueError("GRPO 样本需要 prompt 和 ground_truth")
            gold=json.loads(row["ground_truth"])
            prediction=json.dumps({k:v for k,v in gold.items() if not k.startswith("allowed_")})
            if score_completion(prediction,gold)["total"]!=1:
                raise ValueError("参考答案未通过奖励接口自检")
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["sft","grpo"])
    parser.add_argument("--config",default=str(ROOT/"training"/"config.json"))
    parser.add_argument("--data")
    parser.add_argument("--model",help="Optional local model directory or public model id")
    parser.add_argument("--output")
    parser.add_argument("--sft-adapter",default=str(ROOT/"checkpoints"/"sft"))
    parser.add_argument("--max-steps",type=int)
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.model:
        config["model"]=args.model
    data=Path(args.data) if args.data else ROOT/"data"/"generated"/f"train_balanced_{args.mode}.jsonl"
    if not data.exists():
        raise SystemExit("请先运行 python -m training.build_dataset")
    rows=inspect_data(data,args.mode)
    dependencies={name:bool(importlib.util.find_spec(name)) for name in ("torch","transformers","trl","peft","datasets","accelerate")}
    if args.max_steps is not None and args.max_steps<1:
        raise SystemExit("max-steps 必须为正整数")
    report={"mode":args.mode,"samples":len(rows),"model":config["model"],"dependencies":dependencies,"gpu_training_executed":False,"data_path":str(data),"data_sha256":hashlib.sha256(data.read_bytes()).hexdigest(),"config":config,"weak_labels_need_review":True}
    if args.mode=="grpo":
        parent=Path(args.sft_adapter)/"adapter_model.safetensors"
        report["sft_adapter"]=str(Path(args.sft_adapter).resolve())
        if parent.exists():
            report["sft_adapter_sha256"]=hashlib.sha256(parent.read_bytes()).hexdigest()
    if args.dry_run:
        print(json.dumps(report,ensure_ascii=True,indent=2))
        return
    if not all(dependencies.values()):
        raise SystemExit("缺少训练依赖，请在独立训练环境安装 requirements-training.txt。Web 原型无需安装。")
    if args.mode=="grpo" and not (Path(args.sft_adapter)/"adapter_config.json").exists():
        raise SystemExit("请先完成 SFT，再通过 --sft-adapter 指定其 LoRA 输出目录")
    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from trl import SFTConfig,SFTTrainer,GRPOConfig,GRPOTrainer
    from training.rewards import evidence_reward
    if not torch.cuda.is_available():
        raise SystemExit("当前环境没有可用 CUDA。请先配置训练环境，避免误用 CPU 长时间训练。")
    dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer=AutoTokenizer.from_pretrained(config["model"])
    if tokenizer.pad_token is None:
        tokenizer.pad_token=tokenizer.eos_token
    # Reject overlong data before loading GPU weights. Do not truncate policy
    # evidence while keeping a target that depends on the removed clauses.
    budget=config["max_length"] - (config["max_completion_length"] if args.mode=="grpo" else 0)
    lengths=[len(tokenizer.apply_chat_template(r["messages"] if args.mode=="sft" else r["prompt"],tokenize=True,add_generation_prompt=args.mode=="grpo")) for r in rows]
    if max(lengths)>budget:
        raise SystemExit(f"样本最大 {max(lengths)} tokens 超过预算 {budget}。请缩减相关证据并重新核对标签，或在显存测试后调整配置。未启动训练。")
    model=AutoModelForCausalLM.from_pretrained(config["model"],torch_dtype=dtype)
    model.config.use_cache=False
    adapter=LoraConfig(r=config["lora_r"],lora_alpha=config["lora_alpha"],lora_dropout=0.0,target_modules=["q_proj","k_proj","v_proj","o_proj"],task_type="CAUSAL_LM")
    output=Path(args.output) if args.output else ROOT/"checkpoints"/args.mode
    common=dict(output_dir=str(output),max_steps=args.max_steps or config["max_steps"],per_device_train_batch_size=config["per_device_train_batch_size"],gradient_accumulation_steps=config["gradient_accumulation_steps"],gradient_checkpointing=True,bf16=dtype==torch.bfloat16,fp16=dtype==torch.float16,logging_steps=1,save_strategy="no",report_to="none",seed=config["seed"],optim="adamw_torch",disable_tqdm=True)
    if args.mode=="sft":
        dataset=Dataset.from_list([{"prompt":r["messages"][:-1],"completion":[r["messages"][-1]]} for r in rows])
        trainer=SFTTrainer(model=model,args=SFTConfig(**common,learning_rate=1e-4,max_length=config["max_length"],completion_only_loss=True),processing_class=tokenizer,train_dataset=dataset,peft_config=adapter)
    else:
        model=PeftModel.from_pretrained(model,args.sft_adapter,is_trainable=True)
        dataset=Dataset.from_list(rows)
        trainer=GRPOTrainer(model=model,args=GRPOConfig(**common,learning_rate=5e-6,num_generations=config["num_generations"],max_completion_length=config["max_completion_length"],use_vllm=False,beta=0.0),processing_class=tokenizer,train_dataset=dataset,reward_funcs=evidence_reward)
    trainer.train()
    trainer.save_model(str(output))
    tokenizer.save_pretrained(str(output))
    log=trainer.state.log_history
    report.update(gpu_training_executed=True,steps_completed=trainer.state.global_step,smoke_run=trainer.state.global_step<=2,nonzero_gradient_steps=sum(float(r.get("grad_norm",0))>0 for r in log),reward_signal_steps=sum(float(r.get("reward_std",0))>0 for r in log),max_gpu_allocated_gb=round(torch.cuda.max_memory_allocated()/1024**3,3),training_log=log)
    (output/"run_summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Training completed:",output)


if __name__=="__main__":
    main()
