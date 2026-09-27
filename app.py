"""Local timetable application. Account credentials live only in memory."""
import argparse
import copy
import json
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import engine
from course_data import validate_document
from export_workbook import make_workbook
from school_client import CourseClient,BatchRequired
from solver_backends import warm_backend

TITLE='北信科完全学分制自动排课'
VERSION='1.0.0'
RESOURCE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))


def atomic_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8') as handle:
            json.dump(data,handle,ensure_ascii=False,indent=2,allow_nan=False)
            handle.flush();os.fsync(handle.fileno())
        for attempt in range(4):
            try:os.replace(temporary,path);return
            except PermissionError:
                if attempt==3:raise
                time.sleep(.1)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_solution(courses,solution):
    engine.validate_solution(courses,solution)
    value=copy.deepcopy(solution);events=[]
    for course in courses:
        assignment=value['assignments'][course['id']]
        option=next((o for o in course['options'] if o['id']==assignment.get('option_id')),None)
        assignment['events']=copy.deepcopy(option['events']) if option else []
        if option:
            assignment.update(kind='option',label=option['label'])
            events.extend(dict(e,course_id=course['id'],course_code=course['code'],course_name=course['name']) for e in option['events'])
    value['events']=events;value['day_off']=engine.free_day_summary(courses,events)
    return value


class State:
    def __init__(self,data_dir,backend,client=None):
        self.path=Path(data_dir)/'planner.json'
        self.lock=threading.RLock();self.fetch_lock=threading.Lock();self.solve_lock=threading.Lock()
        self.client=client or CourseClient();self.backend=backend;self.revision=0
        self.progress='';self.batch_id=''
        self.document={'schema_version':1,'term':'','courses':[]}
        self.preferences={'weights':dict(engine.DEFAULT_WEIGHTS),'fixed':{},'allow_self_study':False}
        self.solution=None
        if self.path.exists():
            saved=json.loads(self.path.read_text(encoding='utf-8-sig'))
            self.document=validate_document(saved['document'])
            self.preferences=saved.get('state',self.preferences)
            if saved.get('solution'):self.solution=canonical_solution(self.document['courses'],saved['solution'])

    def commit(self,document,preferences,solution):
        # Replace the disk snapshot before exposing the new state to any page.
        atomic_write(self.path,{'document':document,'state':preferences,'solution':solution})
        self.document=document;self.preferences=preferences;self.solution=solution;self.revision+=1

    def payload(self):
        with self.lock:
            return copy.deepcopy(dict(courses=self.document['courses'],days=engine.DAYS,slots=engine.SLOTS,term=self.document['term'],state=self.preferences,solution=self.solution,revision=self.revision,backend=self.backend,version=VERSION))


class Server(ThreadingHTTPServer):
    allow_reuse_address=os.name!='nt'
    daemon_threads=True
    def server_bind(self):
        if os.name=='nt':self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(RESOURCE/'static'),**kwargs)
    def log_message(self,*args):pass
    @property
    def state(self):return self.server.state
    def end_headers(self):
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        super().end_headers()
    def send_json(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def local_request(self):
        host=self.headers.get('Host','')
        permitted={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        origin=self.headers.get('Origin')
        return host in permitted and (not origin or origin in {'http://'+h for h in permitted})
    def do_GET(self):
        if not self.local_request():self.send_json({'error':'仅限本机页面访问'},403);return
        path=urlsplit(self.path).path
        if path=='/api/catalog':self.send_json(self.state.payload());return
        if path=='/api/settings':
            self.send_json(dict(username=self.state.client.username,password_set=bool(self.state.client.password),batches=self.state.client.batches,batch_id=self.state.batch_id,backend=self.state.backend,progress=self.state.progress,fetching=self.state.fetch_lock.locked()));return
        if path=='/api/health':self.send_json(dict(status='ok',version=VERSION,backend=self.state.backend));return
        if path not in ('/','/index.html','/courses.html','/settings.html','/preferences.html','/app.js','/settings.js','/styles.css','/timetable.js','/export.js'):
            self.send_json({'error':'页面不存在'},404);return
        super().do_GET()
    def do_POST(self):
        if not self.local_request() or not self.headers.get('Content-Type','').startswith('application/json'):
            self.send_json({'error':'请求来源或格式无效'},403);return
        path=urlsplit(self.path).path
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=22_000_000:raise ValueError('请求大小无效')
            request=json.loads(self.rfile.read(length))
            if not isinstance(request,dict):raise ValueError('请求必须是对象')
            state=self.state
            if path=='/api/fetch':
                if not state.fetch_lock.acquire(blocking=False):self.send_json({'error':'正在获取课程安排'},409);return
                try:
                    with state.lock:revision=state.revision
                    state.client.credentials(request.get('username'),request.get('password'))
                    document=state.client.fetch_all(str(request.get('batch_id') or ''),lambda message:setattr(state,'progress',message))
                    with state.lock:
                        if revision!=state.revision:self.send_json({'error':'课表已改变，请重新获取'},409);return
                        state.commit(document,{'weights':dict(state.preferences['weights']),'fixed':{},'allow_self_study':False},None)
                        state.batch_id=str(request.get('batch_id') or '')
                    missing=[c['name'] for c in document['courses'] if not c['options']]
                    self.send_json(dict(course_count=len(document['courses']),class_count=sum(len(c['options']) for c in document['courses']),missing=missing))
                finally:state.progress='';state.fetch_lock.release()
                return
            if path=='/api/solve':
                with state.lock:
                    if request.get('revision')!=state.revision:self.send_json({'error':'课程数据已变化，请刷新页面'},409);return
                    courses=copy.deepcopy(state.document['courses']);revision=state.revision
                if not courses:raise ValueError('请先获取课程安排')
                if not state.solve_lock.acquire(blocking=False):self.send_json({'error':'正在计算，请稍后重试'},409);return
                try:solution=engine.solve(courses,request,backend=state.backend)
                finally:state.solve_lock.release()
                self.send_json(dict(solution=solution,revision=revision));return
            if path=='/api/plan':
                with state.lock:
                    if request.get('revision')!=state.revision:self.send_json({'error':'课表已更新，请刷新页面'},409);return
                    solution=canonical_solution(state.document['courses'],request['solution'])
                    prefs=request['state']
                    prefs={'weights':dict(solution['weights']),'fixed':dict(prefs.get('fixed',{})),'allow_self_study':solution['allow_self_study']}
                    state.commit(state.document,prefs,solution)
                    self.send_json(dict(revision=state.revision))
                return
            if path=='/api/export/xlsx':
                with state.lock:courses=copy.deepcopy(state.document['courses'])
                content=make_workbook(RESOURCE/'assets/export-template.xlsx',courses,request,engine.DAYS,engine.SLOTS)
                self.send_response(200);self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content);return
            self.send_json({'error':'接口不存在'},404)
        except BatchRequired as error:self.send_json({'error':str(error),'batches':error.batches},422)
        except (ValueError,KeyError,TypeError,RuntimeError,TimeoutError) as error:self.send_json({'error':str(error)},422)
        except OSError:self.send_json({'error':'本地文件保存失败，原课程和课表已保留'},500)
        except Exception:self.send_json({'error':'处理失败，原课程和课表已保留'},500)


def main(default_backend='ortools'):
    parser=argparse.ArgumentParser(description=TITLE)
    parser.add_argument('--solver',choices=['ortools','gurobi'],default=default_backend)
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--demo',action='store_true')
    args=parser.parse_args()
    default_dir=(Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent)/'data'
    state=State(args.data_dir or default_dir,args.solver)
    if args.demo and not state.document['courses']:
        state.commit(validate_document(json.loads((RESOURCE/'examples/courses.json').read_text(encoding='utf-8'))),state.preferences,None)
    warm_backend(args.solver)
    try:server=Server(('127.0.0.1',args.port),Handler)
    except OSError:
        if args.port!=8768:raise
        server=Server(('127.0.0.1',0),Handler)
    server.state=state
    url=f'http://127.0.0.1:{server.server_port}/'
    print(TITLE+' '+VERSION+' · '+args.solver+'\n'+url,flush=True)
    if not args.no_browser:
        opener=threading.Timer(.5,lambda:webbrowser.open(url));opener.daemon=True;opener.start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
