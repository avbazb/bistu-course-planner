const el=id=>document.getElementById(id);
let polling=null;
let generation=0;
function batches(items,selected=''){
  el('batch').replaceChildren(new Option('自动选择当前批次',''),...items.map(b=>new Option(b.name,b.code,false,b.code===selected)));
}
async function settings(){
  const response=await fetch('/api/settings');
  if(!response.ok)throw new Error('无法读取设置');
  return response.json();
}
async function load(){
  try{
    const data=await settings();
    el('username').value=data.username;
    el('password').placeholder=data.password_set?'已设置':'';
    batches(data.batches,data.batch_id);
    el('backend').textContent=data.backend==='gurobi'?'Gurobi 版':'OR-Tools 版';
    el('fetch-status').textContent=data.progress;
  }catch(error){el('fetch-status').textContent=error.message;}
}
el('account-form').addEventListener('submit',async(event)=>{
  event.preventDefault();
  el('fetch-courses').disabled=true;
  el('fetch-status').textContent='正在获取课程安排';
  const current=++generation;
  polling=setInterval(async()=>{
    try {const data=await settings();if(current===generation && polling && data.progress)el('fetch-status').textContent=data.progress;}catch{}
  },1000);
  try{
    const response=await fetch('/api/fetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:el('username').value,password:el('password').value,batch_id:el('batch').value})});
    const result=await response.json();
    if(result.batches)batches(result.batches);
    if(!response.ok)throw new Error(result.error||'获取失败');
    el('password').value='';el('password').placeholder='已设置';
    el('fetch-status').textContent=`已获取 ${result.course_count} 门课程、${result.class_count} 个班次`+(result.missing.length?'；暂无时间安排：'+result.missing.join('、'):'');
  }catch(error){el('fetch-status').textContent=error.message;}
  finally{generation++;clearInterval(polling);polling=null;el('fetch-courses').disabled=false;}
});
load();
