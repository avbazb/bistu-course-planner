import copy
import base64
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from xml.etree import ElementTree as ET
from urllib.parse import quote
from pathlib import Path
from unittest.mock import patch

import requests
import app
import engine
from course_data import course_from_rows, meeting, validate_document
from school_client import AuthenticationExpired, BatchRequired, CourseClient, BASE, SSO, encrypt_password
from solver_backends import warm_backend

ROOT=Path(__file__).resolve().parents[1]


def document():
    return validate_document(json.loads((ROOT/'examples/courses.json').read_text(encoding='utf-8')))


def make_course(code,choices):
    return dict(code=code,name=code,options=[dict(id=f'{code}-{i}',teacher='示例教师',events=[dict(day=d,start=s,end=e,weeks=w,teacher='示例教师',room='示例教室') for d,s,e,w in meetings]) for i,meetings in enumerate(choices)])


def catalog(*courses):return validate_document({'courses':list(courses)})['courses']


class SolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warm_backend('ortools')
        cls.backends=['ortools']+(['gurobi'] if shutil.which('gurobi_cl') else [])

    def solve_each(self,courses,request):
        return [engine.solve(courses,request,backend=b) for b in self.backends]

    def test_backends_demo_and_canonical_events(self):
        results=self.solve_each(document()['courses'],{})
        for result in results:
            self.assertEqual(result['scheduled_count'],3)
            self.assertFalse(result['allow_self_study'])
            engine.validate_solution(document()['courses'],result)
        self.assertEqual(len({r['objective'] for r in results}),1)

    def test_weeks_and_short_last_meeting_not_merged(self):
        courses=catalog(make_course('A',[[(0,11,13,[4,5]),(0,11,12,[6])]]),make_course('B',[[(0,13,14,[6])]]))
        for result in self.solve_each(courses,{}):self.assertEqual(result['scheduled_count'],2)
        courses[1]['options'][0]['events'][0]['weeks']=[5]
        for backend in self.backends:
            with self.assertRaises(ValueError):engine.solve(courses,{},backend=backend)

    def test_free_days_only_weekdays(self):
        courses=catalog(make_course('A',[[(0,3,4,[1,2])]]),make_course('B',[[(1,6,7,[1,2])],[(0,6,7,[1,2])]]))
        request={'weights':{k:(10 if k=='freeDays' else 0) for k in engine.DEFAULT_WEIGHTS}}
        for result in self.solve_each(courses,request):
            self.assertEqual(result['assignments']['B']['option_id'],'B-1')
            self.assertEqual(result['day_off']['weekday_occupied'],2)

    def test_self_study_requires_every_class_blocked(self):
        courses=catalog(make_course('A',[[(0,1,2,[1])]]),make_course('B',[[(0,1,2,[1])],[(1,1,2,[1])]]))
        for backend in self.backends:
            with self.assertRaises(ValueError):engine.solve(courses,{'allow_self_study':True,'fixed':{'B':'self-study'}},backend=backend)
        courses[1]['options'].pop()
        for result in self.solve_each(courses,{'allow_self_study':True,'fixed':{'B':'self-study'}}):
            self.assertEqual(result['self_study_count'],1)

    def test_unknown_fixed_weight_and_nan(self):
        for request in [{'fixed':{'UNKNOWN':'x'}},{'weights':{'early8':float('nan')}},{'allow_self_study':'false'}]:
            with self.assertRaises(ValueError):engine.solve(document()['courses'],request)

    def test_validator_rejects_forged_assignment_and_missing_course(self):
        courses=document()['courses'];result=self.solve_each(courses,{})[0]
        result['assignments'][courses[0]['id']]['kind']='unassigned'
        with self.assertRaises(ValueError):app.canonical_solution(courses,result)
        result['assignments'].pop(courses[0]['id'])
        with self.assertRaises(ValueError):app.canonical_solution(courses,result)


class ParsingTests(unittest.TestCase):
    def test_mask_is_authoritative_and_last_week_distinct(self):
        row={'SKZC':'00011','SKZCMC':'4-9周','SKXQ':'1','KSJC':'11','JSJC':'13','SKJS':'示例教师','YPSJDD':'教室'}
        self.assertEqual(meeting(row)['weeks'],[4,5])
        self.assertEqual(meeting(row)['weeks_text'],'4-5周')
        item={'JXBID':'class1','KCH':'A','SKJS':'示例教师','hasTest':'1','SKSJ':[row,dict(row,SKZC='000001',JSJC='12')]}
        course=course_from_rows({'KCH':'A','KCM':'示例课程'},[{'KCH':'A','tcList':[item]}])
        self.assertEqual(len(course['options'][0]['events']),2)
        self.assertTrue(course['options'][0]['lab_unverified'])

    def test_private_fields_stripped(self):
        source=document();source['token']='not-real';source['courses'][0]['secretVal']='private'
        source['courses'][0]['options'][0].update(gender='private',title='private',staffId='private')
        serialized=json.dumps(validate_document(source))
        for forbidden in ['token','secretVal','gender','staffId','private']:self.assertNotIn(forbidden,serialized)

    def test_bad_times_rejected(self):
        row={'SKZC':'0','SKXQ':'1','KSJC':'1','JSJC':'2'}
        with self.assertRaises(ValueError):meeting(row)


class FakeClient(CourseClient):
    def __init__(self):
        super().__init__();self.logins=0;self.calls=[];self.fail_once=False;self.always_expired=False;self.fail_course=False;self.multiple=False
        self.credentials('demo-user','demo-password')
    def login(self):
        self.logins+=1;self.token='test-token';self.obtained_at=time.time()
    def read(self,path,payload,batch_id=''):
        self.calls.append((path,copy.deepcopy(payload),batch_id))
        if self.fail_once or self.always_expired:
            self.fail_once=False;raise AuthenticationExpired()
        if path=='/web/studentInfo':
            batches=[{'code':'demo','name':'演示批次','canSelect':'1'}]
            if self.multiple:batches.append(dict(batches[0],code='another'))
            return {'student':{'electiveBatchList':batches}}
        if path=='/elective/courseCart/list':return {'total':2,'rows':[{'KCH':c,'KCM':c,'JXBLX':'FANKC'} for c in ['A','B']]}
        if self.fail_course and payload['cartCourse']=='B':raise RuntimeError('模拟网络错误')
        code=payload['cartCourse']
        return {'total':1,'rows':[{'KCH':code,'tcList':[{'JXBID':str(i),'KCH':code,'SKJS':'示例教师','SKSJ':[{'SKZC':'11','SKXQ':'1' if code=='A' else '2','KSJC':'3','JSJC':'4'}]} for i in range(25)]}]}


class ClientTests(unittest.TestCase):
    def test_sso_flow_removes_stale_cookies_and_sm2_roundtrip(self):
        from gmssl import sm2
        private='1'.zfill(64)
        cipher=sm2.CryptSM2(private_key=private,public_key='',mode=1)
        public=cipher._kg(int(private,16),sm2.default_ecc_table['g'])
        cipher.public_key=public
        encoded=base64.b64encode(bytes.fromhex('04'+public)).decode()
        encrypted=encrypt_password('演示密码',encoded)
        self.assertEqual(cipher.decrypt(base64.b64decode(encrypted)).decode(),'演示密码')
        client=CourseClient();client.credentials('demo-user','demo-password')
        client.session.cookies.set('COOKIE_INFO','old-flow',domain='sso.bistu.edu.cn')
        client.session.cookies.set('token','old-token',domain='xk.bistu.edu.cn')
        calls=[]
        def reply(method,url,**kwargs):
            calls.append((method,url))
            result=requests.Response();result.status_code=200;result._content=b'{}'
            if url==BASE+'/auth/cas':
                self.assertEqual(len(client.session.cookies),0)
                result.status_code=302;result.headers['Location']=SSO+'/login?demo=1'
            elif url==SSO+'/login?demo=1':
                if not any(c[0]=='POST' for c in calls):
                    client.session.cookies.set('COOKIE_INFO',quote(json.dumps({'data':{'flowKey':'fresh-flow'}})),domain='sso.bistu.edu.cn')
                else:result.status_code=302;result.headers['Location']=BASE+'/auth/cas?ticket=demo-ticket'
            elif url==SSO+'/api/reset/rules':result._content=json.dumps({'data':{'encrypt':{'publicKey':encoded}}}).encode()
            elif url==SSO+'/username-password/login':
                self.assertEqual(kwargs['json']['flowKey'],'fresh-flow')
                self.assertEqual(cipher.decrypt(base64.b64decode(kwargs['json']['password'])).decode(),'demo-password')
                result._content=b'{"code":666666}'
            elif url==BASE+'/auth/cas?ticket=demo-ticket':client.session.cookies.set('token','new-token',domain='xk.bistu.edu.cn')
            else:raise AssertionError('Unexpected offline request')
            self.assertFalse(kwargs['allow_redirects'])
            return result
        with patch.object(client.session,'request',side_effect=reply):client.login()
        self.assertEqual(client.token,'new-token')
        self.assertEqual(len(calls),6)

    def test_cart_all_classes_not_limited_to_page_size(self):
        client=FakeClient();result=client.fetch_all()
        self.assertEqual(len(result['courses']),2)
        self.assertEqual(sum(len(c['options']) for c in result['courses']),50)
        self.assertEqual(len(client.calls),4)
        self.assertEqual(client.calls[-1][1],{'orderBy':'','pageNumber':1,'pageSize':10,'teachingClassType':'FANKC','cartCourse':'B'})

    def test_token_reuse_expiry_and_single_retry(self):
        client=FakeClient();client.fetch_all();client.fetch_all();self.assertEqual(client.logins,1)
        client.obtained_at=time.time()-301;client.fetch_all();self.assertEqual(client.logins,2)
        client.fail_once=True;client.fetch_all();self.assertEqual(client.logins,3)
        client.always_expired=True
        with self.assertRaises(RuntimeError):client.fetch_all()
        self.assertEqual(client.logins,4)

    def test_batch_requires_user_choice(self):
        client=FakeClient();client.multiple=True
        with self.assertRaises(BatchRequired):client.fetch_all()
        self.assertEqual(len(client.calls),1)
        self.assertEqual(len(client.fetch_all('another')['courses']),2)

    def test_request_allowlist_and_partial_failure(self):
        client=FakeClient()
        with patch.object(client.session,'request',side_effect=AssertionError('unexpected network')):
            for method,url in [('POST',BASE+'/unsupported'),('GET','https://example.com/')]:
                with self.assertRaises(ValueError):client.request(method,url)
        client.fail_course=True
        with self.assertRaises(RuntimeError):client.fetch_all()

    def test_password_not_reused_for_other_account(self):
        client=FakeClient()
        with self.assertRaises(ValueError):client.credentials('other','')
        client.credentials('demo-user','');self.assertEqual(client.password,'demo-password')


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):warm_backend('ortools')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.client=FakeClient()
        self.state=app.State(self.temp.name,'ortools',self.client)
        self.state.commit(document(),self.state.preferences,None)
        self.server=app.Server(('127.0.0.1',0),app.Handler);self.server.state=self.state
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.http=requests.Session();self.http.trust_env=False
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.http.close();self.temp.cleanup()
    def post(self,path,body):return self.http.post(self.url+path,json=body,timeout=4)

    def test_solve_save_restart_and_revision(self):
        result=self.post('/api/solve',{'revision':self.state.revision}).json()
        result['state']=self.state.preferences
        response=self.post('/api/plan',result);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.post('/api/plan',result).status_code,409)
        saved=app.State(self.temp.name,'ortools')
        self.assertEqual(saved.solution['scheduled_count'],3)
        contents=self.state.path.read_text(encoding='utf-8')
        self.assertNotIn('demo-password',contents);self.assertNotIn('demo-user',contents)

    def test_slow_solver_finishes_and_does_not_block_page_reads(self):
        from ortools.sat.python import cp_model
        original_solve=cp_model.CpSolver.solve
        started=threading.Event()
        def slow_solve(solver,*args,**kwargs):
            started.set()
            time.sleep(1.2)
            return original_solve(solver,*args,**kwargs)
        responses=[]
        request=threading.Thread(target=lambda:responses.append(self.post('/api/solve',{'revision':self.state.revision})))
        with patch.object(cp_model.CpSolver,'solve',slow_solve):
            request.start()
            self.assertTrue(started.wait(2))
            # Other page requests remain available while the solver is still running.
            health=self.http.get(self.url+'/api/health',timeout=1)
            self.assertEqual(health.status_code,200)
            self.assertTrue(request.is_alive())
            request.join(4)
        self.assertFalse(request.is_alive())
        self.assertEqual(len(responses),1)
        self.assertEqual(responses[0].status_code,200,responses[0].text)
        solution=responses[0].json()['solution']
        self.assertEqual(solution['scheduled_count'],3)
        self.assertGreaterEqual(solution['elapsed_ms'],1200)

    def test_failed_fetch_and_disk_error_keep_old_snapshot(self):
        before=self.state.path.read_bytes();revision=self.state.revision
        self.client.fail_course=True
        response=self.post('/api/fetch',{'username':'demo-user'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(before,self.state.path.read_bytes());self.assertEqual(revision,self.state.revision)
        self.client.fail_course=False
        with patch('app.atomic_write',side_effect=PermissionError()):
            self.assertEqual(self.post('/api/fetch',{'username':'demo-user'}).status_code,500)
        self.assertEqual(before,self.state.path.read_bytes());self.assertEqual(revision,self.state.revision)

    def test_fetch_success_and_settings_redact_password(self):
        result=self.post('/api/fetch',{'username':'demo-user'}).json()
        self.assertEqual(result['class_count'],50)
        self.assertEqual(len(self.state.document['courses']),2)
        settings=self.http.get(self.url+'/api/settings',timeout=4).json()
        self.assertTrue(settings['password_set']);self.assertNotIn('password',settings);self.assertNotIn('token',settings)

    def test_cross_origin_and_static_allowlist(self):
        self.assertEqual(self.http.post(self.url+'/api/fetch',json={},headers={'Origin':'https://example.com'},timeout=4).status_code,403)
        self.assertEqual(self.http.get(self.url+'/api/catalog',headers={'Host':'example.com'},timeout=4).status_code,403)
        self.assertEqual(self.http.get(self.url+'/app.py',timeout=4).status_code,404)
        self.assertEqual(self.http.get(self.url+'/settings.html',timeout=4).status_code,200)

    def test_export_contains_all_meetings_and_only_teacher_name(self):
        result=self.post('/api/solve',{'revision':self.state.revision}).json()['solution']
        image='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6D1cAAAAASUVORK5CYII='
        # Generate an actual CRC-valid minimal PNG, independently of the exporter.
        import struct,zlib
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\xff\xff\xff'))+chunk(b'IEND',b'')
        response=self.post('/api/export/xlsx',{'week':0,'image':base64.b64encode(png).decode(),'assignments':{k:v['option_id'] for k,v in result['assignments'].items()}})
        self.assertEqual(response.status_code,200,response.text[:200] if response.status_code!=200 else '')
        with zipfile.ZipFile(io.BytesIO(response.content)) as workbook:
            xml=workbook.read('xl/worksheets/sheet2.xml').decode()
            self.assertIn('演示教师',xml);self.assertNotIn('性别',xml);self.assertNotIn('职称',xml)
            root=ET.fromstring(xml);ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            rows=root.findall('m:sheetData/m:row',ns)
            self.assertEqual(sum(int(r.get('r'))>=5 for r in rows),len(result['events']))


if __name__=='__main__':unittest.main()
