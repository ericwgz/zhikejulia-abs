const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'../app/static/abs');
const tick=()=>new Promise(r=>setTimeout(r,10));
const metricIds=['dpd','cdr','ccr','cpr','term','average','region','top10','shrink','wal','wac','replacement','spread','oc','dsc','reserve','residual','interest','unemployment','income','cpi','confidence','lpr','policy'];
const schema={fields:[{key:'balance',name:'资产池余额',unit:'元'}],parameters:{months:3,deterioration_pp:3,early_cpr_pct:60,shock_default_pct:35,default_accelerates:true},metrics:metricIds.map(id=>({id,name:id,unit:'%',basis:'value',op:'gt',yellow:3,red:5}))};
const ds={id:'ds-one',name:'3只样本.csv',synthetic:true,products:[{id:'SIM-1',name:'样本一',rows:180},{id:'SIM-2',name:'样本二',rows:180}],issues:[]};
function run(){return {id:'run-one',dataset_id:ds.id,product:{id:'SIM-1',name:'样本一'},created_at:'2026-09-08T00:00:00Z',synthetic:true,input_hash:'a'.repeat(64),issues:[],source_evidence:{row_count:180},assessment:{as_of:'2026-08-31',assessed:24,score:79,status:'yellow',method_version:'stress-1.0',score_method:'测试口径',notes:[],period:{},aggregates:{weighted_pd_12m:3,pd_coverage:100,duration_years:1,dpd90:1},alerts:[{}],dimensions:['loan','pool','cash','macro'].map(id=>({id,weight:.25})),metrics:schema.metrics.map((m,i)=>({...m,ref:'M'+(i+1),dimension:['loan','pool','cash','macro'][Math.floor(i/6)],value:3,previous:2,comparison:3,status:'yellow',formula:'余额 / 总余额',threshold:{source:'文档参考线',yellow:3,red:5,op:'gt',basis:'value'}}))},simulation:{ready:false,message:'待补齐压力模拟字段',missing:['a_balance'],parameters:{months:3}},ai:{status:'ready',model:'mock-model',report:{sections:['summary','quality','structure','scenarios','events','limitations'].map(id=>({id,title:id,analysis:'模型分析 <img src=x onerror=alert(1)> 不能作为网页标签执行。',evidence_refs:['M1']})),actions:[{priority:'P1',action:'复核回款',reason:'需要核对口径',trigger:'出现变化时',evidence_refs:['M1']}]}}};}
async function setup(authenticated=true){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://127.0.0.1:4317/#/stress',runScripts:'outside-only'}),w=dom.window,requests=[],exports=[];
 let team='team-a',authorized=authenticated,hold=null,pending=null;
 w.ABSWorkspace={toast:()=>{},getCatalog:()=>({products:[]})};w.scrollTo=()=>{};w.confirm=()=>true;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.URL.createObjectURL=()=> 'blob:test';w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){exports.push(this.download)};
 const response=(body,ok=true)=>({ok,json:async()=>body});
 w.fetch=async(url,opts={})=>{
  if(url.endsWith('/session'))return response({authenticated:authorized,csrf:'csrf-token',workspace:authorized?{id:team,name:team,demo:true}:null,user:{name:'栀可 Julia'}});
  if(url.endsWith('/auth/demo')){authorized=true;return response({ok:true});}
  const endpoint=url.split('/stress/')[1];const body=opts.body?JSON.parse(opts.body):undefined;requests.push({endpoint,body,headers:opts.headers});
  if(endpoint===hold)return await new Promise(resolve=>pending=resolve);
  if(endpoint==='schema')return response(schema);
  if(endpoint==='datasets')return response({datasets:team==='team-a'?[ds]:[]});
  if(endpoint==='runs')return response({runs:[]});
  if(endpoint==='demo')return response({dataset:ds});
  if(endpoint==='run')return response(run());
  if(endpoint==='runs/run-one')return response(run());
  if(endpoint==='contract')return response({message:'请核对',thresholds:{dpd:{yellow:2,red:4,source:'待人工确认',quote:'合约原文超过2%关注'}},notes:[]});
  if(endpoint==='upload')return response({message:'上传字段不正确'},false);
  throw Error('Unexpected endpoint '+endpoint);
 };
 w.eval(fs.readFileSync(path.join(root,'stress.js'),'utf8'));await tick();
 const $=s=>w.document.querySelector(s),all=s=>[...w.document.querySelectorAll(s)];
 return {dom,w,$,all,requests,exports,setTeam:v=>team=v,hold:v=>hold=v,resolve:v=>{const r=pending;pending=null;r(response(v));},response,render:()=>w.ABSStress.render()};
}
(async()=>{
 const a=await setup(false);assert.match(a.$('#main').textContent,/资产池压力测试/);a.$('#sx-enter').click();await tick();await tick();assert(a.$('#sx-file'));
 assert(a.$('#sx-run').disabled);a.$('#sx-confirm').checked=true;a.$('#sx-confirm').dispatchEvent(new a.w.Event('change'));assert(!a.$('#sx-run').disabled);
 a.$('#sx-run').click();await tick();await tick();assert.equal(a.requests.find(r=>r.endpoint==='run').headers['X-CSRF-Token'],'csrf-token');assert.equal(a.requests.find(r=>r.endpoint==='run').body.product_id,'SIM-1');
 a.$('[data-tab="metrics"]').click();assert.equal(a.all('.sx-metrics tbody tr').length,24);assert.match(a.$('.sx-score').textContent,/79/);
 a.$('[data-tab="report"]').click();assert.equal(a.all('.sx-report section').length,7);assert.equal(a.all('.sx-report img').length,0);assert.match(a.$('.sx-report').textContent,/<img src=x/);
 a.$('[data-evidence="M1"]').click();assert.match(a.$('#dialog-body').textContent,/余额/);assert(a.$('#dialog').open);
 a.$('#sx-json').click();a.$('#sx-report-export').click();assert(a.exports.some(n=>n.endsWith('.json')));assert(a.exports.some(n=>n.endsWith('.html')));
 a.$('#sx-product').value='SIM-2';a.$('#sx-product').dispatchEvent(new a.w.Event('change'));assert.equal(a.$('.sx-summary'),null);assert(a.$('#sx-run').disabled);
 a.setTeam('team-b');await a.render();assert.equal(a.$('.sx-report'),null);assert.equal(a.$('#sx-dataset').options.length,1,'new team cannot retain previous datasets');a.dom.window.close();

 const b=await setup();b.hold('demo');b.$('#sx-demo').click();await tick();assert(b.$('#sx-demo').disabled);
 b.w.location.hash='/dashboard';await tick();b.w.location.hash='/stress';await tick();await b.render();b.resolve({dataset:ds});await tick();await tick();assert(!b.$('#sx-demo').disabled,'late request must release busy after navigation');b.dom.window.close();

 const c=await setup();const file={name:'bad.csv',size:3,arrayBuffer:async()=>new Uint8Array([1,2,3]).buffer};Object.defineProperty(c.$('#sx-file'),'files',{value:[file]});c.$('#sx-file').dispatchEvent(new c.w.Event('change'));await tick();await tick();assert.match(c.$('.work-error').textContent,/上传字段不正确/);assert(!c.$('#sx-demo').disabled);c.dom.window.close();
 const d=await setup();d.w.fetch=async()=>({ok:false,json:async()=>{throw Error('upstream HTML page');}});Object.defineProperty(d.$('#sx-file'),'files',{value:[file]});d.$('#sx-file').dispatchEvent(new d.w.Event('change'));await tick();await tick();assert.match(d.$('.work-error').textContent,/服务暂时没有返回有效结果/);assert(!d.$('#sx-demo').disabled);d.dom.window.close();
 console.log('PASS: stress authentication, confirmation, CSRF, 24 metrics, immutable product selection, model escaping/evidence/export, team isolation, stale-request busy recovery, upload error state.');
})().catch(e=>{console.error(e);process.exitCode=1});
