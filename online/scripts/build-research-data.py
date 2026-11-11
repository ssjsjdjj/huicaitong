"""Version primary text and derive diagnostics from hash-bound historical outputs.
Never consume the reserved 54 cases or generate model predictions/human labels.
"""
from pathlib import Path
import hashlib,json,re,sys
SITE=Path(__file__).resolve().parent.parent
LOCAL=SITE.parent if (SITE.parent/'app.py').is_file() else SITE.parent/'huicaitong'
WORK=SITE/'.work'
WORK.mkdir(exist_ok=True)
sys.path[:0]=[str(SITE),str(LOCAL),str(WORK/'documents-venv/Lib/site-packages')]
# Use the exact PDF reader shipped in the frozen browser release.
import zipfile
frozen=WORK/'frozen-python';frozen.mkdir(exist_ok=True)
with zipfile.ZipFile(SITE/'dist/python-app.zip') as archive:
    for name in archive.namelist():
        if name.startswith('pypdf/') and name.endswith('.py'):
            target=(frozen/name).resolve()
            assert target.is_relative_to(frozen.resolve())
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
sys.path.insert(0,str(frozen))
from pypdf import PdfReader
from primary_evidence import digest
from diagnostics import analyze
from training.evaluate import evaluate_predictions

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def build():
    registry=json.loads((SITE/'data/source-registry.json').read_text(encoding='utf-8'));byid={d['id']:d for d in registry['documents']};documents=[];passages=[]
    for id in ('living-guide-2024','rent-platform-2026','rent-faq-2021'):
        d=byid[id];path=SITE/d['local_url'].lstrip('/');assert sha(path)==d['sha256']
        pdf=path.suffix=='.pdf';role='historical_qa' if id=='rent-faq-2021' else 'direct_source'
        pages=[{'page':i+1,'text':page.extract_text().replace('\r\n','\n')} for i,page in enumerate(PdfReader(path).pages)] if pdf else [{'page':None,'text':path.read_text(encoding='utf-8').replace('\r\n','\n')}]
        documents.append({'id':id,'title':d['title'],'publisher':d['publisher'],'issued_on':d['issued_on'],'checked_on':d['checked_on'],'url':d['url'],'local_url':d['local_url'],'source_sha256':d['sha256'],'role':role,'visible_from':d['issued_on'] if pdf else d['checked_on'],'temporal_basis':'文件标明日期' if pdf else '页面取证日期；不能倒推历史页面状态','verification_note':d['verification_note'],'pages':pages})
        for pg in pages:
            text=pg['text'];ranges=[(0,len(text))] if pdf else [(m.start(),m.end()) for m in re.finditer(r'\S[^\n]*(?:\n(?!\n)[^\n]+)*',text)]
            for start,end in ranges:
                excerpt=text[start:end];line_start=text[:start].count('\n')+1;line_end=line_start+excerpt.count('\n')
                page=pg['page'];pid=id+('-p'+str(page) if page else '-l'+str(line_start))
                layout='本页含跨列申请条件表，请打开原PDF核对行列归属，提取文本不能表达表格的对应关系。' if id=='living-guide-2024' and page in (2,3) else ''
                passages.append({'id':pid,'document_id':id,'page':page,'start':start,'end':end,'line_start':line_start,'line_end':line_end,'locator':'PDF第'+str(page)+'页' if page else f'页面快照第{line_start}—{line_end}行','text':excerpt,'layout_note':layout,'searchable':len(re.sub(r'\s','',excerpt))>=70})
    anchors={}
    for id,page in [('living-scope',2),('living-time',2),('living-employer',3),('living-insurance',3),('living-exclusion',4),('living-payment',2),('living-materials',4),('living-second-scope',2),('living-second-insurance',3),('living-second-payment',5),('living-second-materials',4)]:
        anchors[id]=['living-guide-2024-p'+str(page)]
    anchors['living-second-payment']=['living-guide-2024-p2','living-guide-2024-p5']
    # Explicit paragraph anchors, checked against the captured primary text.
    for id,quotes in {'rent-eligibility':['“申请家庭”包括申请人','毕业时间在2020年'],'rent-time':['第一笔补贴申请时限为毕业后2年内','第一笔补贴应在杭州用人单位'],'rent-standard':['每户每年发放1万元，可发放三年'],'rent-channel':['每笔补贴均需提交申请']}.items():
        anchors[id]=[]
        for quote in quotes:
            matches=[p['id'] for p in passages if p['document_id']=='rent-platform-2026' and quote in p['text']]
            assert matches,(id,quote);anchors[id].extend(matches)
        anchors[id]=list(dict.fromkeys(anchors[id]))
    excluded=[{'id':d['id'],'title':d['title'],'reason':'签章扫描原件尚未逐页完成OCR及人工核对，保留下载，不纳入文本检索' if d['id'] in ('rules-126-2023','talent-4-2020') else '行动计划历史背景文件，未纳入本轮办理条件检索'} for d in registry['documents'] if d['id'] not in {x['id'] for x in documents}]
    data={'schema_version':1,'corpus_id':'hz-primary-text-v1','created_on':'2026-11-11','sources_checked_on':registry['checked_on'],'source_registry_sha256':registry['sha256'],'documents':documents,'passages':passages,'clause_anchors':anchors,'excluded_documents':excluded,'notice':'检索2026-10-30已取得的官方资料快照，未在本轮重新确认现行效力。BM25分数是词法相关度，不是可信概率；命中词高亮不代表片段支持结论。跨页内容需结合上下文，表格页需核对原PDF。'}
    data['sha256']=digest(data);write(SITE/'data/primary-corpus.json',data)
    root=LOCAL/'training-runs';report_path=root/'grpo-development-full-evaluation.json';report=json.loads(report_path.read_text(encoding='utf-8'));gold_path=root/'grpo-development-full.gold.jsonl';pred_path=root/'grpo-development-full.jsonl'
    selection=json.loads((LOCAL/'checkpoints/selection.json').read_text(encoding='utf-8'))
    assert selection['selected_metrics']['report_sha256']==sha(report_path),'Historical selected report changed'
    assert sha(gold_path)==report['input_sha256']['gold'] and sha(pred_path)==report['input_sha256']['predictions']
    rows=lambda p:[json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]
    gold=rows(gold_path);predictions=rows(pred_path);metrics,details=evaluate_predictions(gold,predictions)
    assert metrics['confusion_matrix']==report['confusion_matrix'] and metrics['cases']==report['cases']
    tasks=[]
    for row in gold:
        target=json.loads(row['ground_truth']) if isinstance(row['ground_truth'],str) else row['ground_truth']
        context=json.loads(next(m['content'] for m in row['prompt'] if m['role']=='user'))
        tasks.append({'case_id':row['case_id'],'policy_id':target['policy_id'],'profile':context['applicant'],'ground_truth':target})
    policies=json.loads((LOCAL/'data/policies.json').read_text(encoding='utf-8'))['policies'];diagnostic=analyze(tasks,predictions,details,policies)
    historical={'schema_version':1,'experiment':'grpo-balanced / 92条历史开发集','label_source':'synthetic_weak_supervision','purpose':'development','notice':'历史模型的真实已保存输出，参考为合成弱监督标签；开发集曾参与模型选择。本页不重新运行模型，不构成人工独立测试结果。','input_sha256':{**report['input_sha256'],'original_report':sha(report_path)},'metrics':report,'diagnostics':diagnostic}
    write(SITE/'data/historical-diagnostics.json',historical)
    print(json.dumps({'indexed_documents':len(documents),'passages':len(passages),'searchable_passages':sum(p['searchable'] for p in passages),'historical_cases':len(gold),'false_pass':diagnostic['summary']['false_pass'],'corpus_sha256':data['sha256']}))

if __name__=='__main__':build()
