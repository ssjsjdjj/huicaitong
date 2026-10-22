"""One-click local launch. Reuse this task's optional training environment if present."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent


def selected_checkpoint(root=ROOT):
    folder=root/"checkpoints"
    config=folder/"selection.json"
    if not config.exists():
        return folder/"grpo","huicaitong-grpo-initial"
    value=json.loads(config.read_text(encoding="utf-8"))
    adapter=(folder/value["adapter"]).resolve()
    name=value["model_id"]
    if not adapter.is_relative_to(folder.resolve()) or not isinstance(name,str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}",name):
        raise ValueError("选定模型配置的路径或名称无效")
    weights=adapter/"adapter_model.safetensors"
    if not weights.is_file() or hashlib.sha256(weights.read_bytes()).hexdigest()!=value["adapter_sha256"]:
        raise ValueError("选定模型权重与评测冻结记录不一致")
    return adapter,name


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--no-browser",action="store_true")
    args=parser.parse_args()
    from app import load_env
    load_env()
    work=ROOT.parent.parent/"work"
    model_python=work/"training-venv"/"Scripts"/"python.exe"
    model_dir=work/"models"/"Qwen2.5-0.5B-Instruct"
    if not model_python.exists():
        model_python=ROOT/".venv-training"/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    if not (model_dir/"download_provenance.json").exists():
        model_dir=ROOT/".model-cache"/"Qwen2.5-0.5B-Instruct"
    try:
        adapter,model_name=selected_checkpoint()
    except (ValueError,KeyError,TypeError,OSError) as error:
        adapter,model_name=None,"huicaitong-local"
        print("选定实验模型不可用，将启动规则版："+str(error),flush=True)
    env=os.environ.copy()
    process=None
    log=None
    if not env.get("HCT_LLM_BASE_URL","").strip() and model_python.exists() and (model_dir/"download_provenance.json").exists() and adapter and (adapter/"adapter_config.json").exists():
        port=None
        for candidate in range(8766,8776):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1",candidate))
                    port=candidate
                    break
                except OSError:
                    continue
        if port:
            (ROOT/"runtime").mkdir(exist_ok=True)
            log=(ROOT/"runtime"/"model-server.log").open("w",encoding="utf-8")
            model_env={**env,"HF_HOME":str(work/"model-cache"),"HF_HUB_OFFLINE":"1","HF_HUB_DISABLE_TELEMETRY":"1"}
            command=[str(model_python),"-m","training.serve","--model",str(model_dir),"--adapter",str(adapter),"--port",str(port),"--name",model_name,"--parent-pid",str(os.getpid())]
            process=subprocess.Popen(command,cwd=ROOT,env=model_env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            print("Starting optional local model...",flush=True)
            for _ in range(40):
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models",timeout=.5) as response:
                        model=json.load(response)
                    if model["data"][0]["id"]==model_name:
                        env.update(HCT_LLM_BASE_URL=f"http://127.0.0.1:{port}/v1",HCT_LLM_MODEL=model_name)
                        print("Local model ready. Initial experimental checkpoint, not policy approval.",flush=True)
                        break
                except Exception:
                    time.sleep(.5)
    app_command=[sys.executable,str(ROOT/"app.py")]
    if not args.no_browser:
        app_command.append("--open-browser")
    app=None
    exit_code=0
    try:
        app=subprocess.Popen(app_command,cwd=ROOT,env=env)
        exit_code=app.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for child in (app,process):
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        if log:
            log.close()
    return exit_code


if __name__=="__main__":
    raise SystemExit(main())
