"""Download Qwen's official ModelScope snapshot and verify every file's SHA256."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
from store import ROOT


def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as handle:
        while block:=handle.read(4*1024*1024):
            h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=str(ROOT/".model-cache"/"Qwen2.5-0.5B-Instruct"))
    args=parser.parse_args()
    import requests
    root=Path(args.output).resolve()
    root.mkdir(parents=True,exist_ok=True)
    repo="Qwen/Qwen2.5-0.5B-Instruct"
    api="https://modelscope.cn/api/v1/models/"+repo
    response=requests.get(api+"/repo/files",params={"Revision":"master","Recursive":"true"},timeout=30)
    response.raise_for_status()
    files={f["Path"]:f for f in response.json()["Data"]["Files"] if f["Type"]=="blob"}
    names=["config.json","generation_config.json","tokenizer_config.json","tokenizer.json","vocab.json","merges.txt","LICENSE","README.md","model.safetensors"]
    provenance={"repository":repo,"host":"modelscope.cn","file_revisions":{},"verified":False}
    for name in names:
        meta=files[name]
        expected=meta["Sha256"]
        target=root/name
        provenance["file_revisions"][name]={"revision":meta["Revision"],"sha256":expected}
        url=requests.Request("GET",api+"/repo",params={"Revision":meta["Revision"],"FilePath":name}).prepare().url
        if target.exists() and digest(target)==expected:
            print("Verified existing",name,flush=True)
            continue
        temp=root/(name+".download.tmp")
        if meta["Size"]<32*1024*1024:
            data=requests.get(url,timeout=90)
            data.raise_for_status()
            temp.write_bytes(data.content)
        else:
            total=meta["Size"]
            parts=[(i,start,min(start+32*1024*1024,total)-1) for i,start in enumerate(range(0,total,32*1024*1024))]
            def fetch(part):
                i,start,end=part
                part_path=root/f"part-{expected[:12]}-{i:03d}.bin"
                for attempt in range(3):
                    try:
                        with requests.get(url,headers={"Range":f"bytes={start}-{end}"},timeout=(20,90),stream=True) as r:
                            if r.status_code!=206 or r.headers.get("Content-Range")!=f"bytes {start}-{end}/{total}":
                                raise ValueError("Unexpected range response")
                            with part_path.open("wb") as handle:
                                for chunk in r.iter_content(1024*1024):
                                    handle.write(chunk)
                        if part_path.stat().st_size!=end-start+1:
                            raise ValueError("Incomplete model part")
                        return part_path
                    except Exception:
                        if attempt==2:
                            raise
            with ThreadPoolExecutor(max_workers=8) as pool:
                for n,job in enumerate(as_completed([pool.submit(fetch,p) for p in parts]),1):
                    job.result()
                    print("Weight parts",n,"/",len(parts),flush=True)
            with temp.open("wb") as handle:
                for i,_,_ in parts:
                    with (root/f"part-{expected[:12]}-{i:03d}.bin").open("rb") as src:
                        while chunk:=src.read(1024*1024):
                            handle.write(chunk)
        if digest(temp)!=expected:
            raise SystemExit("Hash verification failed: "+name)
        temp.replace(target)
        print("Verified",name,flush=True)
    provenance["verified"]=True
    (root/"download_provenance.json").write_text(json.dumps(provenance,indent=2),encoding="utf-8")
    print("Ready:",root,flush=True)


if __name__=="__main__":
    main()
