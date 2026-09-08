const assert=require('node:assert/strict'),crypto=require('node:crypto'),cp=require('node:child_process'),path=require('node:path');
const root=path.resolve(__dirname,'..'),commit=process.argv[2]||cp.execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
if(!/^[0-9a-f]{40}$/.test(commit))throw Error('Expected a full Git commit SHA');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
(async()=>{
 for(const endpoint of ['health','status']){
  const response=await fetch('https://zhikejulia.com/api/abs/'+endpoint,{signal:AbortSignal.timeout(20000)});assert.equal(response.status,200);
  const result=await response.json();if(endpoint==='health'){assert.equal(result.ok,true);assert.equal(result.catalogReady,true);}
  console.log(JSON.stringify({endpoint,result}));
 }
 for(const name of ['index.html','workspace.js','workspace.css','scoring.js','catalog.json','tickets.js','tickets.css','stress.js','stress.css']){
  const expected=cp.execFileSync('git',['show',commit+':app/static/abs/'+name],{cwd:root});
  const response=await fetch('https://zhikejulia.com/'+name+'?verify='+commit,{signal:AbortSignal.timeout(20000)});assert.equal(response.status,200,name);
  assert.equal(hash(Buffer.from(await response.arrayBuffer())),hash(expected),'Live file differs: '+name);
 }
 console.log('PASS: deployed static assets match '+commit);
})().catch(error=>{console.error(error.message);process.exit(1)});
