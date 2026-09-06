(function(root){
  'use strict';
  const dimensions = [
    {id:'loan',name:'底层贷款',question:'借款人能不能还',weight:.4,icon:'▤'},
    {id:'pool',name:'资产池结构',question:'池子健不健康',weight:.25,icon:'◫'},
    {id:'cash',name:'现金流与偿付',question:'钱够不够还',weight:.25,icon:'≋'},
    {id:'macro',name:'宏观与行为',question:'环境变没变',weight:.1,icon:'◎'}
  ];
  // Each anchor is [observed value, score]. Linear interpolation, clipped to 0–100.
  const metrics = [
    {id:'dpd',dim:'loan',name:'DPD30+ 余额占比',code:'DELINQUENCY / ≥30 DAYS',unit:'%',weight:.5,anchors:[[1,100],[2,80],[3,60],[5,0]],def:'观察日逾期至少 30 天贷款的全部未偿本金 ÷ 同日资产池全部未偿本金。分母不使用逾期分期金额。',source:'贷款台账 · 2026.08.31 · 模拟汇总'},
    {id:'migration',dim:'loan',name:'M1 → M2 迁徙率',code:'COHORT ROLL RATE / 1 MONTH',unit:'%',weight:.3,anchors:[[8,100],[15,80],[22,60],[40,0]],def:'追踪期初 DPD 1–30 天的固定贷款队列，期末迁入 DPD 31–60 天的期初本金权重 ÷ 该队列期初本金；观察间隔一个月。不是两个独立月末余额相除。',source:'队列迁徙表 · 2026.07–08 · 模拟汇总'},
    {id:'loss',dim:'loan',name:'累计净损失率',code:'STATIC COHORT / NET LOSS',unit:'%',weight:.2,anchors:[[1,100],[2.5,80],[4,60],[7,0]],def:'初始静态批次的累计违约本金减累计回收本金 ÷ 该批次初始本金，违约按 DPD90+ 定义并去重。循环新购资产需分批次监控，不混入初始分母。',source:'初始批次表现表 · 截至 2026.08.31 · 模拟汇总'},
    {id:'concentration',dim:'pool',name:'前五大省份余额占比',code:'GEOGRAPHIC CONCENTRATION',unit:'%',weight:.4,anchors:[[30,100],[40,80],[50,60],[70,0]],def:'余额最大的五个省份贷款未偿本金之和 ÷ 资产池未偿本金，地区以借款人统一口径常住地统计。',source:'资产池分布表 · 2026.08.31 · 模拟汇总'},
    {id:'eligibility',dim:'pool',name:'新购资产合格率',code:'REVOLVING PURCHASE / ELIGIBILITY',unit:'%',weight:.35,anchors:[[90,0],[97,60],[99,80],[100,100]],def:'通过全部演示入池资格规则的新购贷款本金 ÷ 本期拟购贷款本金。真实规则应逐条对应交易文件，不能仅用平均得分替代资格检查。',source:'循环购买核验表 · 2026.08 · 模拟汇总'},
    {id:'tenor',dim:'pool',name:'加权平均剩余期限',code:'WEIGHTED AVERAGE MATURITY',unit:'个月',weight:.25,anchors:[[6,100],[9,80],[12,60],[18,0]],def:'各贷款剩余合同期限按未偿本金加权。此处以期限越长风险越高作演示，真实评分需联动产品与证券剩余期限。',source:'资产池期限表 · 2026.08.31 · 模拟汇总'},
    {id:'coverage',dim:'cash',name:'下期优先档本息覆盖',code:'NEXT PAYMENT / SENIOR COVERAGE',unit:'×',weight:.6,anchors:[[.8,0],[1,60],[1.1,80],[1.3,100]],def:'下期可分配现金扣费用后的余额 ÷ 优先档当期应付利息和本金。可分配现金包含演示可用储备。小于 1 触发红灯覆盖规则。',source:'下一偿付日预算 · 2026.09.25 · 模拟现金流'},
    {id:'reserve',dim:'cash',name:'现金储备达标率',code:'CASH RESERVE / TARGET',unit:'%',weight:.2,anchors:[[50,0],[80,60],[100,80],[120,100]],def:'可用现金储备 ÷ 演示目标储备；目标随示例产品规模同比例配置。真实储备调用与补足顺序依交易文件配置。',source:'储备账户表 · 2026.08.31 · 模拟余额'},
    {id:'spread',dim:'cash',name:'年化超额利差',code:'ANNUALISED EXCESS SPREAD',unit:'%',weight:.2,anchors:[[0,0],[1,60],[2,80],[4,100]],def:'近一期年化资产收益减证券融资成本、服务及管理费用后的利差，未扣未来信用损失。不能作为已实现保障。',source:'收支预算表 · 2026.08 · 模拟汇总'},
    {id:'unemployment',dim:'macro',name:'失业率情景值',code:'MACRO / SCENARIO INPUT',unit:'%',weight:.4,anchors:[[4,100],[5,80],[6,60],[8,0]],def:'模拟宏观情景输入，不是国家统计局当前发布数据。实际使用应接入官方序列并考虑发布时滞及区域暴露。',source:'宏观假设表 · 2026.08 · 人工设定示例'},
    {id:'autopay',dim:'macro',name:'自动扣款成功率',code:'PAYMENT BEHAVIOUR / AUTOPAY',unit:'%',weight:.4,anchors:[[80,0],[90,60],[95,80],[99,100]],def:'观察期首次自动扣款成功的应还贷款笔数 ÷ 发起首次扣款的应还贷款笔数。与余额加权逾期指标分开解释。',source:'扣款行为统计 · 2026.08 · 模拟汇总'},
    {id:'prepay',dim:'macro',name:'提前还款率偏离',code:'CPR / ABSOLUTE DEVIATION',unit:'个百分点',weight:.2,anchors:[[0,100],[2,80],[4,60],[8,0]],def:'近一期年化提前还款率与演示基准的绝对差。高早偿可能压缩利差并增加再投资需求，因此不一律视为利好。',source:'早偿情景表 · 2026.08 · 模拟汇总'}
  ];
  // All amounts are in RMB 10,000; all data are synthetic.
  const pools = {
    huabei:{name:'消费贷 2026-03 · 花呗类',type:'消费贷应收账款（演示）',balance:238000,collections:28000,reserveCash:5000,fees:400,interest:2500,principal:27500,values:{dpd:2.65,migration:18.4,loss:2.35,concentration:37.2,eligibility:100,tenor:8.4,reserve:100,spread:2.8,unemployment:5.4,autopay:93.2,prepay:1.8},prior:82,history:[86,85,84,82,82],due:'2026.09.25'},
    jiebei:{name:'消费贷 2026-02 · 借呗类',type:'个人小额贷款应收账款（演示）',balance:196000,collections:34300,reserveCash:6000,fees:400,interest:2500,principal:27500,values:{dpd:1.52,migration:10.5,loss:1.2,concentration:31.8,eligibility:100,tenor:8,reserve:120,spread:3.6,unemployment:5.4,autopay:97.8,prepay:1},prior:91,history:[88,89,90,91,91],due:'2026.09.25'},
    risk:{name:'消费贷 2026-01 · 压力样本',type:'个人小额贷款应收账款（演示）',balance:215000,collections:24200,reserveCash:4500,fees:400,interest:2500,principal:27500,values:{dpd:3.8,migration:24.5,loss:5.2,concentration:42.5,eligibility:98.5,tenor:10.2,reserve:90,spread:1.8,unemployment:5.4,autopay:91,prepay:2.8},prior:68,history:[82,79,76,73,68],due:'2026.09.25'}
  };
  const clamp=(v,min=0,max=100)=>Math.min(max,Math.max(min,v));
  function scoreMetric(value,anchors){
    if(!Number.isFinite(value))return null;
    if(value<=anchors[0][0])return anchors[0][1];
    if(value>=anchors.at(-1)[0])return anchors.at(-1)[1];
    for(let i=1;i<anchors.length;i++)if(value<=anchors[i][0]){const[a,s]=anchors[i-1];const[b,t]=anchors[i];return clamp(s+(value-a)/(b-a)*(t-s));}
  }
  function color(score,thresholds={green:80,yellow:60}){if(score===null||!Number.isFinite(score))return 'gray';const displayed=Math.round(score);return displayed>=thresholds.green?'green':displayed>=thresholds.yellow?'yellow':'red';}
  function evaluate(pool,options={}){
    const {multiplier=1,recovery=40,delay=0,complete=true,thresholds={green:80,yellow:60}}=options;
    if(!Number.isFinite(multiplier)||multiplier<1||multiplier>3||!Number.isFinite(recovery)||recovery<0||recovery>70||!Number.isFinite(delay)||delay<0||delay>20)throw new Error('压力假设超出范围');
    if(!Number.isInteger(thresholds.green)||!Number.isInteger(thresholds.yellow)||thresholds.yellow<1||thresholds.green>100||thresholds.yellow>=thresholds.green)throw new Error('灯色阈值无效');
    const amounts=['balance','collections','reserveCash','fees','interest','principal'];
    const validAmounts=pool&&amounts.every(k=>Number.isFinite(pool[k])&&pool[k]>=0)&&pool.balance>0&&pool.interest+pool.principal>0;
    const validMetrics=pool?.values&&metrics.filter(m=>m.id!=='coverage').every(m=>Number.isFinite(pool.values[m.id])&&pool.values[m.id]>=0&&(m.id==='reserve'||pool.values[m.id]<=100));
    if(!complete||!validAmounts||!validMetrics)return{values:{},metrics:metrics.map(m=>({...m,value:null,score:null})),dimensions:dimensions.map(d=>({...d,score:null})),raw:null,score:null,status:'gray',triggers:[],cash:null,coverage:null,shortfall:null,waterfall:{feePaid:null,interestPaid:null,principalPaid:null,residual:null},complete:false};
    const baseLoss=pool.balance*.03*.6;
    const scenarioLoss=pool.balance*.03*multiplier*(1-recovery/100);
    const cash=Math.max(0,pool.collections-(scenarioLoss-baseLoss))*(1-delay/30)+pool.reserveCash;
    const available=Math.max(0,cash-pool.fees);
    const due=pool.interest+pool.principal;
    // Historical cumulative loss stays observed. Prospective recovery assumptions
    // change future cash availability; they cannot undo an already-hit trigger.
    const values={...pool.values,dpd:clamp(pool.values.dpd*multiplier),migration:clamp(pool.values.migration*multiplier),coverage:available/due};
    const results=metrics.map(m=>({...m,value:values[m.id],score:complete?scoreMetric(values[m.id],m.anchors):null}));
    const dims=dimensions.map(d=>({...d,score:complete?results.filter(m=>m.dim===d.id).reduce((s,m)=>s+m.score*m.weight,0):null}));
    const raw=complete?dims.reduce((s,d)=>s+d.score*d.weight,0):null;
    const triggers=[];
    if(values.coverage<1)triggers.push('下期优先档本息覆盖不足 1.00×');
    if(values.loss>=5)triggers.push('累计净损失率达到演示触发线 5.00%');
    const score=complete?Math.min(Math.round(raw),triggers.length?thresholds.yellow-1:100):null;
    let remaining=cash;
    const feePaid=Math.min(remaining,pool.fees);remaining-=feePaid;
    const interestPaid=Math.min(remaining,pool.interest);remaining-=interestPaid;
    const principalPaid=Math.min(remaining,pool.principal);remaining-=principalPaid;
    return{values,metrics:results,dimensions:dims,raw,score,status:color(score,thresholds),triggers,cash,coverage:values.coverage,shortfall:Math.max(0,due-available),waterfall:{feePaid,interestPaid,principalPaid,residual:remaining},complete};
  }
  const api={dimensions,metrics,pools,scoreMetric,color,evaluate};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ABS=api;
})(typeof window!=='undefined'?window:globalThis);
