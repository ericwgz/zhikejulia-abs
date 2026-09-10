const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'../app/static/abs');
const tick=()=>new Promise(r=>setTimeout(r,10));
const metricIds=['dpd','cdr','ccr','cpr','term','average','region','top10','shrink','wal','wac','replacement','spread','oc','dsc','reserve','residual','interest','unemployment','income','cpi','confidence','lpr','policy'];
const schema={fields:[{key:'balance',name:'资产池余额',unit:'元'}],parameters:{months:3,deterioration_pp:3,early_cpr_pct:60,shock_default_pct:35,default_accelerates:true},metrics:metricIds.map(id=>({id,name:id,unit:'%',basis:'value',op:'gt',yellow:3,red:5}))};
const ds={id:'ds-one',name:'3只样本.csv',synthetic:true,products:[{id:'SIM-1',name:'样本一',rows:180},{id:'SIM-2',name:'样本二',rows:180}],issues:[]};
function run(){return {id:'run-one',dataset_id:ds.id,dataset_name:'本次 <img src=x> 资产池.csv',product:{id:'SIM-1',name:'样本一'},created_at:'2026-09-08T00:00:00Z',synthetic:true,input_hash:'a'.repeat(64),issues:[],source_evidence:{row_count:180},assessment:{as_of:'2026-08-31',assessed:24,score:79,status:'yellow',method_version:'stress-1.0',score_method:'测试口径',notes:[],period:{},aggregates:{weighted_pd_12m:3,pd_coverage:100,duration_years:1,dpd90:1},alerts:[{}],dimensions:['loan','pool','cash','macro'].map(id=>({id,weight:.25})),metrics:schema.metrics.map((m,i)=>({...m,ref:'M'+(i+1),dimension:['loan','pool','cash','macro'][Math.floor(i/6)],value:3,previous:2,comparison:3,status:'yellow',formula:'余额 / 总余额',threshold:{source:'文档参考线',yellow:3,red:5,op:'gt',basis:'value'}}))},simulation:{ready:false,message:'待补齐压力模拟字段',missing:['a_balance'],parameters:{months:3}},ai:{status:'ready',model:'mock-model',report:{sections:['summary','quality','structure','scenarios','events','limitations'].map(id=>({id,title:id,analysis:'模型分析 <img src=x onerror=alert(1)> 不能作为网页标签执行。',evidence_refs:['M1']})),actions:[{priority:'P1',action:'复核回款',reason:'需要核对口径',trigger:'出现变化时',evidence_refs:['M1']}]}}};}
async function setup(authenticated=true,options={}){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://127.0.0.1:4317/#/stress',runScripts:'outside-only'}),w=dom.window,requests=[],exports=[],created=[],revoked=[],timeouts=[];
 let team='team-a',authorized=authenticated,hold=null,pending=null;
 w.ABSWorkspace={toast:()=>{},getCatalog:()=>({products:[]})};w.scrollTo=()=>{};w.confirm=()=>true;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.URL.createObjectURL=file=>{const url='blob:test-'+(created.length+1);created.push({file,url});return url};w.URL.revokeObjectURL=url=>revoked.push(url);w.HTMLAnchorElement.prototype.click=function(){exports.push(this.download)};
 const schedule=w.setTimeout.bind(w);w.setTimeout=(fn,delay,...args)=>{if(delay===340000&&options.controlTimeout){timeouts.push(fn);return schedule(()=>{},delay);}return schedule(fn,delay===2000?1:delay,...args);};
 const response=(body,ok=true)=>({ok,json:async()=>body});
 w.fetch=async(url,opts={})=>{
  if(url.endsWith('/session'))return response({authenticated:authorized,csrf:'csrf-token',workspace:authorized?{id:team,name:team,demo:true}:null,user:{name:'栀可 Julia'}});
  if(url.endsWith('/auth/demo')){authorized=true;return response({ok:true});}
  const endpoint=url.split('/stress/')[1];const body=opts.body?JSON.parse(opts.body):undefined;requests.push({endpoint,body,headers:opts.headers});
  if(endpoint===hold)return await new Promise(resolve=>pending=resolve);
  if(options.respond){const answer=await options.respond(endpoint,body,opts);if(answer!==undefined)return answer;}
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
 return {dom,w,$,all,requests,exports,created,revoked,timeouts,setTeam:v=>team=v,hold:v=>hold=v,resolve:v=>{const r=pending;pending=null;r(response(v));},response,render:()=>w.ABSStress.render()};
}
const reply=body=>({ok:true,json:async()=>body});
const pdfResult=()=>({input_type:'pdf',model:'qwen3.8-max',requires_confirmation:true,message:'核对原PDF后应用',thresholds:{dpd:{yellow:2,red:4,quote:'识别摘录 <img src=x onerror=alert(1)> 超过2%关注',source:'PDF 第2页 · AI识别，待人工确认'}},citations:{dpd:{page:2,kind:'ai_recognized'}},notes:['页码 <script>bad()</script> 需要核对']});
function selectFile(a,name,size=24,target='#sx-contract-file'){const f={name,size,arrayBuffer:async()=>new Uint8Array(Math.min(size,24)).buffer};Object.defineProperty(a.$(target),'files',{value:[f],configurable:true});a.$(target).dispatchEvent(new a.w.Event('change'));return f;}
async function settle(predicate,label){for(let i=0;i<80;i++){if(predicate())return;await tick();}assert.fail('Timed out: '+label);}
(async()=>{
 const a=await setup(false);assert.match(a.$('#main').textContent,/资产池压力测试/);a.$('#sx-enter').click();await tick();await tick();assert(a.$('#sx-file'));
 assert(a.$('#sx-run').disabled);a.$('#sx-confirm').checked=true;a.$('#sx-confirm').dispatchEvent(new a.w.Event('change'));assert(!a.$('#sx-run').disabled);
 a.$('#sx-run').click();await tick();await tick();assert.equal(a.requests.find(r=>r.endpoint==='run').headers['X-CSRF-Token'],'csrf-token');assert.equal(a.requests.find(r=>r.endpoint==='run').body.product_id,'SIM-1');
 a.$('[data-tab="metrics"]').click();assert.equal(a.all('.sx-metrics tbody tr').length,24);assert.match(a.$('.sx-score').textContent,/79/);
 a.$('[data-tab="report"]').click();assert.equal(a.all('.sx-report section').length,7);assert.equal(a.all('.sx-report img').length,0);assert.match(a.$('.sx-report-source').textContent,/本次 <img src=x> 资产池.csv/);assert.match(a.$('.sx-report').textContent,/<img src=x/);
 a.$('[data-evidence="M1"]').click();assert.match(a.$('#dialog-body').textContent,/余额/);assert(a.$('#dialog').open);
 a.$('#sx-json').click();a.$('#sx-report-export').click();assert(a.exports.some(n=>n.endsWith('.json')));assert(a.exports.some(n=>n.endsWith('.html')));
 a.$('#sx-product').value='SIM-2';a.$('#sx-product').dispatchEvent(new a.w.Event('change'));assert.equal(a.$('.sx-summary'),null);assert(a.$('#sx-run').disabled);
 a.setTeam('team-b');await a.render();assert.equal(a.$('.sx-report'),null);assert.equal(a.$('#sx-dataset').options.length,1,'new team cannot retain previous datasets');a.dom.window.close();

 const b=await setup();b.hold('demo');b.$('#sx-demo').click();await tick();assert(b.$('#sx-demo').disabled);
 b.w.location.hash='/dashboard';await tick();b.w.location.hash='/stress';await tick();await b.render();b.resolve({dataset:ds});await tick();await tick();assert(!b.$('#sx-demo').disabled,'late request must release busy after navigation');b.dom.window.close();

 const c=await setup();const file={name:'bad.csv',size:3,arrayBuffer:async()=>new Uint8Array([1,2,3]).buffer};Object.defineProperty(c.$('#sx-file'),'files',{value:[file]});c.$('#sx-file').dispatchEvent(new c.w.Event('change'));await tick();await tick();assert.match(c.$('.work-error').textContent,/上传字段不正确/);assert(!c.$('#sx-demo').disabled);c.dom.window.close();
 const d=await setup();d.w.fetch=async()=>({ok:false,json:async()=>{throw Error('upstream HTML page');}});Object.defineProperty(d.$('#sx-file'),'files',{value:[file]});d.$('#sx-file').dispatchEvent(new d.w.Event('change'));await tick();await tick();assert.match(d.$('.work-error').textContent,/服务暂时没有返回有效结果/);assert(!d.$('#sx-demo').disabled);d.dom.window.close();

 const txt=await setup();assert.equal(txt.$('#sx-contract-file').accept,'.pdf,.docx,.txt');selectFile(txt,'合约.txt');await settle(()=>txt.$('#sx-contract-apply'),'synchronous TXT contract');assert.equal(txt.requests.filter(r=>r.endpoint.startsWith('contracts/')).length,0);assert.equal(txt.$('[data-threshold="dpd"][data-level="yellow"]').value,'3','TXT extraction requires manual apply');txt.$('#sx-contract-apply').click();assert.equal(txt.$('[data-threshold="dpd"][data-level="yellow"]').value,'2');txt.dom.window.close();

 let polls=0;const pdf=await setup(true,{respond:async endpoint=>endpoint==='contract'?reply({id:'contract-one',status:'pending'}):endpoint==='contracts/contract-one'?reply(++polls===1?{id:'contract-one',status:'pending'}:{id:'contract-one',status:'ready',result:pdfResult()}):undefined});
 selectFile(pdf,'扫描合约.PDF',5000000);await settle(()=>pdf.$('#sx-contract-apply'),'PDF polling ready');assert.equal(polls,2);assert.equal(pdf.requests.find(r=>r.endpoint==='contract').headers['X-CSRF-Token'],'csrf-token');assert.equal(pdf.requests.find(r=>r.endpoint==='contracts/contract-one').body,undefined);assert.equal(pdf.$('[data-threshold="dpd"][data-level="yellow"]').value,'3','PDF extraction must not auto-apply');assert(pdf.$('#sx-contract-section').open);assert.equal(pdf.all('.sx-contract-preview img,.sx-contract-preview script').length,0);assert.match(pdf.$('.sx-contract-preview').textContent,/<img src=x/);assert.match(pdf.$('.sx-contract-preview').textContent,/AI识别/);assert.match(pdf.$('.sx-contract-preview').textContent,/第 2 页/);assert.match(pdf.$('.sx-contract-preview').textContent,/qwen3.8-max/);assert.equal(pdf.$('.sx-contract-original').getAttribute('href'),'blob:test-1#page=2');assert.equal(pdf.$('.sx-contract-original').target,'_blank');assert.equal(pdf.$('.sx-contract-original').rel,'noopener');assert.equal(pdf.w.localStorage.length,0);
 pdf.$('#sx-contract-apply').click();assert.equal(pdf.$('.sx-contract-preview'),null);assert.deepEqual(pdf.revoked,['blob:test-1']);assert.equal(pdf.$('[data-threshold="dpd"][data-level="yellow"]').value,'2');assert(pdf.$('#sx-run').disabled);pdf.$('#sx-confirm').checked=true;pdf.$('#sx-confirm').dispatchEvent(new pdf.w.Event('change'));pdf.$('#sx-run').click();await settle(()=>pdf.requests.some(r=>r.endpoint==='run'),'run with confirmed PDF thresholds');const override=pdf.requests.find(r=>r.endpoint==='run').body.thresholds.dpd;assert.deepEqual(Object.keys(override).sort(),['quote','red','source','yellow']);assert.match(override.source,/PDF 第2页/);assert.match(override.source,/AI识别摘录.*已由用户核对/);assert.match(override.quote,/<img src=x/);await settle(()=>!pdf.$('#sx-demo').disabled,'PDF run completion');pdf.dom.window.close();

 const limits=await setup();selectFile(limits,'oversized.pdf',5000001);await settle(()=>limits.$('.work-error'),'PDF limit');assert.match(limits.$('.work-error').textContent,/超过5 MB/);assert.equal(limits.requests.filter(r=>r.endpoint==='contract').length,0);selectFile(limits,'oversized.docx',700001);await settle(()=>limits.$('.work-error'),'DOCX limit');assert.match(limits.$('.work-error').textContent,/DOCX\/TXT超过700 KB/);selectFile(limits,'oversized.txt',700001);await settle(()=>limits.$('.work-error'),'TXT limit');assert.match(limits.$('.work-error').textContent,/DOCX\/TXT超过700 KB/);selectFile(limits,'data.csv',700001,'#sx-file');await settle(()=>limits.$('.work-error'),'data limit unchanged');assert.match(limits.$('.work-error').textContent,/700 KB/);selectFile(limits,'data.pdf',500,'#sx-file');await settle(()=>limits.$('.work-error'),'PDF routed to contract input');assert.match(limits.$('.work-error').textContent,/合约阈值/);assert.equal(limits.requests.filter(r=>r.endpoint==='upload').length,0);selectFile(limits,'wrong.html',500);await settle(()=>limits.$('.work-error'),'unsupported contract type');assert.match(limits.$('.work-error').textContent,/仅支持 PDF/);assert.equal(limits.created.length,0);limits.dom.window.close();

 const failed=await setup(true,{respond:async endpoint=>endpoint==='contract'?reply({id:'contract-fail',status:'pending'}):endpoint==='contracts/contract-fail'?reply({id:'contract-fail',status:'failed',message:'PDF无法读取，请解除文件加密后重新上传。'}):undefined});selectFile(failed,'encrypted.pdf');await settle(()=>failed.$('.work-error'),'failed PDF job');assert.match(failed.$('.work-error').textContent,/解除文件加密/);assert.equal(failed.$('#sx-contract-apply'),null);assert(!failed.$('#sx-contract-file').disabled);assert.deepEqual(failed.revoked,['blob:test-1']);failed.dom.window.close();

 for(const change of ['team','product','dataset','navigation','cancel']){
  const stale=await setup(true,{respond:async endpoint=>endpoint==='contract'?reply({id:'contract-stale',status:'pending'}):undefined});stale.hold('contracts/contract-stale');selectFile(stale,'待完成.pdf',800000);await settle(()=>stale.requests.some(r=>r.endpoint==='contracts/contract-stale'),'pending PDF before '+change);assert(stale.$('#sx-contract-file').disabled);assert(stale.$('[data-threshold="dpd"]').disabled);assert(stale.$('#sx-months').disabled);assert(!stale.$('#sx-contract-cancel').disabled);
  if(change==='team'){stale.setTeam('team-b');await stale.render();}
  if(change==='product'){stale.$('#sx-product').value='SIM-2';stale.$('#sx-product').dispatchEvent(new stale.w.Event('change'));}
  if(change==='dataset'){stale.$('#sx-dataset').value='';stale.$('#sx-dataset').dispatchEvent(new stale.w.Event('change'));}
  if(change==='navigation'){stale.w.location.hash='/dashboard';await tick();stale.w.location.hash='/stress';await tick();await stale.render();}
  if(change==='cancel')stale.$('#sx-contract-cancel').click();
  assert.deepEqual(stale.revoked,['blob:test-1'],change+' must revoke local PDF');stale.resolve({id:'contract-stale',status:'ready',result:pdfResult()});await tick();await tick();assert.equal(stale.$('#sx-contract-apply'),null,change+' must ignore stale result');assert(!stale.$('#sx-contract-file').disabled,change+' must release busy state');assert.equal(stale.$('[data-threshold="dpd"][data-level="yellow"]').value,'3');stale.dom.window.close();
 }

 const cleared=await setup(true,{respond:async endpoint=>endpoint==='contract'?reply({id:'contract-clear',status:'pending'}):endpoint==='contracts/contract-clear'?reply({id:'contract-clear',status:'ready',result:pdfResult()}):undefined});selectFile(cleared,'原文.pdf');await settle(()=>cleared.$('#sx-contract-clear'),'clear ready PDF');cleared.$('#sx-contract-clear').click();assert.equal(cleared.$('.sx-contract-preview'),null);assert.deepEqual(cleared.revoked,['blob:test-1']);assert.equal(cleared.$('[data-threshold="dpd"][data-level="yellow"]').value,'3');cleared.dom.window.close();

 const empty=await setup(true,{respond:async endpoint=>endpoint==='contract'?reply({id:'contract-empty',status:'pending'}):endpoint==='contracts/contract-empty'?reply({id:'contract-empty',status:'ready',result:{...pdfResult(),thresholds:{},citations:{}}}):undefined});selectFile(empty,'无匹配条款.pdf');await settle(()=>empty.$('#sx-contract-clear'),'empty extraction');assert(empty.$('#sx-contract-apply').disabled);assert.match(empty.$('.sx-contract-preview').textContent,/没有提取到可直接匹配/);assert(!empty.$('#sx-contract-file').disabled);empty.$('#sx-contract-clear').click();assert.deepEqual(empty.revoked,['blob:test-1']);empty.dom.window.close();

 const timeout=await setup(true,{controlTimeout:true,respond:async(endpoint,body,opts)=>endpoint==='contract'?reply({id:'contract-timeout',status:'pending'}):endpoint==='contracts/contract-timeout'?new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true})):undefined});selectFile(timeout,'超时.pdf');await settle(()=>timeout.requests.some(r=>r.endpoint==='contracts/contract-timeout'),'poll request before timeout');timeout.timeouts[0]();await settle(()=>timeout.$('.work-error'),'PDF timeout');assert.match(timeout.$('.work-error').textContent,/等待超时.*重新上传/);assert(!timeout.$('#sx-contract-file').disabled);assert.deepEqual(timeout.revoked,['blob:test-1']);timeout.dom.window.close();
 console.log('PASS: stress auth/CSRF, 24 metrics/report escaping, team isolation, TXT/PDF contract upload limits, pending/ready/failed/timeout/cancel, stale team/product/dataset/navigation results, PDF page links and URL cleanup, human confirmation with source provenance.');
})().catch(e=>{console.error(e);process.exitCode=1});
