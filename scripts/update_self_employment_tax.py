#!/usr/bin/env python3
import hashlib, html as htmlmod, json, re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

OUT = Path(__file__).resolve().parents[1] / 'self-employment-tax.json'
SSA_URL = 'https://www.ssa.gov/OACT/cola/cbb.html'
LAW_1401 = 'https://uscode.house.gov/view.xhtml?edition=prelim&req=granuleid%3AUSC-prelim-title26-section1401'
LAW_1402 = 'https://uscode.house.gov/view.xhtml?edition=prelim&req=granuleid%3AUSC-prelim-title26-section1402'
IRS_505 = 'https://www.irs.gov/publications/p505'
IRS_560 = 'https://www.irs.gov/taxtopics/tc560'

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]
    def handle_data(self, data):
        self.parts.append(data)

def fetch_text(url):
    req = Request(url, headers={
        'User-Agent':'Mozilla/5.0 NumerosLiveRules/1.0 (+https://www.numeros.pro/)',
        'Accept':'text/html,application/xhtml+xml'
    })
    with urlopen(req, timeout=35) as r:
        raw = r.read().decode('utf-8', 'replace')
    p = TextExtractor(); p.feed(raw)
    return re.sub(r'\s+', ' ', htmlmod.unescape(' '.join(p.parts))).strip()

def money_int(s):
    return int(re.sub(r'[^0-9]', '', s))

def extract_ssa_bases(text):
    found = {}
    for year_s, amount_s in re.findall(r'\b(20\d{2})\b\s+\$?([0-9]{2,3}(?:,[0-9]{3})+)', text):
        year = int(year_s); amount = money_int(amount_s)
        if 2022 <= year <= datetime.now(timezone.utc).year + 1 and 100000 <= amount <= 500000:
            found[year] = amount
    return found

def extract_irs505_current_base(text):
    # Pub. 505 current-year worksheet states both the worksheet year and the maximum
    # income subject to Social Security tax. This is the official fallback when SSA
    # blocks automated GitHub runner requests.
    years = [int(y) for y in re.findall(r'Worksheet 2-3\.\s*(20\d{2})|Worksheet 2-3\.(20\d{2})', text) for y in y if y]
    current_year = max(years) if years else datetime.now(timezone.utc).year
    patterns = [
        r'Maximum income subject to social security tax.{0,160}?\$\s*([0-9]{2,3}(?:,[0-9]{3})+)',
        r'Maximum income subject to Social Security tax.{0,160}?\$\s*([0-9]{2,3}(?:,[0-9]{3})+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            amount = money_int(m.group(1))
            if 100000 <= amount <= 500000:
                return current_year, amount
    raise RuntimeError('Could not verify current Social Security wage base from IRS Publication 505')

def section_core(text, section_number):
    patterns = [f'§{section_number}.', f'§ {section_number}.', f'{section_number}.']
    start = -1
    for marker in patterns:
        pos = text.find(marker)
        if pos >= 0:
            start = pos; break
    if start < 0:
        raise RuntimeError(f'Could not locate Section {section_number} operative text')
    core = text[start:]
    cut_positions = []
    for marker in ['Source Credit', 'References in Text', 'Amendments', 'Effective Date', 'Savings Provision']:
        pos = core.find(marker)
        if pos > 500:
            cut_positions.append(pos)
    if cut_positions:
        core = core[:min(cut_positions)]
    core = re.sub(r'\s+', ' ', core).strip()
    if len(core) < 500:
        raise RuntimeError(f'Section {section_number} operative text was unexpectedly short')
    return core

def validate_core_markers(law1401, law1402, irs505, irs560):
    checks = {
        'ss_rate_12_4': bool(re.search(r'12\.4 percent', law1401, re.I)),
        'medicare_rate_2_9': bool(re.search(r'2\.9 percent', law1401, re.I)),
        'additional_medicare_0_9': bool(re.search(r'0\.9 percent', law1401, re.I)),
        'minimum_400': bool(re.search(r'less than \$\s*400', law1402, re.I)),
        'wage_base_coordination': bool(re.search(r'contribution and benefit base.*?minus.*?wages', law1402, re.I)),
        'factor_92_35': bool(re.search(r'92\.35%|92\.35 percent|0\.9235', irs505, re.I)),
        'half_deduction_50': bool(re.search(r'Multiply line 10 by 50%|one-half of (?:the )?self-employment tax', irs505, re.I)),
        'amt_rate_0_9': bool(re.search(r'0\.9%|0\.9 percent', irs560, re.I)),
        'amt_joint_250000': bool(re.search(r'250,000', irs560)),
        'amt_mfs_125000': bool(re.search(r'125,000', irs560)),
        'amt_other_200000': bool(re.search(r'200,000', irs560)),
        'amt_wage_coordination': bool(re.search(r'reducing the applicable threshold.*?Medicare wages|threshold.*?reduced.*?wages', irs560, re.I)),
    }
    missing = [k for k,v in checks.items() if not v]
    if missing:
        raise RuntimeError('Core-rule marker verification failed: ' + ', '.join(missing))

def law_signature(law1401, law1402):
    core1401 = section_core(law1401, '1401')
    core1402 = section_core(law1402, '1402')
    canonical = '26-USC-1401\n' + core1401 + '\n26-USC-1402\n' + core1402
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def main():
    data = json.loads(OUT.read_text(encoding='utf-8'))
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

    law1401 = fetch_text(LAW_1401)
    law1402 = fetch_text(LAW_1402)
    irs505 = fetch_text(IRS_505)
    irs560 = fetch_text(IRS_560)

    try:
        validate_core_markers(law1401, law1402, irs505, irs560)
        signature = law_signature(law1401, law1402)
    except Exception as exc:
        data['law']['status'] = 'review-required'
        data['law']['reason'] = str(exc)
        data['law']['checkedAt'] = now_iso
        data['checkedAt'] = now_iso
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        raise

    old_sig = data.get('law', {}).get('signatureSha256')
    if old_sig and old_sig != signature:
        data['law']['status'] = 'review-required'
        data['law']['reason'] = 'Official operative text in 26 U.S.C. §§ 1401/1402 changed from the verified baseline.'
        data['law']['currentSignatureSha256'] = signature
        data['law']['checkedAt'] = now_iso
        data['checkedAt'] = now_iso
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        raise SystemExit('Safety stop: self-employment tax law changed; review required.')

    data['law']['status'] = 'current'
    data['law']['signatureSha256'] = signature
    data['law']['checkedAt'] = now_iso
    data['law'].pop('reason', None)
    data['law'].pop('currentSignatureSha256', None)

    history = {int(x['year']): int(x['socialSecurityWageBase']) for x in data.get('history', [])}
    wage_base_source = None
    latest_year = None
    latest_base = None

    try:
        ssa = fetch_text(SSA_URL)
        bases = extract_ssa_bases(ssa)
        if bases:
            history.update(bases)
            latest_year = max(bases)
            latest_base = bases[latest_year]
            wage_base_source = 'SSA Contribution and Benefit Base'
    except Exception as exc:
        print(f'SSA fetch unavailable ({exc}); verifying wage base from IRS Publication 505 instead.')

    if latest_base is None:
        latest_year, latest_base = extract_irs505_current_base(irs505)
        history[latest_year] = latest_base
        wage_base_source = 'IRS Publication 505 fallback'

    data['latestYear'] = latest_year
    data['current']['year'] = latest_year
    data['current']['socialSecurityWageBase'] = latest_base
    data['history'] = [
        {'year': y, 'socialSecurityWageBase': history[y]}
        for y in sorted(history)
        if y >= 2022
    ]
    data['sourceStatus'] = 'verified'
    data['wageBaseSourceUsed'] = wage_base_source
    data['checkedAt'] = now_iso
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Law current; latest wage base: {latest_year} ${latest_base:,} via {wage_base_source}')

if __name__ == '__main__':
    main()
