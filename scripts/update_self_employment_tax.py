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

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]
    def handle_data(self, data):
        self.parts.append(data)

def fetch_text(url):
    req = Request(url, headers={'User-Agent':'NumerosLiveRules/1.0 (+https://www.numeros.pro/)'})
    with urlopen(req, timeout=35) as r:
        raw = r.read().decode('utf-8', 'replace')
    p = TextExtractor(); p.feed(raw)
    return re.sub(r'\s+', ' ', htmlmod.unescape(' '.join(p.parts))).strip()

def money_int(s):
    return int(re.sub(r'[^0-9]', '', s))

def extract_ssa_bases(text):
    # SSA's table exposes year + taxable maximum pairs. Keep only modern plausible values.
    found = {}
    for year_s, amount_s in re.findall(r'\b(20\d{2})\b\s+\$?([0-9]{2,3}(?:,[0-9]{3})+)', text):
        year = int(year_s); amount = money_int(amount_s)
        if 2022 <= year <= datetime.now(timezone.utc).year + 1 and 100000 <= amount <= 500000:
            found[year] = amount
    return found

def core_signature(law1401, law1402, irs505):
    checks = {
        'ss_rate_12_4': bool(re.search(r'12\.4 percent', law1401, re.I)),
        'medicare_rate_2_9': bool(re.search(r'2\.9 percent', law1401, re.I)),
        'additional_medicare_0_9': bool(re.search(r'0\.9 percent', law1401, re.I)),
        'joint_threshold_250000': bool(re.search(r'\$\s*250,000', law1401)),
        'other_threshold_200000': bool(re.search(r'\$\s*200,000', law1401)),
        'minimum_400': bool(re.search(r'less than \$\s*400', law1402, re.I)),
        'wage_base_reduction': bool(re.search(r'contribution and benefit base.*?minus.*?wages', law1402, re.I)),
        'factor_92_35': bool(re.search(r'92\.35%|92\.35 percent|0\.9235', irs505, re.I)),
        'half_deduction': bool(re.search(r'Multiply line 10 by 50%|one-half of self-employment tax', irs505, re.I)),
    }
    if not all(checks.values()):
        missing = [k for k,v in checks.items() if not v]
        raise RuntimeError('Core-rule marker verification failed: ' + ', '.join(missing))
    canonical = '|'.join(k + '=1' for k in sorted(checks))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def main():
    data = json.loads(OUT.read_text(encoding='utf-8'))
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

    law1401 = fetch_text(LAW_1401)
    law1402 = fetch_text(LAW_1402)
    irs505 = fetch_text(IRS_505)

    try:
        signature = core_signature(law1401, law1402, irs505)
    except Exception as exc:
        data['law']['status'] = 'review-required'
        data['law']['reason'] = str(exc)
        data['checkedAt'] = now_iso
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        raise

    old_sig = data.get('law', {}).get('signatureSha256')
    if old_sig and old_sig != signature:
        data['law']['status'] = 'review-required'
        data['law']['reason'] = 'Core Section 1401/1402/IRS Schedule SE markers changed from the verified baseline.'
        data['law']['currentSignatureSha256'] = signature
        data['checkedAt'] = now_iso
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        raise SystemExit('Safety stop: self-employment tax core rules changed; review required.')

    data['law']['status'] = 'current'
    data['law']['signatureSha256'] = signature
    data['law'].pop('reason', None)
    data['law'].pop('currentSignatureSha256', None)

    ssa = fetch_text(SSA_URL)
    bases = extract_ssa_bases(ssa)
    if not bases:
        raise SystemExit('Safety stop: no plausible SSA wage-base values detected; existing data preserved.')

    latest_year = max(bases)
    latest_base = bases[latest_year]
    history = {int(x['year']): int(x['socialSecurityWageBase']) for x in data.get('history', [])}
    history.update(bases)

    data['latestYear'] = latest_year
    data['current']['year'] = latest_year
    data['current']['socialSecurityWageBase'] = latest_base
    data['history'] = [
        {'year': y, 'socialSecurityWageBase': history[y]}
        for y in sorted(history)
        if y >= 2022
    ]
    data['sourceStatus'] = 'verified'
    data['checkedAt'] = now_iso
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Law current; latest SSA wage base: {latest_year} ${latest_base:,}')

if __name__ == '__main__':
    main()
