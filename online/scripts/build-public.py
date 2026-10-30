"""Deterministic browser build: small bootstrap, versioned core and lazy PDF assets."""
from pathlib import Path
import hashlib
import io
import json
import shutil
import sys
import zipfile

SITE=Path(__file__).resolve().parent.parent
LOCAL=SITE.parent if (SITE.parent/'app.py').is_file() else SITE.parent/'huicaitong'
WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
DIST=SITE/'dist'
ASSETS=DIST/'assets'
ASSETS.mkdir(parents=True,exist_ok=True)
previous=json.loads((DIST/'assets.json').read_text(encoding='utf-8')) if (DIST/'assets.json').exists() else {}
sys.path.insert(0,str(LOCAL))
import app
from core import RAW_FIELDS, validate_profile
from fixtures import CASES


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def sha(data):return hashlib.sha256(data).hexdigest()


def profile_hash(profile):
    clean=validate_profile(profile)
    return sha(encode({field:clean.get(field) for field in sorted(RAW_FIELDS)}))


def archive(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as output:
        for name,data in sorted(files.items()):
            entry=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            output.writestr(entry,data)
    return stream.getvalue()


def asset(kind,data,suffix,label):
    name=f'{kind}-{sha(data)[:16]}.{suffix}'
    (ASSETS/name).write_bytes(data)
    return {'url':'/assets/'+name,'bytes':len(data),'sha256':sha(data),'label':label}


seed=json.loads((LOCAL/'data'/'policies.json').read_text(encoding='utf-8'))
draft=json.loads((LOCAL/'data'/'review_draft.json').read_text(encoding='utf-8'))
seen={profile_hash(row['profile']) for row in draft['cases']}
seen.update(profile_hash(row['profile']) for row in CASES)
inputs=[]
for file in sorted((LOCAL/'data'/'generated').glob('*.jsonl')):
    count=0
    for line in file.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        row=json.loads(line)
        messages=row.get('prompt') or row.get('messages')
        if not isinstance(messages,list):continue
        for message in messages:
            if message.get('role')!='user':continue
            context=json.loads(message['content'])
            if isinstance(context,dict) and isinstance(context.get('applicant'),dict):
                seen.add(profile_hash(context['applicant']));count+=1
    inputs.append({'file':file.name,'sha256':sha(file.read_bytes()),'tasks':count})
known={'profile_sha256':sorted(seen),'inputs':inputs,'notice':'只覆盖本项目当前打包的开发与历史检查记录，以及内置练习；不检测近重复或外部使用。'}

core={}
for name in ('app.py','core.py','fixtures.py','guidance.py','llm.py','materials.py','policy_time.py','presentation.py','rag.py','review.py','store.py','document_worker.py'):
    core[name]=(LOCAL/name).read_bytes()
for name in ('browser_backend.py','human_evaluation.py'):
    core[name]=(SITE/name).read_bytes()
for name in ('__init__.py','evaluate.py','rewards.py'):
    core['training/'+name]=(LOCAL/'training'/name).read_bytes()
for name in ('policies.json','review_draft.json'):
    core['data/'+name]=(LOCAL/'data'/name).read_bytes()
core['data/evaluation-known-profiles.json']=encode(known)
for source in (LOCAL/'data'/'material_examples').iterdir():
    if source.suffix in {'.pdf','.txt'}:core['data/material_examples/'+source.name]=source.read_bytes()
core['checkpoints/selection.json']=(LOCAL/'checkpoints'/'selection.json').read_bytes()
for phase in ('sft','grpo'):
    core[f'checkpoints/{phase}/run_summary.json']=(LOCAL/'checkpoints'/phase/'run_summary.json').read_bytes()
for source in (LOCAL/'training-runs').glob('*evaluation.json'):
    core['training-runs/'+source.name]=source.read_bytes()

pypdf=WORK/'documents-venv'/'Lib'/'site-packages'/'pypdf'
if pypdf.is_dir():
    pdf={'pypdf/'+p.relative_to(pypdf).as_posix():p.read_bytes() for p in pypdf.rglob('*.py')}
else:
    # Reuse the verified reader shipped with this frozen release.
    with zipfile.ZipFile(DIST/'python-app.zip') as existing:
        pdf={name:existing.read(name) for name in existing.namelist() if name.startswith('pypdf/') and name.endswith('.py') and '..' not in Path(name).parts}
    if not pdf:raise RuntimeError('The frozen pypdf reader is missing from dist/python-app.zip.')
core_asset=asset('core',archive(core),'zip','政策核验程序')
pdf_asset=asset('pdf',archive(pdf),'zip','PDF 阅读组件')
# Retain a full compatibility bundle for the original reproduction scripts.
(DIST/'python-app.zip').write_bytes(archive({**core,**pdf}))

meta={'city':'杭州','snapshot_date':app.TODAY,'checked_on':seed['checked_on'],
      'policies':sum(p['status']=='included' for p in seed['policies']),
      'clauses':sum(len(p['clauses']) for p in seed['policies'] if p['status']=='included'),
      'retriever':'中文 BM25 · 浏览器内检索','model_configured':False,'model_name':'公开演示 · 模型实验记录',
      'training':app.training_status(),'selected_model':app.selected_model(),'model_evaluations':app.model_evaluations(),
      'notice':seed['notice'],'version':'0.5.0-online','deployment_mode':'browser'}
bootstrap={'/api/health':{'ok':True,'version':'0.5.0-online'},'/api/meta':meta,
           '/api/policies':{'policies':seed['policies']},'/api/examples':{'examples':[{'name':c['id'],'profile':c['profile']} for c in CASES]},
           '/api/materials/capabilities':{'text':True,'pdf':True,'image':False,'ocr_language':None},
           '/api/materials/examples':{'examples':[{'id':'graduation','title':'毕业材料 · 合成 PDF','filename':'graduation-demo.pdf'},{'id':'insurance','title':'连续参保 · 合成 PDF','filename':'insurance-demo.pdf'},{'id':'gap','title':'参保中断 · 合成 TXT','filename':'insurance-gap-demo.txt'}]},
           '/api/review/draft':{**draft,'field_labels':app.FIELD_LABELS}}
bootstrap_asset=asset('bootstrap',encode(bootstrap),'json','页面资料')

runtime_root=DIST/'vendor'/'pyodide'
runtime_names=('pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json')
if (runtime_root/'pyodide.mjs').exists():runtime_source=runtime_root
else:
    candidates=sorted(runtime_root.glob('314.0.7-*/pyodide.mjs'))
    if len(candidates)!=1:raise RuntimeError('Select one verified Pyodide 314.0.7 runtime.')
    runtime_source=candidates[0].parent
runtime_data={name:(runtime_source/name).read_bytes() for name in runtime_names}
runtime_id='314.0.7-'+sha(encode({name:sha(data) for name,data in runtime_data.items()}))[:12]
runtime_path=runtime_root/runtime_id
runtime_path.mkdir(exist_ok=True)
for name,data in runtime_data.items():(runtime_path/name).write_bytes(data)
if runtime_source==runtime_root:
    for name in runtime_names:(runtime_root/name).unlink()
runtime_base='/vendor/pyodide/'+runtime_id+'/'
runtime_assets=[{'url':runtime_base+name,'bytes':len(data),'sha256':sha(data),'label':'核验引擎' if name.endswith('.wasm') else 'Python 标准库' if name.endswith('.zip') else '运行组件'} for name,data in runtime_data.items()]

custom=('online.js','runtime-worker.mjs','asset-cache.mjs','import-recovery.mjs','review-recovery.mjs','review-workbench.js','online.css','review-panels.html','review-dialog.html','scripts/predict-frozen.py')
web_inputs={p.name:sha(p.read_bytes()) for p in (LOCAL/'web').iterdir() if p.is_file()}
overrides={p.name:p for p in (SITE/'web-overrides').iterdir() if p.is_file()}
web_inputs.update({name:sha(p.read_bytes()) for name,p in overrides.items()})
build_id=sha(encode({'custom':{name:sha((SITE/name).read_bytes()) for name in custom},'web':web_inputs,'core':core_asset['sha256'],'pdf':pdf_asset['sha256'],'bootstrap':bootstrap_asset['sha256']}))[:16]
for name in ('app.js','workflow.js','ux.js','styles.css','workflow.css','ux.css','icon.svg'):
    shutil.copy2(overrides.get(name,LOCAL/'web'/name),DIST/name)
for name in custom:
    if name.endswith(('.js','.mjs','.css')):(DIST/name).write_text((SITE/name).read_text(encoding='utf-8').replace('__HCT_BUILD__',build_id),encoding='utf-8')
(DIST/'predict-frozen.py').write_bytes((SITE/'scripts'/'predict-frozen.py').read_bytes())

html=(LOCAL/'web'/'index.html').read_text(encoding='utf-8')
html=html.replace('<script src="/app.js" defer>','<link rel="stylesheet" href="/online.css"><script src="/online.js" defer></script><script src="/app.js" defer>')
html=html.replace('<script src="/ux.js" defer>','<script src="/review-workbench.js" defer></script><script src="/ux.js" defer>')
html=html.replace('本地研究原型','公开体验版').replace('连接本地模型 <span>↗</span>','模型实验说明 <span>↗</span>').replace('<span class="version">v0.4</span>','<span class="version">v0.5.1</span>')
status='''<section class="engine-status" id="engine-status" data-state="loading" role="status"><div><strong>浏览器核验</strong><span id="engine-message">页面可先浏览与填写，正在载入政策资料…</span></div><progress id="engine-progress" max="100" aria-label="核验组件准备进度"></progress><button class="btn btn-quiet small" id="engine-retry" hidden>重试加载（保留填写内容）</button></section>
<section id="import-recovery-banner" class="import-recovery" role="alert" hidden><h2>政策导入恢复需要处理</h2><p id="import-recovery-summary"></p><ul id="import-recovery-errors"></ul><p id="import-recovery-notice"></p><div class="toolbar"><button class="btn small" id="import-original-backup">下载原始记录</button><button class="btn small" id="import-live-backup">备份当前可用政策</button><button class="btn small" id="import-retry">重新尝试恢复</button><button class="btn small" id="import-use-recovered">备份后仅保留可用政策</button></div></section>'''
html=html.replace('<main id="main">','<main id="main">'+status+'<div class="online-banner"><strong>公开体验版</strong> · 申请资料只在你的浏览器内处理。页面可先浏览和填写；核验引擎后台准备，PDF 组件按需加载。大模型保留历史实验记录，当前不提供在线推理。资料来源核对日期为 2026-10-21。</div>')
html=html.replace('accept=".pdf,.txt,.png,.jpg,.jpeg"','accept=".pdf,.txt"')
html=html.replace('文件在本机处理，不发送给模型或外部服务。文字 PDF 最多 5 页。图片识别不可用时，可从原系统导出文字 PDF，或粘贴完整逐月记录为 TXT；不要把图片仅改后缀。','文件只在当前浏览器处理，不上传服务器。支持 TXT 和最多 5 页的文字 PDF；图片与扫描 PDF 暂不支持。PDF 阅读组件仅在首次读取 PDF 时准备。')
html=html.replace('导入前需人工核对原文。','导入前需人工核对原文。导入只影响当前浏览器；恢复失败记录会保留，可下载备份后整理。')
html=html.replace('<div id="knowledge-list"','<details class="panel import-backups"><summary>政策导入恢复与备份</summary><p id="import-backup-status" role="status"></p><div id="import-backup-history"></div></details><div id="knowledge-list"')
html=html.replace('训练步数、峰值显存和评测结果读取自本机运行记录。','训练步数、峰值显存和评测结果来自冻结的历史实验。公开网页不执行 GPU 训练或推理。')
html=html.replace('36 条合成人物草稿，答案留空。请先阅读原文，再记录你的结论与依据。','内置 36 条仅作开发练习；可另建新案例，人工确认后冻结评测集并比较实际预测。')
panels=(SITE/'review-panels.html').read_text(encoding='utf-8')
guide,benchmarks=panels.split('<!-- BENCHMARKS -->',1)
html=html.replace('<div class="review-layout">',guide+'<div class="review-layout">',1)
marker='    <section class="view" id="view-report" hidden>'
position=html.index(marker)
before=html[:position];end=before.rfind('</section>')
html=before[:end]+benchmarks+before[end:]+html[position:]
html=html.replace('<span id="review-storage-status" role="status"></span>','<span id="review-storage-status" role="status"></span><button class="btn btn-quiet small" id="review-recovery-download" hidden>下载未恢复的原始复核记录</button><button class="btn btn-quiet small" id="review-recovery-saved" hidden>下载既有复核恢复备份</button>')
html=html.replace('<div class="toast" id="toast"',(SITE/'review-dialog.html').read_text(encoding='utf-8')+'<div class="toast" id="toast"')
start=html.index('<h2>连接你自己的本地模型</h2>');end=html.index('</dialog>',start)
html=html[:start]+'<h2>模型实验说明</h2><p>公开版当前不运行推理模型。「训练与评测」保留真实历史实验；「人工复核」支持冻结标注并比较你实际生成的预测。规则结果与模型实验分开记录。</p><button class="btn btn-primary full" id="refresh-model">查看当前运行状态</button>'+html[end:]
for name in ('styles.css','workflow.css','ux.css','online.css','app.js','workflow.js','ux.js','online.js','review-workbench.js'):
    html=html.replace('/'+name+'"','/'+name+'?v='+build_id+'"')
(DIST/'index.html').write_text(html.replace('__HCT_BUILD__',build_id),encoding='utf-8')

app_js=(DIST/'app.js').read_text(encoding='utf-8').replace('规则基线 · 模型未连接','浏览器规则核验 · 公开演示').replace('需连接本地模型','公开版未启用在线推理').replace('连接本地模型','模型实验说明').replace('实验模型未连接','公开版未启用在线模型')
app_js=app_js.replace('尚未检测到配置，请保存并重启应用','公开版运行正常，当前不提供在线模型推理')
app_js=app_js.replace('已导入 ${r.imported} 份政策。请继续核对规则与来源。','已导入 ${r.imported} 份政策，仅影响当前浏览器。${r.storage_notice||\'\'}')
(DIST/'app.js').write_text(app_js,encoding='utf-8')
workflow=(DIST/'workflow.js').read_text(encoding='utf-8').split('function updateReviewProgress(){',1)[0]
(DIST/'workflow.js').write_text(workflow,encoding='utf-8')

manifest={'build_id':build_id,'version':'0.5.1-online','bootstrap':bootstrap_asset,'core':core_asset,'pdf':pdf_asset,'runtime_base':runtime_base,'cached_assets':[core_asset,pdf_asset,*runtime_assets]}
(DIST/'assets.json').write_bytes(encode(manifest))
# Remove only previous generated bundles under this build's assets directory.
current={a['url'] for a in (core_asset,pdf_asset,bootstrap_asset)}
for key in ('core','pdf','bootstrap'):
    url=previous.get(key,{}).get('url','')
    if url and url not in current:
        target=(DIST/url.lstrip('/')).resolve()
        if target.is_relative_to(ASSETS.resolve()) and target.name.startswith(('core-','pdf-','bootstrap-')) and target.is_file():target.unlink()
provenance={'source_snapshot_date':'2026-10-21','runtime':'Pyodide 314.0.7 / Python 3.14.2','pypdf_version':'6.10.0','build_id':build_id,'applicant_uploads':False,'model_inference':False,'known_profile_groups':len(seen),'core_files':{name:sha(data) for name,data in sorted(core.items())},'pdf_files':{name:sha(data) for name,data in sorted(pdf.items())}}
(SITE/'source-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'build_id':build_id,'bootstrap_bytes':bootstrap_asset['bytes'],'core_bytes':core_asset['bytes'],'lazy_pdf_bytes':pdf_asset['bytes'],'runtime_bytes':sum(a['bytes'] for a in runtime_assets),'known_profile_groups':len(seen)}))
