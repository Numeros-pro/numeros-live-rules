#!/usr/bin/env python3
import hashlib, json, re, html as htmlmod
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

IRS_URL = 'https://www.irs.gov/individuals/international-taxpayers/figuring-the-foreign-earned-income-exclusion'
LAW_URL = 'https://uscode.house.gov/view.xhtml?req=(title:26%20section:911%20edition:prelim)'
OUT = Path(__file__).resolve().parents[1] / 'feie.json'

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]
    def handle_data(self, data):
        self.parts.append(data)

def fetch_text(url):
    req = Request(url, headers={'User-Agent':'NumerosLiveRules/1.0 (+https://www.numeros.pro/)'})
    with urlopen(req, timeout=30) as r:
        raw = r.read().decode('utf-8', 'replace')
    p = TextExtractor(); p.feed(raw)
    return re.sub(r'\s+', ' ', htmlmod.unescape(' '.join(p.parts))).strip()

def leap_days(year):
    return 366 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 365

def extract_rules(text):
    found = {}
    patterns = [
        r'For tax year\s+(20\d{2}),\s+the maximum(?: foreign earned income)? exclusion is\s+\$\s*([0-9]{2,3}(?:,[0-9]{3})+)',
        r'For tax year\s+(20\d{2}),\s+the maximum foreign earned income exclusion is the lesser of[^$]{0,180}\$\s*([0-9]{2,3}(?:,[0-9]{3})+)',
        r'(20\d{2})[^.]{0,180}maximum foreign earned income exclusion[^$]{0,120}\$\s*([0-9]{2,3}(?:,[0-9]{3})+)'
    ]
    now = datetime.now(timezone.utc).year
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            year = int(m.group(1)); limit = int(m.group(2).replace(',', ''))
            if 2022 <= year <= now + 1 and 100000 <= limit <= 1000000 and limit % 100 == 0:
                found[year] = {'year':year,'limit':limit,'days':leap_days(year)}
    return found

def normalize_law_text(text):
    start = text.find('§911.')
    if start < 0:
        start = text.find('Citizens or residents of the United States living abroad')
    core = text[start:] if start >= 0 else text
    for marker in ['Source Credit', 'References in Text', 'Amendments', 'Effective Date']:
        pos = core.find(marker)
        if pos > 1000:
            core = core[:pos]
            break
    return re.sub(r'\s+', ' ', core).strip()

def validate_expected_law_markers(core):
    required = [
        r'exclusion amount for any calendar year is \$80,000',
        r'substituting ["“]2004["”] for ["“]2016["”]',
        r'at least 330 full days',
        r'tax home is in a foreign country',
        r'foreign earned income'
    ]
    return all(re.search(p, core, re.I) for p in required)

def main():
    data = json.loads(OUT.read_text(encoding='utf-8'))
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

    law_text = fetch_text(LAW_URL)
    law_core = normalize_law_text(law_text)
    if not validate_expected_law_markers(law_core):
        data.setdefault('law', {})['status'] = 'review-required'
        data['law']['reason'] = 'Expected Section 911 core markers could not be verified.'
        data['law']['checkedAt'] = now_iso
        data['checkedAt'] = now_iso
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        raise SystemExit('Safety stop: Section 911 markers changed or could not be verified.')

    law_hash = hashlib.sha256(law_core.encode('utf-8')).hexdigest()
    law = data.setdefault('law', {})
    previous_hash = law.get('sectionTextSha256')
    if previous_hash and previous_hash != law_hash:
        law['status'] = 'review-required'
        law['reason'] = 'Official Section 911 operative text changed since the last verified baseline.'
        law['currentSectionTextSha256'] = law_hash
        law['checkedAt'] = now_iso
        data['checkedAt'] = now_iso
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        raise SystemExit('Safety stop: Section 911 changed; calculator review required.')

    law.update({
        'authority':'Office of the Law Revision Counsel, U.S. House of Representatives',
        'section':'26 U.S.C. § 911',
        'url':LAW_URL,
        'status':'current',
        'sectionTextSha256':law_hash,
        'checkedAt':now_iso
    })
    law.pop('reason', None)
    law.pop('currentSectionTextSha256', None)

    irs_text = fetch_text(IRS_URL)
    detected = extract_rules(irs_text)
    if not detected:
        data['checkedAt'] = now_iso
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        raise SystemExit('Safety stop: no valid IRS FEIE rule detected; existing values preserved.')

    existing = {int(x['year']):x for x in data.get('years', [])}
    for year, rule in detected.items():
        existing[year] = rule
    years = sorted(existing.values(), key=lambda x:int(x['year']), reverse=True)
    latest = years[0]

    data['latestYear'] = int(latest['year'])
    data['years'] = years
    data['source'] = {
        'authority':'Internal Revenue Service',
        'url':IRS_URL,
        'status':'github-pages-verified',
        'liveRule':latest
    }
    data['safety'] = {
        'fallbackAvailable':True,
        'neverGuessUnknownYear':True,
        'lawChangeBehavior':'pause-and-review',
        'validation':'Annual ceilings are accepted only from the IRS page after Section 911 passes the law guard.'
    }
    data['checkedAt'] = now_iso
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Law current; verified IRS years:', ', '.join(str(x['year']) for x in years))

if __name__ == '__main__':
    main()
