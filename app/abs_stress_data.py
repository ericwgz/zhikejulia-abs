"""Bounded, dependency-free panel-data import and reproducible synthetic fixtures."""
import base64
import csv
import io
import math
import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

MAX_FILE = 700_000
MAX_ROWS = 6000
FIELDS = [
    ('product_id', '产品编号', 'text'), ('product_name', '产品名称', 'text'), ('date', '日期', 'date'),
    ('balance', '资产池余额', '元'), ('loan_count', '贷款笔数', '笔'),
    ('dpd1_balance', 'DPD1+余额', '元'), ('dpd30_balance', 'DPD30+余额', '元'), ('dpd90_balance', 'DPD90+余额', '元'),
    ('new_defaults', '当日新增违约本金', '元'), ('performing_open', '当日期初未违约本金', '元'),
    ('cumulative_defaults', '累计违约本金', '元'), ('original_balance', '初始资产池本金', '元'), ('cumulative_additions', '累计新增入池本金', '元'),
    ('scheduled_principal', '当日计划本金回款', '元'), ('prepayments', '当日提前还款本金', '元'),
    ('balance_term', '余额乘剩余期限合计', '元月'), ('balance_rate', '余额乘年利率合计', '元比率'),
    ('balance_pd', '余额乘12月PD合计', '元比率'), ('pd_covered_balance', '有12月PD的贷款余额', '元'),
    ('duration_pv_time', '现金流现值乘年数合计', '元年'), ('duration_pv', '现金流现值合计', '元'),
    ('principal_time', '未来计划本金乘回款月数合计', '元月'),
    ('future_principal', '未来计划本金合计', '元'), ('max_province_balance', '最大单省余额', '元'),
    ('top10_balance', '余额前10%贷款合计', '元'), ('new_assets', '当日新入池本金', '元'), ('maturing_assets', '当日到期本金', '元'),
    ('security_balance', '证券总余额', '元'), ('security_rate', '证券加权年成本', '比率'),
    ('available_cash', '当日可用现金流', '元'), ('debt_due', '当日应付本息', '元'), ('reserve', '储备金余额', '元'),
    ('post_waterfall', '当日瀑布后净余缺', '元'), ('asset_interest', '当日资产利息收入', '元'), ('security_interest', '当日证券利息应付', '元'),
    ('unemployment', '失业率', '比率'), ('income_growth', '收入增速', '比率'), ('cpi', 'CPI同比', '比率'),
    ('confidence', '消费信心指数', '指数'), ('lpr', 'LPR', '比率'), ('policy', '监管政策事件', 'text'),
    ('forecast_ccr', '发行预测累计违约率', '比率'),
    ('a_balance', '优先A余额', '元'), ('b_balance', '优先B余额', '元'), ('sub_balance', '次级余额', '元'),
    ('a_rate', '优先A年票息', '比率'), ('b_rate', '优先B年票息', '比率'), ('sub_rate', '次级年票息', '比率'),
    ('a_maturity', '优先A剩余月数', '月'), ('b_maturity', '优先B剩余月数', '月'), ('sub_maturity', '次级剩余月数', '月'),
]
KEYS = [f[0] for f in FIELDS]
ALIASES = {name: key for key, name, unit in FIELDS} | {key: key for key in KEYS}
RATIOS = {k for k, _, u in FIELDS if u == '比率'}


class DataError(ValueError):
    pass


def decode_file(data, pdf_contract=False):
    name = data.get('filename')
    if not isinstance(name, str) or len(name) > 160:
        raise DataError('文件名无效。')
    try:
        content = base64.b64decode(data.get('content', ''), validate=True)
    except (ValueError, TypeError):
        raise DataError('文件编码无法读取。') from None
    limit = 5_000_000 if pdf_contract and name.lower().endswith('.pdf') else MAX_FILE
    if not 0 < len(content) <= limit:
        if limit > MAX_FILE: raise DataError('PDF单个文件限5 MB，请上传包含监控阈值的合约节选。')
        raise DataError('单个文件限 700 KB；请使用资产池日度汇总数据。')
    return name, content


def xml(raw):
    # OOXML normally uses UTF-8; reject other encodings rather than scanning encoded bytes unsafely.
    try: decoded=raw.decode('utf-8-sig')
    except UnicodeDecodeError: raise DataError('XML须使用UTF-8编码。') from None
    if '\x00' in decoded or '<!DOCTYPE' in decoded.upper() or '<!ENTITY' in decoded.upper():
        raise DataError('不支持包含外部实体的 XML。')
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise DataError('文件内部 XML 损坏。') from None


def archive(raw):
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        infos = z.infolist()
        if len(infos) > 100 or sum(i.file_size for i in infos) > 8_000_000:
            raise DataError('文件解压后过大，请减少行数或删除无关工作表。')
        if len({i.filename for i in infos}) != len(infos) or any(i.flag_bits & 1 for i in infos):
            raise DataError('不支持加密或重复条目的文件。')
        return z
    except (zipfile.BadZipFile, RuntimeError):
        raise DataError('文件不是有效的 XLSX / DOCX。') from None


def xlsx_rows(raw):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with archive(raw) as z:
        names = z.namelist()
        if any('vbaProject' in n or 'externalLink' in n for n in names):
            raise DataError('不支持宏或外部工作簿链接。')
        if 'xl/workbook.xml' not in names:
            raise DataError('找不到 Excel 工作簿。')
        book = xml(z.read('xl/workbook.xml'))
        if book.find('s:workbookPr', ns) is not None and book.find('s:workbookPr', ns).get('date1904') in ('1', 'true'):
            raise DataError('请将日期改为 YYYY-MM-DD 文本，并使用 Excel 1900 日期系统。')
        rels = {r.get('Id'): r.get('Target') for r in xml(z.read('xl/_rels/workbook.xml.rels')) if r.get('TargetMode') != 'External'}
        sheets = book.findall('s:sheets/s:sheet', ns)
        selected = next((s for s in sheets if s.get('name') in ('资产池日度', 'pool_daily')), sheets[0] if sheets else None)
        if selected is None:
            raise DataError('工作簿没有可读取的工作表。')
        target = rels.get(selected.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'), '')
        path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        if '..' in path or path not in names:
            raise DataError('工作表路径无法识别。')
        strings = []
        if 'xl/sharedStrings.xml' in names:
            strings = [''.join(e.itertext()) for e in xml(z.read('xl/sharedStrings.xml'))]
        result = []
        for row in xml(z.read(path)).findall('s:sheetData/s:row', ns):
            cells = {}
            for cell in row.findall('s:c', ns):
                ref = cell.get('r', '')
                match = re.fullmatch(r'([A-Z]{1,3})[0-9]+', ref)
                if not match:
                    raise DataError('工作表单元格坐标无效。')
                col = 0
                for c in match[1]: col = col * 26 + ord(c) - 64
                if col > 64: raise DataError('工作表最多支持 64 列。')
                if col-1 in cells:raise DataError('工作表含重复单元格坐标。')
                if cell.find('s:f', ns) is not None:
                    raise DataError(f'{ref} 含公式，请先复制并粘贴为数值后上传。')
                v = cell.findtext('s:v', '', ns)
                if cell.get('t') == 's':
                    try:
                        index=int(v)
                        if not 0<=index<len(strings):raise IndexError()
                        v = strings[index]
                    except (ValueError, IndexError): raise DataError('共享文本索引无效。') from None
                elif cell.get('t') == 'inlineStr': v = ''.join(cell.find('s:is', ns).itertext())
                elif cell.get('t') in ('e', 'b'): raise DataError(f'{ref} 为错误值或布尔值。')
                cells[col - 1] = v
            if cells: result.append([cells.get(i, '') for i in range(max(cells) + 1)])
            if len(result) > MAX_ROWS + 1: raise DataError('最多支持 6000 行日度汇总数据。')
        return result


def read_rows(filename, raw):
    ext = filename.lower().rsplit('.', 1)[-1]
    if ext == 'xlsx': return xlsx_rows(raw)
    if ext != 'csv': raise DataError('数据文件仅支持 .csv 或 .xlsx。')
    try: content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try: content = raw.decode('gb18030')
        except UnicodeDecodeError: raise DataError('CSV 请使用 UTF-8 或 GB18030 编码。') from None
    csv.field_size_limit(4096)
    try:
        rows = []
        for row in csv.reader(io.StringIO(content)):
            if len(row) > 64: raise DataError('CSV 最多支持 64 列。')
            if any(x.strip() for x in row): rows.append(row)
            if len(rows) > MAX_ROWS + 1: raise DataError('最多支持 6000 行日度汇总数据。')
        return rows
    except csv.Error: raise DataError('CSV 格式无效或单元格过长。') from None


def parse_panel(filename, raw):
    rows = read_rows(filename, raw)
    if len(rows) < 2: raise DataError('文件须包含表头和至少一行数据。')
    headers = [ALIASES.get(v.strip()) for v in rows[0]]
    unknown = [v for v, key in zip(rows[0], headers) if key is None]
    if unknown: raise DataError('无法识别列：' + '、'.join(unknown[:5]) + '。请按模板汇总；不接收姓名、证件号等个人信息。')
    if len(headers) != len(set(headers)): raise DataError('存在重复列名。')
    if not {'product_id', 'date', 'balance'} <= set(headers): raise DataError('至少需要产品编号、日期、资产池余额三列。')
    result, seen, issues = {}, set(), []
    for i, values in enumerate(rows[1:], 2):
        if len(values) > len(headers): raise DataError(f'第 {i} 行列数超过表头。')
        values += [''] * (len(headers) - len(values))
        record = {k: None for k in KEYS}
        for key, raw_value in zip(headers, values):
            value = raw_value.strip()
            if not value: continue
            if key in ('product_id', 'product_name', 'policy'):
                limit = 80 if key != 'policy' else 240
                if len(value) > limit or any(ord(c) < 32 for c in value): raise DataError(f'第 {i} 行 {key} 过长或含控制字符。')
                if key == 'product_id' and not re.fullmatch(r'[A-Za-z0-9_\-\u4e00-\u9fff]{1,60}', value): raise DataError(f'第 {i} 行产品编号只能含中文、字母、数字、横线和下划线。')
                record[key] = value
            elif key == 'date':
                try:
                    dt = date.fromisoformat(value) if '-' in value else date(1899, 12, 30) + timedelta(days=int(float(value)))
                    if not date(2000, 1, 1) <= dt <= date(2100, 1, 1): raise ValueError()
                    record[key] = dt.isoformat()
                except (ValueError, OverflowError): raise DataError(f'第 {i} 行日期请填写 YYYY-MM-DD。') from None
            else:
                try: number = float(value[:-1]) / 100 if value.endswith('%') and key in RATIOS else float(value)
                except ValueError: raise DataError(f'第 {i} 行 {key} 不是数值。') from None
                if not math.isfinite(number) or abs(number) > 1e16: raise DataError(f'第 {i} 行 {key} 数值超限。')
                if number!=0 and abs(number)<1e-12:raise DataError(f'第 {i} 行 {key} 数值过小，请检查单位。')
                if number < 0 and key not in ('post_waterfall', 'income_growth', 'cpi'): raise DataError(f'第 {i} 行 {key} 不能为负数。')
                if key in RATIOS and abs(number) > 1: raise DataError(f'第 {i} 行 {key} 请用小数比率或百分号，例如 0.03 或 3%。')
                if key in ('loan_count', 'a_maturity', 'b_maturity', 'sub_maturity') and (number != int(number) or number > 1e10): raise DataError(f'第 {i} 行 {key} 须为整数。')
                record[key] = number
        if not record['product_id'] or not record['date'] or record['balance'] is None: raise DataError(f'第 {i} 行缺少产品编号、日期或余额。')
        identity = (record['product_id'], record['date'])
        if identity in seen: raise DataError(f'第 {i} 行产品与日期重复；请勿混合总表和分表。')
        seen.add(identity)
        for key in ('dpd1_balance', 'dpd30_balance', 'dpd90_balance', 'max_province_balance', 'top10_balance', 'balance_pd'):
            if record[key] is not None and record[key] > record['balance'] + .01: raise DataError(f'第 {i} 行 {key} 超过资产池余额。')
        for small,large in [('dpd90_balance','dpd30_balance'),('dpd30_balance','dpd1_balance'),('dpd90_balance','dpd1_balance')]:
            if record[small] is not None and record[large] is not None and record[small]>record[large]:raise DataError(f'第 {i} 行逾期余额应满足 DPD90+ ≤ DPD30+ ≤ DPD1+。')
        if record['pd_covered_balance'] is not None:
            if record['pd_covered_balance']>record['balance'] or record['balance_pd'] is not None and record['balance_pd']>record['pd_covered_balance']:
                raise DataError(f'第 {i} 行须满足 余额乘PD合计 ≤ 有PD的余额 ≤ 资产池余额。')
        if record['cumulative_defaults'] is not None and record['original_balance'] is not None and record['cumulative_additions'] is not None and record['cumulative_defaults']>record['original_balance']+record['cumulative_additions']:
            raise DataError(f'第 {i} 行累计违约本金超过累计入池本金。')
        if all(record[k] is not None for k in ('a_balance', 'b_balance', 'sub_balance', 'security_balance')) and abs(sum(record[k] for k in ('a_balance', 'b_balance', 'sub_balance')) - record['security_balance']) > max(.01, record['security_balance'] * .000001):
            raise DataError(f'第 {i} 行各档本金与证券总余额不一致。')
        result.setdefault(record['product_id'], []).append(record)
        if len(result) > 20: raise DataError('一次最多支持 20 只产品。')
    for pid, panel in result.items():
        panel.sort(key=lambda r: r['date'])
        dates = [date.fromisoformat(r['date']) for r in panel]
        gaps = sum((b - a).days != 1 for a, b in zip(dates, dates[1:]))
        if gaps: issues.append(f'{pid} 有 {gaps} 处日期不连续，涉及这些窗口的指标待评估。')
        missing = [name for key, name, _ in FIELDS if key not in ('product_name', 'policy') and any(r[key] is None for r in panel)]
        if missing: issues.append(f'{pid} 缺失字段：' + '、'.join(missing))
    return result, issues


def demo_rows():
    rows = []
    for j in range(3):
        initial = 100_000_000 * (j + 1)
        cumulative, additions = 0., 0.
        for t in range(180):
            balance = initial * (1 - (.0007 + .00035 * j) * t)
            rate = .12 - .008 * j - .00004 * t
            default = balance * (.000025 + j * .00002 + t * j * .0000003)
            cumulative += default; additions += balance * (.0013 if j==0 else .0005)
            security = initial * (.86 if j==1 else .94) * (1 - .0008 * t)
            dpd = .015 + j * .009 + t * .000035 * (j + 1)
            r = dict.fromkeys(KEYS)
            r.update(product_id=f'SIM-ABS-0{j+1}', product_name=['华东消费贷 · 合成样本', '华南青年客群 · 合成样本', '全国小额贷 · 合成样本'][j], date=(date(2026, 3, 5) + timedelta(days=t)).isoformat(),
                balance=balance, loan_count=round(balance/(8000 + 20*t)), dpd1_balance=balance*min(dpd*1.5,1), dpd30_balance=balance*dpd, dpd90_balance=balance*dpd*.32,
                new_defaults=default, performing_open=balance*(1-dpd*.32)+default, cumulative_defaults=cumulative, original_balance=initial, cumulative_additions=additions,
                scheduled_principal=balance*.0017, prepayments=balance*(.0003 + (.001 if j == 1 and t > 135 else 0)),
                balance_term=balance*(12-t/30*.6), balance_rate=balance*rate, balance_pd=balance*(.025+j*.016), pd_covered_balance=balance, duration_pv_time=balance*(6-t/30*.3)/12, duration_pv=balance, principal_time=balance*(6.5-t/30*.3), future_principal=balance,
                max_province_balance=balance*(.20+.06*j), top10_balance=balance*(.30+.055*j), new_assets=balance*(.0013 if j==0 else .0005), maturing_assets=balance*.0012,
                security_balance=security, security_rate=.042, available_cash=balance*.0024, debt_due=security*.002, reserve=initial*(.018-.00003*t*j),
                post_waterfall=balance*(.00015-.00009*j), asset_interest=balance*rate/365, security_interest=security*.042/365,
                unemployment=.05+.001*j+.000008*t, income_growth=.04-.00016*t*j, cpi=.018+.00004*t, confidence=103-.04*t*(j+1), lpr=.035,
                policy='演示：催收流程合规复核' if j==2 and t>=165 else '无新增政策（合成示例，已核查）', forecast_ccr=.03,
                a_balance=security*.8, b_balance=security*.12, sub_balance=security*.08, a_rate=.035, b_rate=.055, sub_rate=.075,
                a_maturity=9, b_maturity=12, sub_maturity=12)
            rows.append({k: round(v, 8) if isinstance(v, float) else v for k, v in r.items()})
    return rows


def csv_bytes(rows):
    out = io.StringIO(newline='')
    writer = csv.writer(out); writer.writerow([f[1] for f in FIELDS])
    for row in rows: writer.writerow([row.get(k, '') for k in KEYS])
    return ('\ufeff' + out.getvalue()).encode('utf-8')


def xlsx_bytes(rows):
    def col(n):
        s = ''
        while n: n, rem = divmod(n-1,26); s=chr(65+rem)+s
        return s
    def sheet(values):
        result = []
        for i, row in enumerate(values, 1):
            cells = []
            for j, v in enumerate(row, 1):
                ref = f'{col(j)}{i}'
                cells.append(f'<c r="{ref}"><v>{v}</v></c>' if isinstance(v,(int,float)) else f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v or ""))}</t></is></c>')
            result.append(f'<row r="{i}">'+''.join(cells)+'</row>')
        return '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(result)+'</sheetData></worksheet>'
    out = io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="资产池日度" sheetId="1" r:id="r1"/><sheet name="字段说明" sheetId="2" r:id="r2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',sheet([[f[1] for f in FIELDS]]+[[r.get(k,'') for k in KEYS] for r in rows]))
        z.writestr('xl/worksheets/sheet2.xml',sheet([['字段','机器字段名','单位'],*[[n,k,u] for k,n,u in FIELDS],['口径','一只产品每日一行；金额为元，期限为月，利率用0.03或3%。日流量勿填累计值。',''],['空值','留空表示缺失，不能用0代替。仅上传去标识化汇总。',''],['WAL','用未来计划本金乘回款月数合计/未来计划本金合计；只有余额加权剩余期限时明确作为代理。',''],['CDR/CPR','按完整自然月逐日生存率连乘、365/该月天数年化。新增违约仅首次跨90日，不重复计算存量。',''],['样本','SIM-ABS 为可复现数学合成数据，不是真实客户或证券。','']]))
    return out.getvalue()


def contract_text(filename, raw):
    if filename.lower().endswith('.docx'):
        with archive(raw) as z:
            if 'word/document.xml' not in z.namelist(): raise DataError('不是有效的 DOCX 合约。')
            root=xml(z.read('word/document.xml'))
            content='\n'.join(''.join(p.itertext()) for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
    elif filename.lower().endswith('.txt'):
        try: content=raw.decode('utf-8-sig')
        except UnicodeDecodeError: raise DataError('TXT 合约请使用 UTF-8 编码。') from None
    else: raise DataError('合约支持 PDF、DOCX 或 UTF-8 TXT，请选择相应文件。')
    if not 20 <= len(content) <= 30000: raise DataError('合约文字须为 20–30000 字；请上传涉及触发阈值的条款节选。')
    return content
