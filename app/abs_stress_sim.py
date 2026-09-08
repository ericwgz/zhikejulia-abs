"""Monthly closed-pool scenario engine with explicit cash and principal ledgers."""
import math
from abs_stress_data import DataError

DEFAULTS = {'months':6,'deterioration_pp':3,'collection_drop_pct':20,'early_cpr_pct':60,
            'shock_default_pct':35,'shock_month':2,'recovery_pct':35,'recovery_lag':3,
            'macro_unemployment_pp':1,'macro_income_pp':-2,'macro_confidence_pct':-10,'macro_lpr_bp':25,
            'macro_lag':3,'macro_cdr_multiplier':1.5,'fee_pct':.5,'reserve_target_pct':1,
            'acceleration_dpd_pct':5,'default_ccr_pct':10,'default_accelerates':True}
SCENARIOS = [('base','基准情景'),('deterioration','基础恶化'),('prepayment','早偿冲击'),('default','极端违约'),('macro','宏观冲击')]


def parameters(raw):
    if not isinstance(raw,dict) or set(raw)-set(DEFAULTS):raise DataError('压力参数包含未知字段。')
    p=DEFAULTS|raw
    for k,v in p.items():
        if k=='default_accelerates':
            if not isinstance(v,bool):raise DataError('违约加速参数必须为布尔值。')
        elif isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise DataError('压力参数须为有限数字。')
    if p['months'] not in (3,6,12):raise DataError('预测期数请选择 3、6 或 12 个月。')
    for k in ('shock_month','recovery_lag','macro_lag'):
        if p[k]!=int(p[k]) or not 1<=p[k]<=12:raise DataError('冲击月份及滞后月数须为 1–12 的整数。')
    for k in ('deterioration_pp','collection_drop_pct','early_cpr_pct','shock_default_pct','recovery_pct','reserve_target_pct','acceleration_dpd_pct','default_ccr_pct'):
        if not 0<=p[k]<=100:raise DataError(k+' 须在 0–100 之间。')
    if not 0<=p['fee_pct']<=10 or not 0<=p['macro_cdr_multiplier']<=10:raise DataError('服务费或宏观违约倍率超出范围。')
    if not -10<=p['macro_unemployment_pp']<=10 or not -30<=p['macro_income_pp']<=30 or not -100<=p['macro_confidence_pct']<=100 or not -500<=p['macro_lpr_bp']<=500:
        raise DataError('宏观变化参数超出范围。')
    return p


def simulate(latest, assessment, raw=None):
    p=parameters(raw or {})
    required=('balance','dpd90_balance','balance_term','reserve','original_balance','cumulative_additions','cumulative_defaults',
              'a_balance','b_balance','sub_balance','a_rate','b_rate','sub_rate','a_maturity','b_maturity','sub_maturity')
    absent=[k for k in required if latest.get(k) is None]
    metrics={m['id']:m['value'] for m in assessment['metrics']}
    absent += [mid for mid in ('cdr','cpr','wac','dpd') if metrics.get(mid) is None]
    if absent: return {'ready':False,'missing':absent,'parameters':p,'message':'补齐压力模拟输入和完整自然月后再推演；未使用模型猜测缺失值。'}
    if latest['balance']<=0 or latest['balance_term']<=0 or any(not 1<=latest[k]<=120 or latest[k]!=int(latest[k]) for k in ('a_maturity','b_maturity','sub_maturity')):
        raise DataError('压力推演需要正资产余额及 1–120 月证券剩余期限。')
    results=[one_scenario(latest,metrics,p,key,label) for key,label in SCENARIOS]
    base=results[0]
    for s in results:
        s['delta_vs_base']={'interest_income':s['interest_income']-base['interest_income'],
                            'max_due_shortfall':s['max_due_shortfall']-base['max_due_shortfall'],
                            'max_principal_impairment':s['max_principal_impairment']-base['max_principal_impairment']}
    return {'ready':True,'parameters':p,'scenarios':results,'assumptions':[
        '一期=一个预测月，利率按12期转换。封闭资产池、无循环购买、无资产置换；使用汇总等额本金近似，不替代逐笔还款计划。',
        '基准CDR/CPR来自最新完整自然月。已有90+余额移入违约回收队列；不再重复计作新增违约。',
        '正常瀑布：费用→A息→B息→到期A/B本金→储备补足→次级本息→剩余收益；未到期多余本金暂存现金。',
        '加速：费用→A息→B息→A本金→B本金；次级利息在法定到期前允许递延，单列不计逾期；次级到期后未付仍计缺口。违约：费用→A本息→B本息→次级。状态不可逆。',
        '合同本金按上传剩余月数到期一次偿还；加速为提前分配，不自动算应付缺口；违约是否全额到期由参数决定。',
        '触发以每期分配前DPD30和累计违约率判断。模型不擅自推断复杂合约、宽限期或支付失败条款。',
        '本金覆盖损失通过资产价值虚拟清算：正常本金+预计回收应收+现金+储备，先付欠费，再按A本息→B本息→次级分配，分别计算本金不足；不含未来未实现利差。',
        '兑付缺口为当期到期后仍欠付的存量，不能把逐期存量相加；未到期余额、预测覆盖损失与实际核销分别显示。',
        '早偿仅直接增加本金回款；不会预设超额收益上升。宏观弹性和传导滞后是可调整假设，未以180天数据拟合因果关系。',
        '回收至少滞后1个月。未收计划本金留在资产内；未收利息不资本化。利率固定，LPR冲击通过假设信用渠道传导。',
    ]}


def one_scenario(r,m,p,key,label):
    balance=r['balance']; performing=balance-r['dpd90_balance']; term=r['balance_term']/balance
    recovery=p['recovery_pct']/100; lag=int(p['recovery_lag'])
    reserve=r['reserve']; cash=0.; fees_due=0.; state='normal'; events=[]; months=[]
    queue={lag:r['dpd90_balance']*recovery}
    # Existing gross defaults remain in historical CCR; only projected NEW defaults are added below.
    cum_defaults=r['cumulative_defaults']; denom=r['original_balance']+r['cumulative_additions']
    if denom<=0:raise DataError('累计违约分母必须大于零。')
    tranches={k:{'name':n,'initial':r[k+'_balance'],'balance':r[k+'_balance'],'rate':r[k+'_rate'],
                 'maturity':int(r[k+'_maturity']),'interest_due':0.,'principal_paid':0.,'interest_paid':0.,
                 'max_impairment':0.,'breach_month':None,'first_shortfall':None} for k,n in [('a','优先 A'),('b','优先 B'),('sub','次级')]}
    for period in range(1,int(p['months'])+1):
        before_performing=performing; before_cash=cash; before_reserve=reserve
        before_recoveries=sum(queue.values()); before_security=sum(t['balance'] for t in tranches.values())
        cdr=m['cdr']/100; cpr=m['cpr']/100; collection=1.; dpd=m['dpd']; extra_default=0.
        if key=='deterioration':
            progress=period/p['months']; uplift=p['deterioration_pp']*progress
            dpd=min(100,dpd+uplift); cdr=min(.999,cdr*(1+uplift/max(m['dpd'],1)))
            collection=1-p['collection_drop_pct']/100*progress
        elif key=='prepayment' and period<=3: cpr=max(cpr,p['early_cpr_pct']/100)
        elif key=='default' and period==p['shock_month']: extra_default=p['shock_default_pct']/100
        elif key=='macro' and period>=p['macro_lag']:
            impact=max(0,p['macro_unemployment_pp']*.2-p['macro_income_pp']*.04-p['macro_confidence_pct']*.01+p['macro_lpr_bp']*.001)
            cdr=min(.999,cdr*p['macro_cdr_multiplier']*(1+impact)); collection=max(0,1-min(.8,impact*.1))
            dpd=min(100,dpd+impact*2); cpr=max(0,cpr*(1-min(.8,impact*.15)))
        md=1-(1-min(1,cdr))**(1/12); smm=1-(1-min(1,cpr))**(1/12)
        new_default=performing*(1-(1-md)*(1-extra_default)); cum_defaults+=new_default
        performing-=new_default; expected_recovery=new_default*recovery
        queue[period+lag]=queue.get(period+lag,0)+expected_recovery
        recovered=queue.pop(period,0)
        scheduled=min(performing,performing/max(1,term-period+1))
        principal=scheduled*collection; early=(performing-principal)*smm
        interest=max(0,performing-(principal+early)/2)*m['wac']/100/12*collection
        performing-=principal+early
        available=before_cash+interest+principal+early+recovered
        cash=available
        ccr=cum_defaults/denom*100
        target_state='default' if ccr>=p['default_ccr_pct'] else 'accelerated' if dpd>=p['acceleration_dpd_pct'] else 'normal'
        if ['normal','accelerated','default'].index(target_state)>['normal','accelerated','default'].index(state):
            trigger='ccr' if target_state=='default' else 'dpd'
            events.append({'ref':f'E-{key}-{period}','period':period,'from':state,'to':target_state,'metric':trigger,
                           'value':ccr if trigger=='ccr' else dpd,'threshold':p['default_ccr_pct'] if trigger=='ccr' else p['acceleration_dpd_pct'],
                           'basis':'演示合同触发参数；非正式法律事件判定'})
            state=target_state
        for t in tranches.values():t['interest_due']+=t['balance']*t['rate']/12
        fees_due+=before_performing*p['fee_pct']/100/12
        paid_fee=0.; paid_interest=0.; paid_principal=0.; residual=0.; drawn=0.; funded=0.
        def pay(amount,allow_reserve=True):
            nonlocal cash,reserve,drawn
            amount=max(0,amount); take=min(cash,amount); cash-=take
            if allow_reserve:
                extra=min(reserve,amount-take);reserve-=extra;drawn+=extra;take+=extra
            return take
        paid_fee=pay(fees_due); fees_due-=paid_fee
        def pay_interest(k,allow_reserve=True):
            nonlocal paid_interest
            t=tranches[k]; amount=pay(t['interest_due'],allow_reserve); t['interest_due']-=amount;t['interest_paid']+=amount;paid_interest+=amount
        def due(t): return period>=t['maturity'] or state=='default' and p['default_accelerates']
        def pay_principal(k,accelerate=False,allow_reserve=True):
            nonlocal paid_principal
            t=tranches[k]
            if not accelerate and not due(t):return
            amount=pay(t['balance'],allow_reserve); t['balance']-=amount;t['principal_paid']+=amount;paid_principal+=amount
        if state=='default':
            for k in ('a','b','sub'):pay_interest(k);pay_principal(k,True)
        else:
            pay_interest('a');pay_interest('b')
            for k in ('a','b'):pay_principal(k,state=='accelerated',state=='normal' or due(tranches[k]))
            if state=='accelerated' and all(tranches[k]['balance']+tranches[k]['interest_due']<=.01 for k in ('a','b')) and due(tranches['sub']):
                pay_interest('sub');pay_principal('sub')
            if state=='normal':
                target=balance*p['reserve_target_pct']/100
                funded=min(cash,max(0,target-reserve));reserve+=funded;cash-=funded
                pay_interest('sub',False);pay_principal('sub',False,False)
                # Retain all unused principal cash for bullet liabilities; distribute excess interest only.
                residual=min(cash,max(0,interest-paid_fee-paid_interest-funded));cash-=residual
        interest_due=sum(t['interest_due'] for t in tranches.values())
        def deferred(k,t):return t['interest_due'] if k=='sub' and state=='accelerated' and period<t['maturity'] else 0.
        due_shortfall=sum(t['interest_due']-deferred(k,t)+(t['balance'] if due(t) else 0) for k,t in tranches.items())+fees_due
        coverage_assets=max(0,performing+sum(queue.values())+cash+reserve-fees_due)
        losses={};details=[]
        for k in ('a','b','sub'):
            t=tranches[k];coverage_assets=max(0,coverage_assets-t['interest_due'])
            covered=min(t['balance'],coverage_assets);coverage_assets-=covered;losses[k]=t['balance']-covered
        impairment=sum(losses.values())
        for k in ('sub','b','a'):
            t=tranches[k];loss=losses[k];t['max_impairment']=max(t['max_impairment'],loss)
            if t['balance']>.01 and loss>=t['balance']-.01 and t['breach_month'] is None:t['breach_month']=period
        for k,t in tranches.items():
            short=t['interest_due']-deferred(k,t)+(t['balance'] if due(t) else 0)
            if short>.01 and t['first_shortfall'] is None:t['first_shortfall']=period
            details.append({'id':k,'name':t['name'],'balance':t['balance'],'interest_due':t['interest_due'],
                            'due_shortfall':short,'deferred_interest':deferred(k,t),'not_yet_due_principal':0 if due(t) else t['balance'],'coverage_impairment':losses[k]})
        cash_error=before_cash+before_reserve+interest+principal+early+recovered-(paid_fee+paid_interest+paid_principal+residual+cash+reserve)
        asset_error=before_performing-(performing+new_default+principal+early)
        recovery_error=before_recoveries+expected_recovery-(recovered+sum(queue.values()))
        security_error=before_security-(paid_principal+sum(t['balance'] for t in tranches.values()))
        if max(abs(x) for x in (cash_error,asset_error,recovery_error,security_error))>max(.01,balance*1e-10):raise ArithmeticError('Ledger invariant failed')
        months.append({'ref':f'F-{key}-{period}','period':period,'state':state,'dpd':dpd,'ccr':ccr,'cdr':cdr*100,'cpr':cpr*100,
                       'collection_rate':collection*100,'interest_income':interest,'scheduled_principal':principal,'prepayment_principal':early,
                       'default_recovery':recovered,'new_defaults':new_default,'available_cash':available,'reserve_drawn':drawn,'reserve_funded':funded,
                       'fee_paid':paid_fee,'interest_paid':paid_interest,'principal_paid':paid_principal,'residual_paid':residual,
                       'due_shortfall':due_shortfall,'ending_cash':cash,'ending_reserve':reserve,'performing_principal':performing,
                       'pending_recoveries':sum(queue.values()),'principal_impairment':impairment,'tranches':details,
                       'ledger_errors':{'cash':cash_error,'asset':asset_error,'recovery':recovery_error,'security':security_error}})
    detail=[]
    for k,t in tranches.items():
        detail.append({**t,'id':k,'impairment_ratio':t['max_impairment']/t['initial']*100 if t['initial'] else 0,
                       'end_due_shortfall':months[-1]['tranches'][list(tranches).index(k)]['due_shortfall']})
    max_gap=max(mo['due_shortfall'] for mo in months); max_loss=max(mo['principal_impairment'] for mo in months)
    # Internal scenario label is rule-based and distinct from the historical 24-metric score.
    status='red' if any(mo['state']=='default' for mo in months) or max_gap>.01 or tranches['a']['max_impairment']>.01 or tranches['b']['max_impairment']>.01 else 'yellow' if max_loss>.01 or events else 'green'
    return {'id':key,'ref':'S-'+key,'name':label,'status':status,'stability':{'red':'脆弱','yellow':'承压','green':'稳定'}[status],
            'months':months,'tranches':detail,'events':events,'max_due_shortfall':max_gap,'max_principal_impairment':max_loss,
            'interest_income':sum(mo['interest_income'] for mo in months),'principal_collections':sum(mo['scheduled_principal']+mo['prepayment_principal'] for mo in months),
            'first_acceleration':next((e['period'] for e in events if e['to']=='accelerated'),None),
            'first_default':next((e['period'] for e in events if e['to']=='default'),None),'sub_breach':tranches['sub']['breach_month']}
