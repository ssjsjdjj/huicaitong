"""Package unlabelled handoff files; all reference answers stay null."""
from pathlib import Path
import html,io,json,sys,zipfile,hashlib
SITE=Path(__file__).resolve().parent.parent;LOCAL=SITE.parent if (SITE.parent/'app.py').is_file() else SITE.parent/'huicaitong'
sys.path[:0]=[str(SITE),str(LOCAL)]
import v08_evaluation as v
from core import FIELD_LABELS
b=v.check_batch(v.batch());OUT=SITE/'dist/review-packs-v08';OUT.mkdir(parents=True,exist_ok=True)
def js(x):return json.dumps(x,ensure_ascii=False,indent=2).encode()
def esc(x):return html.escape(str(x))
def page(title,body):return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>body{max-width:1000px;margin:30px auto;padding:0 20px;font:16px/1.8 system-ui;color:#203c33}h1{font-size:26px}h2{font-size:21px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #cdd8cf;padding:9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f2;padding:16px}a{color:#1b674e}.note{background:#fff8df;padding:14px}article{margin:35px 0;border-top:2px solid #3f705c;padding-top:15px}.blank{height:100px;border:1px solid #bbc8be}@media print{article{break-before:page}a{color:inherit}body{margin:0}.blank{height:130px}}</style><h1>'+esc(title)+'</h1>'+body+'</html>').encode()
guide='''<p class="note">这是项目编写的60条合成候选，不是真实申请人。全部参考答案为空。原文补核日期仍为2026-10-30，未确认现行效力；评测不作完整资格或审批认定。</p>
<h2>领取、填写与交回</h2><ol><li>协调者把A和B包分别交给两位真实复核者。每人只收自己的任务包；勿交换答案，勿查看规则或模型预测。</li><li>打开线上专用入口（需要网络）；领取相应任务，或导入本包task-A.json / task-B.json。选择统一、可追溯的复核者标识，整个任务保持一致。无需提供姓名、证件号或联系方式。</li><li>逐条阅读人物字段、补充信息与原文，独立填入所有判断。原文编号至少选择1项；它只记录核对过的定位，不证明语义支持。</li><li>确认阅读后保存本条。修改任何答案会退回待复核，再次阅读并确认。可下载草稿跨设备恢复；“保存到本标签页”不保证关闭后保留。</li><li>60条全部确认后，明确声明独立复核并下载正式提交。把正式提交文件交给协调者，而不是把部分草稿当作已完成标注。</li></ol>
<p><a href="https://huicaitong-hangzhou.zishu41.chatgpt.site/#review-v08">打开v0.8专用复核入口</a>。本HTML及worksheet仅作离线阅读和纸面辅助；正式确认与提交使用网页。来源快照见primary-context.html及sources目录。</p>
<h2>标注目标与边界</h2><table><tr><th>维度</th><th>填写口径</th></tr><tr><td>基础条件初筛</td><td>仅就提供的政策快照、人物字段和已录入条件，区分条件满足、明确不满足、信息不足、超出自动覆盖、在读/未来规划。不是主管部门最终审批。</td></tr><tr><td>补充资格处理</td><td>已自填核对只表示相关信息已按题意给出；待确认、人工核验、超出覆盖、规划及先处理明确不满足项分别记录。自报“是/否”不认证真实材料。</td></tr><tr><td>缺失字段</td><td>选择尚需获取、且对本事项有用的核心或extra.补充字段；不把原文没确认的政策效力问题伪装成人物字段。</td></tr><tr><td>可接受下一问</td><td>最多8个可接受的下一问编号，表示任意其中一个均可作为下一步；没有必要追问选空。按必要性评判，不要求模拟固定程序排序。</td></tr><tr><td>材料准备信息</td><td>选择应提示核对的准备项，不表示已提交、材料真实或审批通过。</td></tr><tr><td>指定陈述与片段</td><td>先完成前面的独立判断，再检查作者设定的待核验陈述及指定片段。分别选择直接支持、部分支持、无关/不足支持、相冲突、快照/上下文/效力不足以判断，并另写依据。不是对真实模型输出的评价。</td></tr></table>
<h2>原文和不确定性</h2><p>必须结合上下文及原PDF核对跨列表格，不能只凭命中词。亲清页面快照只代表取证时可见文字；2021问答是历史材料。规范性文件承接、效力或输入无法表达的例外应明确写入解释。遇到资料不足可以保留不确定，不为追求三类均衡强行选答案。</p>
<h2>独立性与保留集纪律</h2><p>练习与口径校准使用原有开发练习，不用本60条试填后改系统或提示词。整批及近重复不参与训练、调参或模型选择。只排除本项目完全重复，不保证外部数据独立；三项任务仅两个政策家族。看过测试结果再改进系统时，需把该批降为开发数据并准备另一批新测试。</p>
<h2>文件、恢复与身份</h2><p>草稿/正式提交带批次、人物输入、原文及引擎指纹。错误、不同批次或被改动文件会拒绝恢复；覆盖前先备份，备份失败即停止。哈希不认证身份、专业资格、独立性或答案正确性。不要在解释中填写真实身份信息。</p>'''
(OUT/'reviewer-guide.html').write_bytes(page('惠才通 v0.8 真人独立复核说明',guide))
context=''.join('<article><h2>'+esc(d['title'])+'</h2><p>性质：'+esc(d['role'])+'；原文取证：'+esc(d['checked_on'])+'</p><p>'+esc(d['verification_note'])+'</p>'+''.join('<section id="'+esc(p['id'])+'"><h3>'+esc(p['id'])+' · '+esc(p['locator'])+'</h3><pre>'+esc(p['text'])+'</pre></section>' for p in b['corpus']['passages'] if p['document_id']==d['id'])+'</article>' for d in b['corpus']['documents'])
context=page('冻结原文定位与上下文',context)
sources={d['local_url'].lstrip('/'): (SITE/d['local_url'].lstrip('/')).read_bytes() for d in b['source_registry']['documents']}
for d in b['source_registry']['documents']:assert hashlib.sha256(sources[d['local_url'].lstrip('/')]).hexdigest()==d['sha256']
def archive(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(files.items()):
            i=zipfile.ZipInfo(name,(1980,1,1,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED;z.writestr(i,data)
    return stream.getvalue()
packs={}
for slot in ('A','B'):
    p=v.assignment(slot);assert all(c['expected'] is None for c in p['cases']) and all(r['answer'] is None and not r['confirmed'] for r in p['records'])
    worksheets=[]
    for c in p['cases']:
        rows=[(FIELD_LABELS.get(k,'城市'),value) for k,value in c['profile'].items()]+[(v.EXTRA[k]['label'],value) for k,value in c['supplementary'].items()]
        display=lambda x:'待确认' if x is None else '是' if x is True else '否' if x is False else {'fulltime':'全日制','parttime':'非全日制','mainland':'国内普通高校','overseas':'国（境）外高校','cn':'中国国籍','other':'其他国籍','master':'硕士','bachelor':'本科','phd':'博士','day':'明确到日','month':'仅年月','unknown':'未核对'}.get(x,str(x))
        table='<table>'+''.join('<tr><td>'+esc(k)+'</td><td>'+esc(display(x))+'</td></tr>' for k,x in rows)+'</table>'
        probe=c['evidence_probe']
        worksheets.append('<article><h2>'+esc(c['case_id'])+'</h2><p>事项：'+esc(next(x['title'] for x in b['policies'] if x['id']==c['policy_id']))+'</p>'+table+'<p>基础条件判断：________________；补充资格处理：________________</p><p>缺失字段、可接受下一问、准备信息：________________</p><p>原文定位与条件判断解释：</p><div class="blank"></div><h3>指定陈述核对（非答案）</h3><p>'+esc(probe['claim'])+'</p><pre>'+esc(probe['quote'])+'</pre><a href="primary-context.html#'+probe['passage_id']+'">'+esc(probe['passage_id'])+' 完整定位</a><p>支持类别：________________；依据：</p><div class="blank"></div><p>□ 已独立阅读原文；复核者标识：________；复核时间：________</p></article>')
    files={'index.html':(OUT/'reviewer-guide.html').read_bytes(),'primary-context.html':context,'task-'+slot+'.json':js(p),'worksheet-'+slot+'.html':page('v0.8 '+slot+'任务 · 60条空白辅助记录',''.join(worksheets)),'source-registry.json':js(b['source_registry']),**sources}
    packs['reviewer-'+slot+'.zip']=archive(files);(OUT/('reviewer-'+slot+'.zip')).write_bytes(packs['reviewer-'+slot+'.zip'])
coord='''<h2>分发与终审清单</h2><ol><li>为A、B、第三人选择三个不同的真实复核者，先用开发练习校准口径。分别分发reviewer-A.zip和reviewer-B.zip，不发抽样设计表。</li><li>收回完整正式提交，保留原始文件；不把草稿或部分确认当作完整标注。</li><li>网页“v0.8专用复核”的协调者入口导入A/B，点击对照。所有60条均由第三人阅读原文和两份解释，逐条选择并填写终审依据，不只处理结构分歧。两人都错就退回修订后重交。</li><li>下载终审草稿随时保存；换A/B提交会清除旧终审选择，载入前备份。未完成60条不得冻结。</li><li>确认本批及近重复未用于开发后冻结，先下载冻结文件，再导出无答案预测输入。把模型、检查点SHA、检索/输入模式、提示词、解码参数、训练来源和评价方案锁定在experiment-registration.json；时间应早于第一次测试推理。</li></ol><h2>指标与局限</h2><p>分别评价基础条件、补充资格、缺失字段、材料、原文编号、可接受下一问及指定陈述的片段支持标签。缺失、空输出、格式错误均留在60条分母；列出误判条件满足和误判补充项已核对。片段标签只评价固定陈述，不自动认证模型生成解释的语义。全部合成、仅两个政策家族，不能声称真实办理准确率或跨城市泛化。</p><p>不得填入模拟人名/软件夹具冒充真实复核。只有真实复核完成后，才有人工参考答案或正式实验成绩。</p>'''
registration={'protocol':v.PROTOCOL,'batch_sha256':b['sha256'],'dataset_sha256':None,'locked_at':None,'reviewer_A':None,'reviewer_B':None,'adjudicator':None,'source_registry_sha256':b['source_registry']['sha256'],'application_engine_sha256':b['engine_sha256'],'models':[],'training_data_versions':[],'prompt_sha256':None,'evidence_mode':None,'retriever_index_version':None,'generation_parameters':None,'primary_metrics':['screening','qualification','false_conditions_met','false_recorded'],'test_use_declaration':None,'actual_results':None}
coordinator={'index.html':page('v0.8 协调者与第三人终审操作',guide+coord),'coordinator-only-design.json':(SITE/'data/review-v08-design.json').read_bytes(),'candidate-audit.json':js(b['audit']),'experiment-registration.json':js(registration),'reviewer-A.zip':packs['reviewer-A.zip'],'reviewer-B.zip':packs['reviewer-B.zip']}
(OUT/'coordinator.zip').write_bytes(archive(coordinator))
manifest={'protocol':v.PROTOCOL,'batch_sha256':b['sha256'],'cases':60,'answers_blank':True,'human_reviews_completed':0,'source_registry_sha256':b['source_registry']['sha256'],'engine_sha256':b['engine_sha256'],'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='manifest.json'}}
(OUT/'manifest.json').write_bytes(js(manifest))
bundle={p.name:p.read_bytes() for p in OUT.iterdir() if p.is_file()}
material_work=SITE/'.work';material_work.mkdir(exist_ok=True)
(material_work/'huicaitong-v08-review-materials.zip').write_bytes(archive(bundle))
print(json.dumps({'output':str(OUT),'cases':60,'blank_answers':60,'human_reviews_completed':0,'material_files':list(bundle)},ensure_ascii=False))
