"""Isolated local document reader. JSON on stdin/stdout; no applicant logging."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent


def ocr_command():
    return [str(Path(os.environ.get("SystemRoot","C:/Windows"))/"System32/WindowsPowerShell/v1.0/powershell.exe"),"-NoProfile","-NonInteractive","-File",str(ROOT/"windows_ocr.ps1")]


def capabilities():
    import importlib.util
    result={"text":True,"pdf":bool(importlib.util.find_spec("pypdf")),"image":False,"ocr_language":None}
    if os.name=="nt":
        try:
            r=subprocess.run(ocr_command()+["-Capabilities"],capture_output=True,timeout=12,check=True)
            data=json.loads(r.stdout.decode("utf-8-sig"))
            result.update(image=bool(data.get("supported")),ocr_language=data.get("language"))
        except (OSError,ValueError,subprocess.SubprocessError):
            pass
    return result


def read_document(filename,data):
    suffix=Path(filename).suffix.lower()
    if suffix==".txt":
        try:
            text=data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text=data.decode("gb18030")
        return {"pages":[text],"method":"local_text"}
    if suffix==".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("文字 PDF 组件未安装，请按 README 配置材料处理环境；TXT 可直接使用。") from None
        if not data.startswith(b"%PDF-"):
            raise ValueError("文件内容不是 PDF")
        try:
            reader=PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("暂不处理加密 PDF")
            if not 1<=len(reader.pages)<=5:
                raise ValueError("每份 PDF 请控制在 1—5 页")
            pages=[p.extract_text() or "" for p in reader.pages]
        except ValueError:
            raise
        except Exception:
            raise ValueError("PDF 无法读取，请另存为文字 PDF 或上传清晰的 PNG/JPG。") from None
        if not any(p.strip() for p in pages):
            raise ValueError("此 PDF 未提取到文字。扫描件请先导出为 PNG/JPG 再做本机识别。")
        return {"pages":pages,"method":"local_pdf_text"}
    if suffix not in {".png",".jpg",".jpeg"}:
        raise ValueError("支持 TXT、文字 PDF、PNG 和 JPG")
    if os.name!="nt":
        raise ValueError("图片识别当前使用 Windows 本地中文 OCR；此设备可先使用 TXT 或文字 PDF。")
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
        raise ValueError("文件内容不是 PNG/JPG")
    with tempfile.TemporaryDirectory(prefix="huicaitong-material-") as tmp:
        path=Path(tmp)/("image"+suffix)
        path.write_bytes(data)
        try:
            r=subprocess.run(ocr_command()+["-InputPath",str(path)],capture_output=True,timeout=25,check=True)
            value=json.loads(r.stdout.decode("utf-8-sig"))
        except (OSError,ValueError,subprocess.SubprocessError):
            raise ValueError("本机图片识别不可用，请检查中文 OCR 组件；也可上传文字 PDF 或 TXT。") from None
    if value.get("error"):
        raise ValueError("本机未识别出可用文字，或图片尺寸超限；请上传清晰、边长不超过 4000 像素的图片。")
    return {"pages":[value["text"]],"method":"windows_local_ocr","language":value.get("language")}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--capabilities",action="store_true")
    args=parser.parse_args()
    if args.capabilities:
        value=capabilities()
    else:
        try:
            body=json.loads(input())
            data=base64.b64decode(body["content_base64"],validate=True)
            if not 0<len(data)<=2_000_000:
                raise ValueError("材料文件须在 1 字节至 2MB 之间")
            value=read_document(body["filename"],data)
            if sum(map(len,value["pages"]))>30000:
                raise ValueError("提取文字超过 30000 字，请分拆材料")
        except ValueError as error:
            value={"error":str(error)}
        except Exception:
            value={"error":"材料无法读取，请核对文件格式"}
    print(json.dumps(value,ensure_ascii=True))


if __name__=="__main__":
    main()
