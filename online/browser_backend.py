"""Browser-only adapter. Reuse the local app's audited routes and rule modules."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse,parse_qs

ROOT=Path(__file__).resolve().parent
tree=ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
nodes=[]
for item in tree.body:
    if isinstance(item,ast.ImportFrom) and item.module=='http.server':
        continue
    if isinstance(item,ast.FunctionDef) and item.name=='main':
        continue
    if isinstance(item,ast.If):
        continue
    if isinstance(item,ast.ClassDef) and item.name=='Handler':
        item.bases=[]
    nodes.append(item)
namespace={'__file__':str(ROOT/'app.py'),'__name__':'browser_app'}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'browser_app','exec'),namespace)

from core import validate_profile
from document_worker import read_document
from materials import parse_fields
from store import PolicyStore
from human_evaluation import new_case, restore_rows, summarize, freeze_dataset, evaluate_dataset, verify_dataset
import campaign_review as campaign
import primary_evidence
import application_flow
import v08_evaluation as v08
import ai_prereview as ai_review
import evidence_context


def browser_extract(body,profile):
    filename=body.get('filename')
    encoded=body.get('content_base64')
    if not isinstance(filename,str) or len(filename)>160 or Path(filename).suffix.lower() not in {'.txt','.pdf'}:
        raise ValueError('公开版支持 TXT 和文字 PDF，暂不支持图片 OCR。')
    if not isinstance(encoded,str) or len(encoded)>2_670_000:
        raise ValueError('材料须为不超过 2MB 的文件')
    try:
        data=base64.b64decode(encoded,validate=True)
    except ValueError:
        raise ValueError('材料编码无效') from None
    if not 0<len(data)<=2_000_000:
        raise ValueError('材料须为不超过 2MB 的非空文件')
    extracted=read_document(filename,data)
    if sum(map(len,extracted['pages']))>30000:
        raise ValueError('提取文字超过 30000 字，请分拆材料')
    diagnostics={}
    candidates,issues=parse_fields(extracted['pages'],profile,diagnostics)
    text='\n\n'.join(extracted['pages'])
    return {'filename':Path(filename).name,'document_sha256':hashlib.sha256(data).hexdigest(),
            'method':extracted['method'],'ocr_language':None,'pages':len(extracted['pages']),
            'candidates':candidates,'issues':issues,'diagnostics':diagnostics,
            'text_preview':text[:6000],'text_preview_truncated':len(text)>6000,
            'notice':'材料只在当前浏览器内处理，不上传服务器或发送给模型。提取结果不验证真伪，请逐项核对后确认。'}


namespace['extract_material']=browser_extract
namespace['material_capabilities']=lambda:{'text':True,'pdf':True,'image':False,'ocr_language':None}
namespace['model_config']=lambda:{'configured':False,'model':'公开演示 · 模型实验记录'}
store=PolicyStore(ROOT/'runtime'/'policies.sqlite3')


class BrowserHandler(namespace['Handler']):
    def __init__(self,path,body):
        self.path=path
        raw=json.dumps(body,ensure_ascii=False).encode('utf-8')
        self.headers={'Content-Type':'application/json','Content-Length':str(len(raw))}
        self.rfile=io.BytesIO(raw)
        self.server=SimpleNamespace(store=store)
        self.value=None
        self.status=200

    def trusted_request(self):
        return True

    def send_json(self,value,status=200):
        self.value=value
        self.status=status


def request(path,body=None):
    try:
        if not isinstance(path,str) or not path.startswith('/api/'):
            raise ValueError('接口地址无效')
        if body is not None and not isinstance(body,dict):
            raise ValueError('请求须为 JSON 对象')
        route=urlparse(path).path
        if route=='/api/ai-review/catalogue' and body is None:return {'status':200,'data':ai_review.catalogue()}
        if route.startswith('/api/ai-review/') and body is not None:
            op=route.rsplit('/',1)[1]
            if op=='request':value=ai_review.request(body.get('case_id'))
            elif op=='import':value=ai_review.import_response(body)
            elif op in {'check','packet','restore','context'}:value=getattr(ai_review,op)(body)
            else:raise ValueError('未知AI辅助预审操作')
            return {'status':200,'data':value}
        if route=='/api/v08/meta' and body is None:return {'status':200,'data':v08.meta()}
        if route=='/api/v08/catalogue' and body is None:return {'status':200,'data':v08.catalogue()}
        if route.startswith('/api/v08/') and body is not None:
            op=route.rsplit('/',1)[1]
            if op=='assignment':value=v08.assignment(body.get('slot'))
            elif op=='restore':value=v08.restore(body.get('packet'))
            elif op=='restore-adjudication':value=v08.restore_adjudication(body.get('packet'))
            elif op=='verify':value={'batch_id':v08.verify_dataset(body.get('dataset'))['batch_id']}
            elif op=='verify-submission':value=v08.submission(body.get('packet'),v08.batch())
            elif op=='template':value=v08.prediction_input(body.get('dataset'))
            elif op in {'draft','submit','compare','freeze','evaluate','adjudication-draft'}:value=getattr(v08,op.replace('-','_'))(body)
            else:raise ValueError('未知v0.8复核操作')
            return {'status':200,'data':value}
        if route=='/api/application/meta' and body is None:
            return {'status':200,'data':{'intents':application_flow.INTENTS,'supplementary_fields':application_flow.EXTRA,'notice':application_flow.NOTICE}}
        if route in {'/api/application/assess','/api/application/guide','/api/application/packet','/api/application/restore'} and body is not None:
            operation=route.rsplit('/',1)[1]
            result=application_flow.restore(body.get('packet'),store.all()) if operation=='restore' else getattr(application_flow,operation)(body,store.all())
            if operation=='assess':
                for row in result['results']:row['source_time']=evidence_context.policy_time(row['policy_id'],result['as_of'])
            return {'status':200,'data':result}
        if route=='/api/primary/catalogue' and body is None:
            return {'status':200,'data':evidence_context.catalogue()}
        if route in {'/api/primary/search','/api/primary/passage','/api/primary/clause'} and body is None:
            args=parse_qs(urlparse(path).query,keep_blank_values=True);arg=lambda k,default='':args.get(k,[default])[0]
            if route.endswith('/search'):
                if arg('history','0') not in {'0','1'}:raise ValueError('历史资料开关无效')
                if arg('later_snapshot','0') not in {'0','1'}:raise ValueError('晚取证快照开关无效')
                data=evidence_context.search(arg('q'),arg('as_of'),arg('history','0')=='1',int(arg('limit','8')),include_later_capture=arg('later_snapshot','0')=='1')
            elif route.endswith('/passage'):
                data=primary_evidence.passage(arg('id'),arg('q'))
                if arg('as_of'):data['temporal_context']=evidence_context.time_context(arg('as_of'),[data['passage']['document_id']])
            else:data=evidence_context.clause_evidence(arg('id'))
            return {'status':200,'data':data}
        if route=='/api/diagnostics/history' and body is None:
            return {'status':200,'data':json.loads((ROOT/'data/historical-diagnostics.json').read_text(encoding='utf-8'))}
        if route=='/api/sources' and body is None:
            return {'status':200,'data':campaign.registry()}
        if route=='/api/campaign' and body is None:
            return {'status':200,'data':{'batch_id':campaign.campaign()['batch_id'],'audit':campaign.audit_candidates()}}
        if route=='/api/campaign/assignment' and body is not None:
            return {'status':200,'data':{'packet':campaign.assignment(body.get('slot'))}}
        if route=='/api/campaign/submit' and body is not None:
            return {'status':200,'data':{'packet':campaign.submission(body,store.all())}}
        if route=='/api/campaign/compare' and body is not None:
            return {'status':200,'data':campaign.compare(body,store.all())}
        if route=='/api/campaign/freeze' and body is not None:
            return {'status':200,'data':{'dataset':campaign.reconcile(body,store.all())}}
        if route=='/api/review/new-case' and body is not None:
            return {'status':200,'data':{'case':new_case(body,store.all())}}
        if route=='/api/review/restore' and body is not None:
            if body.get('schema_version')!=1:raise ValueError('草稿格式版本无效')
            return {'status':200,'data':{'cases':restore_rows(body.get('cases'),store.all()),'notice':'草稿已恢复；待复核记录仍不计入人工标注。'}}
        if route=='/api/review/summary' and body is not None:
            return {'status':200,'data':summarize(restore_rows(body.get('cases'),store.all()),store.all())}
        if route=='/api/benchmark/freeze' and body is not None:
            return {'status':200,'data':{'dataset':freeze_dataset(body,store.all())}}
        if route=='/api/benchmark/verify' and body is not None:
            rows,tasks,policies=verify_dataset(body.get('dataset'))
            return {'status':200,'data':{'summary':summarize(rows,policies),'dataset_sha256':body['dataset']['sha256']}}
        if route=='/api/benchmark/evaluate' and body is not None:
            return {'status':200,'data':evaluate_dataset(body)}
        if urlparse(path).path=='/api/model-assess':
            return {'status':503,'data':{'error':'公开版没有运行推理模型。训练与评测页展示真实历史实验记录。'}}
        handler=BrowserHandler(path,body)
        if body is None:
            handler.api_get(urlparse(path))
        else:
            handler.do_POST()
        if urlparse(path).path=='/api/meta' and handler.status==200:
            handler.value.update(version='0.8.3-online',deployment_mode='browser',model_configured=False,
                                 model_name='公开演示 · 模型实验记录',retriever='中文 BM25 · 浏览器内检索')
        if route=='/api/health' and handler.status==200:
            handler.value['version']='0.8.3-online'
        result={'status':handler.status,'data':handler.value}
        if urlparse(path).path=='/api/import' and handler.status==200:
            result['imports']=imported_policies()
        return result
    except (ValueError,TypeError,KeyError,OverflowError) as error:
        return {'status':400,'data':{'error':str(error)}}
    except Exception:
        return {'status':500,'data':{'error':'浏览器核验未完成，请检查输入或刷新页面后重试。'}}


def imported_policies():
    seed_ids={p['id'] for p in store.seed['policies']}
    return {'city':'杭州','policies':[p for p in store.all() if p['id'] not in seed_ids]}


def request_json(path,body_json):
    return json.dumps(request(path,json.loads(body_json)),ensure_ascii=False)
