"""Candidate extraction from local material; every field needs user confirmation."""
import base64
from datetime import date
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from core import FIELD_LABELS, add_months
from store import ROOT

DEGREE_NAMES={"college":"大专","bachelor":"本科","master":"硕士","phd":"博士"}
DATE_PATTERN=r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"
MONTH_PATTERN=r"(\d{4})[-/.年](\d{1,2})月?"


def document_python():
    explicit=os.getenv("HCT_DOCUMENT_PYTHON","")
    if explicit:
        if not Path(explicit).is_file():
            raise ValueError("材料处理 Python 路径不存在")
        return explicit
    for path in (ROOT.parent.parent/"work/documents-venv/Scripts/python.exe",ROOT/".venv-documents"/("Scripts/python.exe" if os.name=="nt" else "bin/python")):
        if path.is_file():
            return str(path)
    return sys.executable


@lru_cache(maxsize=1)
def material_capabilities():
    try:
        r=subprocess.run([document_python(),str(ROOT/"document_worker.py"),"--capabilities"],capture_output=True,timeout=16,check=True)
        return json.loads(r.stdout.decode("utf-8-sig"))
    except (ValueError,OSError,subprocess.SubprocessError):
        return {"text":True,"pdf":False,"image":False,"ocr_language":None}


def parse_fields(pages, profile, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update(status="ready", required_context=[], ledger=[])
    lines=[{"page":page,"line":n,"quote":text.strip()} for page,text in enumerate(pages,1) for n,text in enumerate(text.splitlines(),1) if text.strip()]
    candidates,issues=[],[]
    found={}
    def propose(field,value,line,method,context=None):
        found.setdefault(field,[]).append({"field":field,"label":FIELD_LABELS[field],"value":value,"value_label":DEGREE_NAMES.get(value,value) if isinstance(value,str) else value,"evidence":line,"method":method,"context":context or {},"requires_confirmation":True})
    for line in lines:
        compact=re.sub(r"\s+","",line["quote"])
        m=re.search(r"毕业(?:日期|时间)[:：]?"+DATE_PATTERN,compact)
        if m:
            try:
                propose("graduation_date",date(*map(int,m.groups())).isoformat(),line,"explicit_label")
            except ValueError:
                issues.append("发现无效毕业日期，未提取")
        m=re.search(r"(?:学历|学位|学历层次)[:：]?(博士|硕士|本科|学士|大专|专科)",compact)
        if m:
            degree={"博士":"phd","硕士":"master","本科":"bachelor","学士":"bachelor","大专":"college","专科":"college"}[m[1]]
            propose("degree",degree,line,"explicit_label")
    for field,values in found.items():
        unique={json.dumps(v["value"],sort_keys=True):v for v in values}
        if len(unique)==1:
            candidates.extend(unique.values())
        else:
            issues.append(FIELD_LABELS[field]+"在同一材料中出现不同值，未自动选择")
    ranges=[]
    records={}
    conflict=False
    for line in lines:
        compact=re.sub(r"\s+","",line["quote"])
        m=re.search(r"记录范围[:：]?"+MONTH_PATTERN+r"(?:至|~|—|–)"+MONTH_PATTERN,compact)
        if m:
            try:
                ranges.append((date(int(m[1]),int(m[2]),1),date(int(m[3]),int(m[4]),1)))
            except ValueError:
                issues.append("记录范围无效")
        m=re.match(r"^"+MONTH_PATTERN+r"[:：|,，]?(正常(?:缴费)?|已缴|补缴|欠缴|未缴|停缴|未参保)(?:$|[|,，].*)",compact)
        if m:
            try:
                month=date(int(m[1]),int(m[2]),1)
            except ValueError:
                issues.append("发现无效缴费月份")
                continue
            status="normal" if m[3] in {"正常","正常缴费","已缴"} else "excluded"
            if month in records and records[month][0]!=status:
                conflict=True
            records[month]=(status,line,m[3])
    if records:
        grad=profile.get("graduation_date")
        app=date.fromisoformat(profile["application_date"])
        last=add_months(app.replace(day=1),-1)
        diagnostics["ledger"]=[{"month":m.strftime("%Y-%m"), "status":v[2], "state":v[0], "counted":False, "evidence":v[1]} for m,v in sorted(records.items())][-120:]
        diagnostics["ledger_truncated"]=len(records)>120
        diagnostics["calculated_through"]=last.strftime("%Y-%m")
        if not grad:
            diagnostics.update(status="needs_context", required_context=["graduation_date"])
            issues.append("先确认表单中的毕业日期，再重新读取参保材料以计算毕业后连续月数")
        elif conflict or len(set(ranges))!=1:
            issues.append("缴费状态有冲突或缺少唯一的记录范围，未推算连续月数")
        else:
            grad_month=date.fromisoformat(grad).replace(day=1)
            start,end=ranges[0]
            if grad_month>last or start>grad_month or end<last or end<start or (last.year-grad_month.year)*12+last.month-grad_month.month>120:
                issues.append("记录范围未完整覆盖毕业当月至参考日期前一个月，未推算连续月数")
            else:
                needed=[]
                cursor=grad_month
                while cursor<=last:
                    needed.append(cursor)
                    cursor=add_months(cursor,1)
                missing=[m.strftime("%Y-%m") for m in needed if m not in records]
                if missing:
                    issues.append("逐月记录缺行（"+"、".join(missing[:6])+"），不能把缺行直接当作未参保")
                else:
                    count=0
                    cursor=last
                    while cursor>=grad_month and records[cursor][0]=="normal":
                        count+=1
                        cursor=add_months(cursor,-1)
                    context={"application_date":profile["application_date"],"graduation_date":grad}
                    line=records[last][1]
                    propose_value={"field":"insurance_months","label":FIELD_LABELS["insurance_months"],"value":count,"value_label":str(count)+" 个月","method":"complete_month_ledger","context":context,"requires_confirmation":True,"evidence":line}
                    candidates.append(propose_value)
                    if count:
                        first=add_months(last,1-count)
                        candidates.append({"field":"insurance_start_date","label":FIELD_LABELS["insurance_start_date"],"value":first.isoformat(),"value_label":first.strftime("%Y-%m"),"method":"complete_month_ledger","context":context,"requires_confirmation":True,"evidence":records[first][1]})
                    diagnostics["continuous_months"]=count
                    diagnostics["continuous_start"]=add_months(last,1-count).strftime("%Y-%m") if count else None
                    for entry in diagnostics["ledger"]:
                        entry["counted"]=bool(count and diagnostics["continuous_start"]<=entry["month"]<=last.strftime("%Y-%m") and entry["state"]=="normal")
                    issues.append("按逐月记录计算至 "+last.strftime("%Y-%m")+"；补缴、未缴等中断连续计数，不计未完成月份。当前参保、单位资格等仍需另外确认")
    for c in candidates:
        c["current_value"]=profile.get(c["field"])
        c["conflict"]=profile.get(c["field"]) is not None and profile[c["field"]]!=c["value"]
    return candidates,issues


def extract_material(body, profile):
    filename=body.get("filename")
    encoded=body.get("content_base64")
    if not isinstance(filename,str) or len(filename)>160 or Path(filename).suffix.lower() not in {".txt",".pdf",".png",".jpg",".jpeg"}:
        raise ValueError("请上传 TXT、文字 PDF、PNG 或 JPG，文件名不超过 160 字")
    if not isinstance(encoded,str) or len(encoded)>2_670_000:
        raise ValueError("材料须为不超过 2MB 的文件")
    try:
        data=base64.b64decode(encoded,validate=True)
    except ValueError:
        raise ValueError("材料编码无效") from None
    if not 0<len(data)<=2_000_000:
        raise ValueError("材料须为不超过 2MB 的非空文件")
    if Path(filename).suffix.lower()==".txt":
        from document_worker import read_document
        extracted=read_document(filename,data)
    else:
        try:
            result=subprocess.run([document_python(),str(ROOT/"document_worker.py")],input=json.dumps({"filename":Path(filename).name,"content_base64":encoded}).encode(),capture_output=True,timeout=40,check=True)
            extracted=json.loads(result.stdout.decode("utf-8-sig"))
        except (OSError,ValueError,subprocess.SubprocessError):
            raise ValueError("材料读取失败或超时，请检查本机材料处理环境") from None
    if extracted.get("error"):
        raise ValueError(extracted["error"])
    if sum(map(len,extracted["pages"]))>30000:
        raise ValueError("提取文字超过 30000 字，请分拆材料")
    diagnostics={}
    candidates,issues=parse_fields(extracted["pages"],profile,diagnostics)
    return {"filename":Path(filename).name,"document_sha256":hashlib.sha256(data).hexdigest(),"method":extracted["method"],"ocr_language":extracted.get("language"),"pages":len(extracted["pages"]),"candidates":candidates,"issues":issues,"diagnostics":diagnostics,"text_preview":"\n\n".join(extracted["pages"])[:6000],"text_preview_truncated":len("\n\n".join(extracted["pages"]))>6000,"notice":"材料只在本机处理。识别结果不验证真伪，也不代表资格通过；请核对原文并逐项确认后再填写表单。图片使用临时文件，处理结束清除，不发送给模型或外部服务。"}
