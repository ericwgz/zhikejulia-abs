"""Versioned monitoring rules: observed values never come from model text."""
import calendar
import math
from datetime import date, timedelta
from abs_stress_data import DataError

VERSION = 'stress-1.0'
# Values here use display units: percent, percentage points, yuan, months, multiples.
SPECS = [
    ('dpd','逾期率 DPD30+','loan','%','DPD30+余额 / 资产池余额 × 100','value','gt',3,5),
    ('cdr','条件违约率 CDR','loan','%','1 − ∏(1 − 当日新增违约 / 期初未违约本金)^(365/天数)，年化','value','gt',2,4),
    ('ccr','累计违约率 CCR','loan','%','累计违约本金 / (初始本金 + 累计新增入池本金) × 100','forecast_multiple','gt',1.5,None),
    ('cpr','提前还款率 CPR','loan','%','1 − ∏(1 − 提前还款 / (期初未违约本金 − 计划本金))^(365/天数)，年化','change_pct','gt',50,None),
    ('term','平均贷款剩余期限','loan','月','Σ(余额 × 剩余月数) / 资产池余额','change_pct','gt',20,None),
    ('average','平均贷款余额','loan','元','资产池余额 / 贷款笔数','change_pct','gt',15,None),
    ('region','地域集中度','pool','%','最大单省贷款余额 / 资产池余额 × 100','value','gt',25,None),
    ('top10','大额贷款集中度（文档金额偏度）','pool','%','余额最高的前 ceil(贷款笔数×10%) 笔贷款合计 / 资产池余额 × 100','value','gt',40,None),
    ('shrink','资产池缩水率','pool','%','(1 − 月末余额 / 上月末余额) × 100；另展示余额留存比','value','gt',5,None),
    ('wal','加权平均期限 WAL','pool','月','Σ(未来计划本金 × 回款月数) / Σ未来计划本金；缺失时仅显示文档WAM代理','change_pct','gt',10,None),
    ('wac','加权平均利率 WAC','pool','%','Σ(余额 × 年利率) / 资产池余额 × 100','change_pp','lt',-.5,None),
    ('replacement','新增 / 到期比','pool','×','当月新增入池本金合计 / 当月到期本金合计','value','lt',.8,None),
    ('spread','超额利差','cash','%','WAC − 证券加权年成本，单位百分点','value','lt',2,1),
    ('oc','超额抵押率 OC','cash','%','资产池余额 / 证券总余额 × 100','value','lt',105,102),
    ('dsc','债务覆盖倍数 DSC','cash','×','当月可用现金流合计 / 当月应付本息合计','value','lt',1.3,1),
    ('reserve','储备金余额','cash','元','期末储备账户余额；与确认的最低储备比较','value','lt',None,0),
    ('residual','瀑布分配后净余缺','cash','元','当月瀑布后净余缺合计；负值是欠付需求，不是负现金账户','negative_periods','ge',None,3),
    ('interest','利息覆盖率','cash','×','当月资产利息收入 / 当月证券利息应付','value','lt',1.2,1),
    ('unemployment','失业率','macro','%','上传的同口径最新失业率；月末值比较','change_pp','gt',.5,None),
    ('income','居民可支配收入增速','macro','%','上传的同口径收入增速；不由贷款余额推导','value','lt',0,None),
    ('cpi','CPI 同比','macro','%','上传的最新 CPI 同比；不对每日重复值求和','value','gt',3,None),
    ('confidence','消费信心指数','macro','点','上传的最新指数；相对上月末变化','change_pct','lt',-5,None),
    ('lpr','LPR / 基准利率','macro','%','上传的同期限利率；上调 25bp = 0.25 个百分点','change_pp','ge',.25,None),
    ('policy','监管政策','macro','事件','非空政策事件启动人工评估；无内容不证明没有政策变化','value','ge',1,None),
]
IDS = {s[0] for s in SPECS}


def ratio(a, b, scale=1):
    result=a / b * scale if a is not None and b is not None and b > 0 else None
    return result if result is not None and math.isfinite(result) else None


def month_window(panel, end):
    first = end.replace(day=1)
    rows = [r for r in panel if first.isoformat() <= r['date'] <= end.isoformat()]
    expected = calendar.monthrange(end.year, end.month)[1]
    complete = end.day == expected and len(rows) == expected and [r['date'] for r in rows] == [(first+timedelta(days=i)).isoformat() for i in range(expected)]
    return rows, complete


def values(panel, end):
    row = next((r for r in panel if r['date'] == end.isoformat()), None)
    if row is None: return {}, {}, False
    rows, complete = month_window(panel, end)
    prior_date = end.replace(day=1)-timedelta(days=1)
    prior = next((r for r in panel if r['date']==prior_date.isoformat()), {})
    evidence = {}
    def field(key):
        evidence[key] = row.get(key)
        return row.get(key)
    def summed(key):
        v = sum(r[key] for r in rows) if complete and all(r.get(key) is not None for r in rows) else None
        evidence['month_sum:'+key] = v
        return v
    def annual(kind):
        if not complete: return None
        survival = 1.
        for r in rows:
            num = r.get('new_defaults' if kind=='cdr' else 'prepayments')
            den = r.get('performing_open')
            if kind == 'cpr':
                scheduled = r.get('scheduled_principal')
                den = den-scheduled if den is not None and scheduled is not None else None
            q = ratio(num, den)
            if q is None or not 0 <= q <= 1: return None
            survival *= 1-q
        return (1-survival**(365/len(rows)))*100
    balance=field('balance')
    orig, additions = field('original_balance'), field('cumulative_additions')
    denom = orig+additions if orig is not None and additions is not None else None
    wac = ratio(field('balance_rate'),balance,100)
    cost = field('security_rate')
    wal = ratio(field('principal_time'),field('future_principal'))
    v = {
        'dpd':ratio(field('dpd30_balance'),balance,100), 'cdr':annual('cdr'),
        'ccr':ratio(field('cumulative_defaults'),denom,100), 'cpr':annual('cpr'),
        'term':ratio(field('balance_term'),balance), 'average':ratio(balance,field('loan_count')),
        'region':ratio(field('max_province_balance'),balance,100), 'top10':ratio(field('top10_balance'),balance,100),
        'shrink':(1-balance/prior['balance'])*100 if complete and prior.get('balance') else None,
        'wal':wal, 'wac':wac, 'replacement':ratio(summed('new_assets'),summed('maturing_assets')),
        'spread':wac-cost*100 if wac is not None and cost is not None else None,
        'oc':ratio(balance,field('security_balance'),100), 'dsc':ratio(summed('available_cash'),summed('debt_due')),
        'reserve':field('reserve'), 'residual':summed('post_waterfall'), 'interest':ratio(summed('asset_interest'),summed('security_interest')),
        'confidence':field('confidence'), 'policy':(0 if row.get('policy') in ('无新增政策（已核查）','无新增政策（合成示例，已核查）') else 1) if field('policy') else None,
    }
    for mid,key in [('unemployment','unemployment'),('income','income_growth'),('cpi','cpi'),('lpr','lpr')]:
        x=field(key); v[mid]=x*100 if x is not None else None
    evidence.update({'period_start':end.replace(day=1).isoformat(),'period_end':end.isoformat(),'days':len(rows),'complete_month':complete,
                     'new_defaults_sum':summed('new_defaults'), 'prepayments_sum':summed('prepayments'), 'prior_balance':prior.get('balance')})
    return v,evidence,complete


def thresholds(overrides, balance):
    if not isinstance(overrides, dict) or set(overrides)-IDS: raise DataError('指标阈值包含未知字段。')
    result = {}
    for mid,name,dim,unit,formula,basis,op,yellow,red in SPECS:
        source='需求文档预警参考线（非合约事件）'
        if mid=='reserve': yellow=balance*.01; source='演示假设：报告日池余额的 1%，待按合同确认'
        value=overrides.get(mid)
        if value is not None:
            if not isinstance(value, dict) or set(value)-{'yellow','red','source','quote'}: raise DataError('阈值格式无效。')
            for level in ('yellow','red'):
                x=value.get(level)
                if x is not None and (isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or abs(x)>1e16): raise DataError('阈值必须是有限数字或空值。')
            yellow=value.get('yellow'); red=value.get('red')
            source=str(value.get('source','用户确认阈值'))[:160]
            quote=str(value.get('quote',''))[:500]
        else: quote=''
        if yellow is not None and red is not None and ((op in ('gt','ge') and red<yellow) or (op=='lt' and red>yellow)):
            raise DataError(f'{name} 的红色阈值应比黄色阈值更严格。')
        result[mid]={'yellow':yellow,'red':red,'basis':basis,'op':op,'source':source,'quote':quote}
    return result


def calculate(panel, overrides=None):
    latest=panel[-1]; end=date.fromisoformat(latest['date'])
    current, evidence, complete=values(panel,end)
    previous_end=end.replace(day=1)-timedelta(days=1)
    previous,_,_=values(panel,previous_end)
    rules=thresholds(overrides or {},latest['balance'])
    negatives=0; cursor=end; negative_known=True
    for _ in range(3):
        vv,_,_=values(panel,cursor)
        if vv.get('residual') is None:negative_known=False;break
        if vv['residual']>=0:break
        negatives+=1; cursor=cursor.replace(day=1)-timedelta(days=1)
    metrics=[]
    for mid,name,dim,unit,formula,basis,op,_,_ in SPECS:
        val=current.get(mid); prior=previous.get(mid); rule=rules[mid]; compare=val; note=''
        if basis=='change_pct': compare=ratio(val-prior,prior,100) if val is not None and prior is not None else None
        elif basis=='change_pp': compare=val-prior if val is not None and prior is not None else None
        elif basis=='forecast_multiple': compare=ratio(val,latest.get('forecast_ccr'),.01)
        elif basis=='negative_periods': compare=negatives if val is not None and negative_known else None
        if mid=='wal' and val is None:
            note='缺少未来计划本金回款时间。文档余额加权剩余期限（WAM）代理：'+(f'{current["term"]:.2f} 月' if current.get('term') is not None else '缺失')+'；不冒充真实 WAL。'
        if mid=='policy' and val is None: note='未提供政策事件，不等同已完成政策排查。'
        if compare is None or (rule['yellow'] is None and rule['red'] is None): status='gray'
        else:
            def hit(bound):
                if bound is None:return False
                if mid=='reserve' and bound==0:return compare<=0
                return compare>bound if op=='gt' else compare>=bound if op=='ge' else compare<bound
            status='red' if hit(rule['red']) else 'yellow' if hit(rule['yellow']) else 'green'
        if compare is None and not note: note='缺少必要输入、完整自然月、可比较前期或有效分母；见输入证据。'
        metrics.append({'id':mid,'ref':'M'+str(len(metrics)+1),'name':name,'dimension':dim,'value':val,'previous':prior,'comparison':compare,
                        'unit':unit,'formula':formula,'threshold':rule,'status':status,'note':note,'as_of':end.isoformat()})
    weights={'loan':.4,'pool':.25,'cash':.25,'macro':.1}; scores={'green':100,'yellow':70,'red':35}
    dimensions=[]
    for dim,weight in weights.items():
        group=[m for m in metrics if m['dimension']==dim]
        score=sum(scores[m['status']] for m in group)/6 if all(m['status']!='gray' for m in group) else None
        dimensions.append({'id':dim,'weight':weight,'score':score})
    # Missing assessment is not silently reweighted. Policy must be explicitly supplied to be assessed.
    score=math.floor(sum(d['score']*d['weight'] for d in dimensions)+.5) if all(d['score'] is not None for d in dimensions) else None
    if score is not None:
        if any(m['status']=='red' for m in metrics):score=min(score,59)
        elif any(m['status']=='yellow' for m in metrics):score=min(score,79)
    status='gray' if score is None else 'green' if score>=80 else 'yellow' if score>=60 else 'red'
    pd=ratio(latest.get('balance_pd'),latest.get('pd_covered_balance'),100)
    return {'method_version':VERSION,'as_of':end.isoformat(),'period':evidence,'metrics':metrics,'dimensions':dimensions,'score':score,'status':status,
            'assessed':sum(m['status']!='gray' for m in metrics),'alerts':[m for m in metrics if m['status'] in ('yellow','red')],
            'aggregates':{'dpd1':ratio(latest.get('dpd1_balance'),latest['balance'],100),'dpd90':ratio(latest.get('dpd90_balance'),latest['balance'],100),
                          'weighted_pd_12m':pd,'pd_coverage':ratio(latest.get('pd_covered_balance'),latest['balance'],100),
                          'duration_years':ratio(latest.get('duration_pv_time'),latest.get('duration_pv')),
                          'balance_retention':100-current['shrink'] if current.get('shrink') is not None else None},
            'score_method':'四维权重 40/25/25/10；各维6指标等权，绿100/黄70/红35。缺一项评估则不出总分；任一红线触发总分上限59，仅有黄线触发上限79。绿≥80、黄60–79、红<60。阈值型内部监控分，不是信用评级。',
            'notes':['CDR/CPR 使用完整自然月日生存率法年化；环比对比上月末。未完整月不外推。',
                     'CCR 分母采用初始本金+累计新增入池本金；实际交易口径如不同需调整输入与方法。',
                     '平均期限为WAM；WAL使用本金计划；久期为上传现金流现值加权年数，不由WAL代替。',
                     '宏观数据由上传文件提供，未联网核验。信心指数按下降5%、失业率/WAC变化按百分点解释。']}
