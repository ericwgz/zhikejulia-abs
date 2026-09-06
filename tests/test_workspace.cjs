const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM}=require('jsdom');
const root=require('node:path').resolve(__dirname,'../app/static/abs')+'/';
const catalog=JSON.parse(fs.readFileSync(root+'catalog.json','utf8'));
const tick=()=>new Promise(r=>setTimeout(r,10));
async function setup(configured){
 const dom=new JSDOM(fs.readFileSync(root+'index.html','utf8'),{url:'http://127.0.0.1:4317/abs/#/dashboard',runScripts:'outside-only'}),w=dom.window,requests=[],pending=[],exports=[];
 w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 w.HTMLAnchorElement.prototype.click=function(){exports.push({name:this.download,url:this.href})};w.URL.createObjectURL=()=> 'blob:local';w.URL.revokeObjectURL=()=>{};
 w.fetch=async(url,opts)=>{if(url.includes('catalog.json'))return {ok:true,json:async()=>catalog};if(url.includes('/status'))return {ok:true,json:async()=>({configured,model:configured?'test-model':''})};requests.push(JSON.parse(opts.body));return new Promise(resolve=>pending.push(resolve));};
 w.eval(fs.readFileSync(root+'scoring.js','utf8'));w.eval(fs.readFileSync(root+'workspace.js','utf8'));await tick();
 const $=s=>w.document.querySelector(s),all=s=>[...w.document.querySelectorAll(s)];
 const change=(s,v)=>{const e=$(s);e.value=v;e.dispatchEvent(new w.Event('change',{bubbles:true}))};
 const input=(s,v)=>{const e=$(s);e.value=v;e.dispatchEvent(new w.Event('input',{bubbles:true}))};
 const nav=async h=>{w.location.hash=h;await tick()};
 const send=async q=>{input('#chat-input',q);$('#chat-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick()};
 const respond=async (i,extra={})=>{pending[i]({ok:true,json:async()=>({answer:'示例分析 <img src=x onerror=alert(1)> [R1]',citations:['R1'],product_id:requests[i].product_id,snapshot_id:requests[i].snapshot_id,...extra})});await tick()};
 return{dom,w,$,all,requests,pending,exports,change,input,nav,send,respond};
}
(async()=>{
 const a=await setup(true),{$,all}=a;
 assert.equal(all('.product-card').length,6);assert.match($('.banner-total').textContent,/110\.00/);assert.deepEqual(catalog.products.map(p=>p.assessment.score),[79,86,89,53,73,91]);
 a.change('#region-filter','华南');assert.equal(all('.product-card').length,2);a.change('#segment-filter','自雇客群');assert.equal(all('.product-card').length,1);assert.match($('.product-card').textContent,/新锐/);a.change('#signal-filter','green');assert.match($('#product-grid').textContent,/没有匹配/);
 $('#reset-filters').click();assert.equal(all('.product-card').length,6);a.input('#product-search','DEMO-ABS-005');assert.equal(all('.product-card').length,1);$('#reset-filters').click();
 await a.nav('/reports');assert.equal(all('.report-center-item').length,18);
 for(const p of catalog.products){await a.nav('/product/'+p.id);assert.match($('.score-value').textContent,new RegExp('^'+p.assessment.score));assert.equal(all('[data-context]:checked').length,2);assert.match($('.context-product').textContent,new RegExp(p.id));}
 await a.nav('/product/DEMO-ABS-001/report/credit');assert.match($('.report-document').textContent,/79 分/);const frozen=$('.report-document').textContent;
 $('#context-preview').click();let ctx=JSON.parse($('#dialog-body pre').textContent);assert.equal(ctx.product.id,'DEMO-ABS-001');assert.equal(ctx.reports.length,2);assert.equal(ctx.reports[0].snapshotId,ctx.snapshotId);$('#download-context').click();assert.match(a.exports.at(-1).name,/context\.json$/);$('#dialog-close').click();
 await a.send('华东产品问题');assert.equal(a.requests.length,1);assert.equal(a.requests[0].report_ids.length,2);assert.equal(a.requests[0].messages.at(-1).content,'华东产品问题');assert.equal($('#chat-send').textContent,'停止');assert.ok(all('[data-context]').every(e=>e.disabled));
 await a.nav('/product/DEMO-ABS-004');assert.equal(all('.message').length,0);await a.respond(0);assert.equal(all('.message').length,0,'late product A response must not appear in B');
 await a.send('华南产品问题');assert.equal(a.requests[1].product_id,'DEMO-ABS-004');assert.equal(a.requests[1].messages.length,1);assert.ok(a.requests[1].report_ids.every(id=>id.startsWith('DEMO-ABS-004-')));await a.respond(1);
 await a.nav('/product/DEMO-ABS-001/report/credit');assert.equal(all('.message').length,2);assert.equal(all('.message img').length,0,'model markup must be escaped');assert.equal($('.report-document').textContent,frozen);$('[data-supplement]').click();assert.match(a.exports.at(-1).name,/DEMO-ABS-001-AI-report-supplement/);
 await a.send('继续分析');assert.equal(a.requests[2].messages.length,3);await a.respond(2,{product_id:'DEMO-ABS-004'});assert.match($('.message.error').textContent,/不匹配/);assert.equal(all('.message.assistant').length,1);
 all('[data-context]').filter(e=>e.checked).forEach(e=>{e.checked=false;e.dispatchEvent(new a.w.Event('change'))});a.input('#chat-input','问题');assert.equal($('#chat-send').disabled,true);
 await a.nav('/product/DEMO-ABS-004');assert.equal(all('[data-context]:checked').length,2,'report choices must be isolated');
 $('#method-button').click();$('#method-complete').checked=false;$('#method-complete').dispatchEvent(new a.w.Event('change'));assert.match($('.score-value').textContent,/—/);assert.match($('#stress-result').textContent,/暂停/);await a.nav('/product/DEMO-ABS-004/report/credit');assert.match($('.report-document').textContent,/53 分/,'fixed report survives temporary missing-data scenario');
 await a.nav('/product/does-not-exist');assert.match($('#main').textContent,/未找到/);a.dom.window.close();
 const b=await setup(false);await b.nav('/product/DEMO-ABS-001');b.input('#chat-input','问题');assert.equal(b.$('#chat-send').disabled,true);assert.match(b.$('.model-unavailable').textContent,/尚未配置/);assert.equal(b.requests.length,0);b.dom.window.close();
 console.log('PASS: dashboard, classification, all six scores, 18 reports, context/export, async product isolation, markup escaping, snapshot fail-closed, independent selection, immutable reports, unconfigured state.');
})().catch(e=>{console.error(e);process.exit(1)});
