"""Optional local model server for the trained LoRA adapter. One generation at a time."""
import argparse
import json
import time
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from store import ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--model",default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--adapter",default=str(ROOT/"checkpoints"/"grpo"))
    parser.add_argument("--port",type=int,default=8766)
    parser.add_argument("--name",default="huicaitong-local")
    parser.add_argument("--parent-pid",type=int,default=0)
    args=parser.parse_args()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM,AutoTokenizer
    if not torch.cuda.is_available():
        raise SystemExit("当前训练环境没有可用 CUDA")
    tokenizer=AutoTokenizer.from_pretrained(args.model)
    dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model=AutoModelForCausalLM.from_pretrained(args.model,torch_dtype=dtype).to("cuda")
    if args.adapter:
        if not (Path(args.adapter)/"adapter_config.json").exists():
            raise SystemExit("找不到已训练的 LoRA 目录，请先完成训练或指定 --adapter")
        model=PeftModel.from_pretrained(model,args.adapter)
    model.eval()
    lock=threading.Lock()

    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self,*unused):
            pass

        def send(self,data,status=200):
            body=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path=="/v1/models":
                self.send({"data":[{"id":args.name,"object":"model"}]})
            else:
                self.send({"error":"not found"},404)

        def do_POST(self):
            if self.path!="/v1/chat/completions":
                self.send({"error":"not found"},404)
                return
            host=self.headers.get("Host","").split(":")[0]
            if host not in {"localhost","127.0.0.1"} or self.headers.get("Origin"):
                self.send({"error":"local backend calls only"},403)
                return
            try:
                size=int(self.headers.get("Content-Length","0"))
                if not 0<size<=128_000:
                    raise ValueError("request too large")
                body=json.loads(self.rfile.read(size))
                messages=body["messages"]
                if not isinstance(messages,list) or not all(isinstance(m,dict) and m.get("role") in {"system","user","assistant"} and isinstance(m.get("content"),str) for m in messages):
                    raise ValueError("invalid messages")
                with lock,torch.inference_mode():
                    inputs=tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_tensors="pt").to("cuda")
                    if inputs.shape[1]>4096:
                        raise ValueError("input exceeds local server token limit")
                    count=max(32,min(int(body.get("max_tokens",384)),768))
                    outputs=model.generate(inputs,attention_mask=torch.ones_like(inputs),max_new_tokens=count,do_sample=False,pad_token_id=tokenizer.eos_token_id)
                    text=tokenizer.decode(outputs[0,inputs.shape[1]:],skip_special_tokens=True)
                    result={"model":args.name,"choices":[{"message":{"role":"assistant","content":text}}],"usage":{"prompt_tokens":inputs.shape[1],"completion_tokens":outputs.shape[1]-inputs.shape[1]}}
                self.send(result)
            except (ValueError,KeyError,TypeError):
                self.send({"error":"invalid request or token limit exceeded"},400)
            except Exception:
                self.send({"error":"local model generation failed"},500)

    server=ThreadingHTTPServer(("127.0.0.1",args.port),ModelHandler)
    if args.parent_pid:
        def watch_parent():
            import psutil
            try:
                parent=psutil.Process(args.parent_pid)
                while parent.is_running():
                    time.sleep(2)
            except psutil.NoSuchProcess:
                pass
            server.shutdown()
        threading.Thread(target=watch_parent,daemon=True).start()
    print(f"Local model ready: http://127.0.0.1:{args.port}/v1; name={args.name}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=="__main__":
    main()
