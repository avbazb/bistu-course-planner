"""SSO authentication and read-only retrieval of courses already in the cart."""
import base64
import json
import secrets
import time
from urllib.parse import quote, unquote, urljoin, urlsplit
import requests
from course_data import course_from_rows, validate_document

BASE='https://xk.bistu.edu.cn/xsxk'
SSO='https://sso.bistu.edu.cn'
READ_PATHS=('/web/studentInfo','/elective/courseCart/list','/elective/clazz/cartlist')


class AuthenticationExpired(RuntimeError):pass


class BatchRequired(ValueError):
    def __init__(self,batches):
        super().__init__('请选择课程批次后再次获取')
        self.batches=batches


def encrypt_password(password,public_key):
    from gmssl import sm2,func
    # Match the captured SSO format: C1C3C2, no 04 prefix, Base64 output.
    key=base64.b64decode(public_key,validate=True)
    if len(key)==65 and key[0]==4:key=key[1:]
    if len(key)!=64:raise ValueError('身份认证公钥格式不支持')
    func.random_hex=lambda length: secrets.token_hex((length+1)//2)[:length]
    cipher=sm2.CryptSM2(private_key='',public_key=key.hex(),mode=1)
    # gmssl 3.2.2 uses lstrip("04"); restore the exact X/Y coordinates.
    cipher.public_key=key.hex()
    return base64.b64encode(cipher.encrypt(password.encode('utf-8'))).decode('ascii')


class CourseClient:
    def __init__(self,session_factory=requests.Session):
        self.session_factory=session_factory
        self.session=session_factory()
        self.username='';self.password='';self.token='';self.obtained_at=0
        self.batches=[];self.deadline=None
        self.session.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0','Accept-Language':'zh-CN,zh;q=0.9','Accept':'application/json, text/plain, */*'})

    def credentials(self,username,password):
        username=str(username or '').strip()
        if not username:raise ValueError('请输入账号')
        if username!=self.username:
            if not password:raise ValueError('请输入新账号的密码')
            self.session.cookies.clear();self.token='';self.obtained_at=0;self.batches=[]
        if password:
            if username!=self.username or password!=self.password:self.token='';self.obtained_at=0;self.batches=[]
            self.password=str(password)
        if not self.password:raise ValueError('请输入密码')
        self.username=username

    def request(self,method,url,**kwargs):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ('sso.bistu.edu.cn','xk.bistu.edu.cn') or parsed.username or parsed.password:
            raise ValueError('身份认证重定向地址无效')
        if method.upper()=='POST' and not (url==SSO+'/username-password/login' or parsed.hostname=='xk.bistu.edu.cn' and parsed.path in ['/xsxk'+p for p in READ_PATHS]):
            raise ValueError('不支持的课程服务接口')
        timeout=min(8,max(0,self.deadline-time.monotonic())) if self.deadline else 8
        if timeout<=0:raise TimeoutError('获取课程超时，原课程安排已保留')
        try:
            response=self.session.request(method,url,timeout=timeout,allow_redirects=False,**kwargs)
        except requests.RequestException:raise RuntimeError('无法连接课程服务，请检查网络后重试') from None
        if response.status_code in (401,403):raise AuthenticationExpired('登录已失效')
        if response.status_code>=400:raise RuntimeError(f'课程服务返回 HTTP {response.status_code}')
        return response

    def login(self):
        self.token='';self.obtained_at=0
        # A renewed login must not reuse an expired token or an old flowKey cookie.
        self.session.cookies.clear()
        service=BASE+'/auth/cas'
        response=self.request('GET',service)
        login_url=urljoin(service,response.headers.get('Location') or SSO+'/login?service='+quote(service,safe=''))
        for _ in range(5):
            page=self.request('GET',login_url)
            cookie=next((c.value for c in self.session.cookies if c.name=='COOKIE_INFO'),None)
            if cookie:break
            if not page.headers.get('Location'):break
            login_url=urljoin(login_url,page.headers['Location'])
        try:flow=json.loads(unquote(cookie or ''))['data']['flowKey']
        except (ValueError,KeyError,TypeError):raise RuntimeError('未取得身份认证流程信息，请稍后重试') from None
        try:public=self.request('GET',SSO+'/api/reset/rules',headers={'Referer':login_url,'X-Requested-With':'XMLHttpRequest'}).json()['data']['encrypt']['publicKey']
        except (ValueError,KeyError,TypeError):raise RuntimeError('未取得身份认证公钥') from None
        encrypted=encrypt_password(self.password,public)
        response=self.request('POST',SSO+'/username-password/login',json={'flowKey':flow,'username':self.username,'password':encrypted},headers={'Referer':login_url,'Origin':SSO,'X-Requested-With':'XMLHttpRequest'})
        try:success=response.json().get('code')==666666
        except ValueError:success=False
        if not success:raise RuntimeError('身份认证未通过，请核对账号密码；验证码或二次验证需先在学校网站完成')
        next_url=login_url
        for _ in range(8):
            response=self.request('GET',next_url)
            token=next((c.value for c in self.session.cookies if c.name=='token' and c.domain.lstrip('.')=='xk.bistu.edu.cn'),None)
            if token:
                self.token=token;self.obtained_at=time.time();self.batches=[]
                return
            location=response.headers.get('Location')
            if not location:break
            next_url=urljoin(next_url,location)
        raise RuntimeError('身份认证成功，但课程服务暂未开放或未返回有效会话')

    def read(self,path,payload,batch_id=''):
        if path not in READ_PATHS:raise ValueError('不支持的课程读取接口')
        headers={'Authorization':self.token,'Referer':BASE+'/profile/index.html','Origin':'https://xk.bistu.edu.cn'}
        if batch_id:headers['batchId']=batch_id
        kwargs={'data':{'token':self.token}} if path=='/web/studentInfo' else {'json':payload}
        response=self.request('POST',BASE+path,headers=headers,**kwargs)
        if response.status_code in (301,302,303,307,308) or 'text/html' in response.headers.get('Content-Type',''):
            raise AuthenticationExpired('登录已失效')
        try:result=response.json()
        except ValueError:raise RuntimeError('课程服务返回的数据格式无效') from None
        if str(result.get('code'))!='200':
            message=str(result.get('msg',''))
            if str(result.get('code')) in ('401','403') or any(x in message for x in ['未登录','登录失效','登录已过期','会话失效']):raise AuthenticationExpired('登录已失效')
            raise RuntimeError('课程服务暂未返回数据，请确认批次已开放')
        return result.get('data') or {}

    def fetch_all(self,batch_id='',progress=lambda message:None):
        self.deadline=time.monotonic()+180
        for attempt in range(2):
            try:
                age=time.time()-self.obtained_at
                if not self.token or not 0<=age<300:
                    progress('正在登录');self.login()
                info=self.read('/web/studentInfo',{})
                raw=info.get('student',{}).get('electiveBatchList',[])
                self.batches=[{'code':str(b.get('code','')),'name':str(b.get('name','')),'available':str(b.get('canSelect'))=='1'} for b in raw if b.get('code')]
                candidates=[b for b in self.batches if b['available']] or self.batches
                if batch_id:
                    chosen=next((b for b in self.batches if b['code']==batch_id),None)
                    if not chosen:raise BatchRequired(self.batches)
                elif len(candidates)==1:chosen=candidates[0]
                else:raise BatchRequired(self.batches)
                batch_id=chosen['code']
                progress('正在读取购物车')
                cart=self.read('/elective/courseCart/list',{},batch_id)
                rows=cart.get('rows',[]) if isinstance(cart,dict) else cart
                if not isinstance(rows,list):raise RuntimeError('购物车响应格式无效')
                if isinstance(cart,dict) and int(cart.get('total',len(rows)))>len(rows):raise RuntimeError('购物车课程未返回完整，原课程安排已保留')
                if not rows:raise ValueError('购物车为空，请先在模拟选课阶段加入课程')
                seen=set();courses=[]
                for index,item in enumerate(rows,1):
                    code=str(item.get('KCH','')).strip()
                    if not code:raise ValueError('购物车中存在缺少课程号的记录')
                    if code in seen:continue
                    seen.add(code);progress(f'正在获取 {index}/{len(rows)}：{item.get("KCM",code)}')
                    payload={'orderBy':'','pageNumber':1,'pageSize':10,'teachingClassType':str(item.get('JXBLX') or 'FANKC'),'cartCourse':code}
                    data=self.read('/elective/clazz/cartlist',payload,batch_id)
                    if not isinstance(data,dict) or not isinstance(data.get('rows'),list):raise RuntimeError('课程班次响应格式无效')
                    # The page count describes course rows; each tcList contains all classes.
                    if int(data.get('total',len(data['rows'])))>len(data['rows']):raise RuntimeError('课程班次未返回完整，原课程安排已保留')
                    courses.append(course_from_rows(item,data['rows']))
                return validate_document(dict(schema_version=1,term=chosen['name'],courses=courses))
            except AuthenticationExpired:
                self.token='';self.obtained_at=0
                if attempt:raise RuntimeError('重新登录后会话仍失效，原课程安排已保留') from None
        raise RuntimeError('无法获取课程安排')
