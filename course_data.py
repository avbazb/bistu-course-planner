"""Whitelist public course fields and retain each distinct weekly meeting."""
import copy
import math
import re
import engine


def text(value):return str(value or '').strip()


def weeks_text(weeks):
    spans=[]
    for week in weeks:
        if spans and spans[-1][1]+1==week:spans[-1][1]=week
        else:spans.append([week,week])
    return '、'.join(str(a) if a==b else f'{a}-{b}' for a,b in spans)+'周'


def meeting(row):
    bits=text(row.get('SKZC'))
    if bits and re.fullmatch('[01]{1,53}',bits):
        weeks=[i+1 for i,b in enumerate(bits) if b=='1'];parity='all'
    else:weeks,parity=engine.parse_week_expression(text(row.get('SKZCMC')))
    day,start,end=int(row['SKXQ'])-1,int(row['KSJC']),int(row['JSJC'])
    if not weeks or not 0<=day<=6 or not 1<=start<=end<=14:raise ValueError('课程时间记录不完整')
    return dict(day=day,start=start,end=end,weeks=weeks,weeks_text=weeks_text(weeks),parity=parity,teacher=text(row.get('SKJS')),room=text(row.get('YPSJDD')))


def number(value):
    try:n=float(value)
    except (TypeError,ValueError):return 0
    return n if math.isfinite(n) and n>=0 else 0


def course_from_rows(cart,rows):
    code=text(cart.get('KCH'))
    if not re.fullmatch('[A-Za-z0-9_]{1,160}',code):raise ValueError('课程代码无效')
    course=dict(id=code,code=code,name=text(cart.get('KCM')) or code,credits=number(cart.get('XF')),hours=0,module='',submodule='',type='',selection_status='',options=[],option_source='课程服务')
    seen=set()
    for row in rows:
        if text(row.get('KCH'))!=code:continue
        course.update(hours=number(row.get('hours')),module=text(row.get('KCLB')))
        for item in row.get('tcList') or []:
            identifier=text(item.get('JXBID'))
            if not identifier or identifier in seen:continue
            if text(item.get('KCH')) not in ('',code):continue
            times=item.get('SKSJ') or item.get('summerScheduleWeekList') or []
            if not times:continue
            events=[meeting(t) for t in times]
            # Deduplicate exact rows only. Different weeks or periods remain separate.
            events=list({engine.event_key(e):e for e in events}.values())
            teacher=text(item.get('SKJS'))
            for event in events:event['teacher']=event['teacher'] or teacher
            seen.add(identifier)
            course['options'].append(dict(id=f'{code}-{identifier}',teaching_class_id=identifier,class_number=text(item.get('KXH')),teacher=teacher,room=text(item.get('YPSJDD')),capacity=engine.teaching_class_capacity(item),events=events,lab_unverified=str(item.get('hasTest','0'))=='1'))
    return enrich([course])[0]


def enrich(courses):
    for course in courses:
        course['option_count']=len(course['options'])
        course['availability']='available' if course['options'] else 'missing'
        for option in course['options']:
            option['label']=engine.summarize_option(option['events'])
            option['penalties']=engine.option_penalties(option['events'])
    return courses


def validate_document(document):
    if not isinstance(document,dict) or not isinstance(document.get('courses'),list):raise ValueError('课程文件格式无效')
    result=[];codes=set();option_ids=set()
    for source in document['courses']:
        code=text(source.get('code'))
        if not re.fullmatch('[A-Za-z0-9_]{1,160}',code) or code in codes or code in ('constructor','prototype','__proto__'):raise ValueError('课程代码无效或重复')
        codes.add(code)
        course={key:text(source.get(key)) for key in ('name','module','submodule','type','selection_status','option_source')}
        course.update(id=code,code=code,credits=number(source.get('credits')),hours=number(source.get('hours')),options=[])
        for raw in source.get('options',[]):
            ident=text(raw.get('id'))
            if not re.fullmatch('[A-Za-z0-9_-]{1,250}',ident) or ident in option_ids or ident in ('auto','self-study','unassigned','__proto__','constructor','prototype'):raise ValueError('教学班 ID 无效或重复')
            option_ids.add(ident)
            option={k:text(raw.get(k)) for k in ('teaching_class_id','class_number','teacher','room')}
            option.update(id=ident,capacity=raw.get('capacity'),lab_unverified=bool(raw.get('lab_unverified')),events=[])
            if option['capacity'] is not None and (type(option['capacity']) is not int or not 0<=option['capacity']<=1000000):raise ValueError('容量格式错误')
            for old in raw.get('events',[]):
                event={k:text(old.get(k)) for k in ('teacher','room')}
                weeks=old.get('weeks',[])
                if not weeks or any(type(w) is not int or not 1<=w<=53 for w in weeks) or weeks!=sorted(set(weeks)):raise ValueError('课程周次无效')
                for k,lo,hi in [('day',0,6),('start',1,14),('end',1,14)]:
                    n=old.get(k)
                    if type(n) is not int or not lo<=n<=hi:raise ValueError('课程节次无效')
                    event[k]=n
                if event['start']>event['end']:raise ValueError('课程节次顺序错误')
                event.update(weeks=copy.copy(weeks),weeks_text=weeks_text(weeks),parity='all')
                option['events'].append(event)
            if not option['events']:raise ValueError('教学班缺少课程时间')
            course['options'].append(option)
        result.append(course)
    return dict(schema_version=1,term=text(document.get('term')),courses=enrich(result))
