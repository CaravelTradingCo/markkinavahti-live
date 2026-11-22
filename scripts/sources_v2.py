"""Markkinavahti: point-in-time dataset builder for personal research.

Market quotes: delayed Yahoo Finance via unofficial yfinance; subject to availability
and Yahoo's terms. Physical commodity benchmarks: World Bank monthly Pink Sheet.
Uranium IMF monthly benchmark: FRED PURANUSDM, with attribution and a caveat
that redistributing copyrighted IMF data commercially requires permission.
Specialty metals: only user-supplied, source-documented observations.
No pretend prices, no daily/physical benchmark conflation.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
import re
import sys
import time
from datetime import datetime, timezone, date
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / 'data'
OUTPUT = DATA_DIR / 'latest.json'
WORLD_BANK_URL = 'https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx'
FRED_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=PURANUSDM'

MARKETS = {
    'SPY': ('S&P 500', 'Indeksi'), 'QQQ': ('Nasdaq 100', 'Indeksi'),
    'IWM': ('Russell 2000', 'Indeksi'), 'DIA': ('Dow Jones', 'Indeksi'),
    'XLK': ('Teknologia', 'Sektori'), 'XLC': ('Viestintä', 'Sektori'),
    'XLY': ('Kulutus: syklinen', 'Sektori'), 'XLF': ('Rahoitus', 'Sektori'),
    'XLI': ('Teollisuus', 'Sektori'), 'XLB': ('Materiaalit', 'Sektori'),
    'XLE': ('Energia', 'Sektori'), 'XLV': ('Terveydenhuolto', 'Sektori'),
    'XLP': ('Päivittäistavarat', 'Sektori'), 'XLU': ('Yhdyskuntapalvelut', 'Sektori'),
    'XLRE': ('Kiinteistöt', 'Sektori'),
    'COPX': ('Kuparikaivosyhtiöt', 'Teema'), 'URA': ('Uraaniosakkeet', 'Teema'),
    'URNM': ('Uraanikaivosyhtiöt', 'Teema'), 'LIT': ('Litium- ja akkuketju', 'Teema'),
    'REMX': ('Harvinaiset maametallit', 'Teema'), 'GDX': ('Kultakaivosyhtiöt', 'Teema'),
    'PICK': ('Kaivos- ja metalliyhtiöt', 'Teema'), 'SMH': ('Puolijohteet', 'Teema'),
    'BOTZ': ('Robotiikka ja AI', 'Teema'), 'URA': ('Uraaniosakkeet', 'Teema'),
    'MP': ('MP Materials', 'Seurantalista'), 'UUUU': ('Energy Fuels', 'Seurantalista'),
    'ALB': ('Albemarle', 'Seurantalista'), 'EQR.AX': ('EQ Resources', 'Seurantalista'),
    'NVDA': ('Nvidia', 'Seurantalista'),
    'VR8.AX': ('Vanadium Resources', 'Seurantalista'),
    'VBX.AX': ('VBX Limited', 'Seurantalista'),
    'VNP.TO': ('5N Plus', 'Seurantalista'),
    'MTLN.L': ('METLEN Energy & Metals', 'Seurantalista'),
}

QUOTE_CURRENCY={'EQR.AX':'AUD','VR8.AX':'AUD','VBX.AX':'AUD',
                'VNP.TO':'CAD','MTLN.L':'EUR'}

# Financial futures are NOT equivalent to physical spot cash/contract benchmarks.
FUTURES = {
    'HG=F': ('Kupari – COMEX-futuuri', 'USD/lb', 'Teollisuusmetallit'),
    'GC=F': ('Kulta – COMEX-futuuri', 'USD/oz', 'Jalometallit'),
    'SI=F': ('Hopea – COMEX-futuuri', 'USD/oz', 'Jalometallit'),
    'CL=F': ('WTI-öljy – NYMEX-futuuri', 'USD/bbl', 'Energia'),
    'NG=F': ('Maakaasu – Henry Hub -futuuri', 'USD/MMBtu', 'Energia'),
}

# World Bank canonical columns (with tolerance for naming changes). Units are
# extracted from the workbook's own units row whenever possible.
PHYSICAL = {
    'copper': ('Kupari', ['Copper'], 'USD/tonni', 'Teollisuusmetallit'),
    'aluminum': ('Alumiini', ['Aluminum', 'Aluminium'], 'USD/tonni', 'Teollisuusmetallit'),
    'nickel': ('Nikkeli', ['Nickel'], 'USD/tonni', 'Teollisuusmetallit'),
    'zinc': ('Sinkki', ['Zinc'], 'USD/tonni', 'Teollisuusmetallit'),
    'tin': ('Tina', ['Tin'], 'USD/tonni', 'Teollisuusmetallit'),
    'lead': ('Lyijy', ['Lead'], 'USD/tonni', 'Teollisuusmetallit'),
    'gold': ('Kulta', ['Gold'], 'USD/troy oz', 'Jalometallit'),
    'silver': ('Hopea', ['Silver'], 'USD/troy oz', 'Jalometallit'),
    'platinum': ('Platina', ['Platinum'], 'USD/troy oz', 'Jalometallit'),
    'iron': ('Rautamalmi', ['Iron ore, cfr spot', 'Iron ore, cfr', 'Iron ore'], 'USD/dmt', 'Teollisuusmetallit'),
    'wti': ('WTI-raakaöljy', ['Crude oil, WTI', 'Crude oil, WTI spot'], 'USD/bbl', 'Energia'),
    'brent': ('Brent-raakaöljy', ['Crude oil, Brent'], 'USD/bbl', 'Energia'),
    'gas': ('Maakaasu, Yhdysvallat', ['Natural gas (U.S.)', 'Natural gas (U.S)', 'Natural gas (US)'], 'USD/MMBtu', 'Energia'),
    'coal': ('Kivihiili, Australia', ['Coal (Australia)', 'Coal, Australia'], 'USD/tonni', 'Energia'),
}

SPECIALTY = [
    ('lithium','Litiumkarbonaatti (akku)', 'Akkumetallit', 'Kiina', 'https://www.metal.com/lithium'),
    ('lithium_hydroxide','Litiumhydroksidi (akku)', 'Akkumetallit','Kiina','https://www.metal.com/lithium'),
    ('cobalt','Koboltti','Akkumetallit','Kiina / kansainvälinen','https://www.metal.com/cobalt'),
    ('tungsten','Volframi APT','Strategiset metallit','Kiina / Eurooppa','https://www.metal.com/tungsten'),
    ('vanadium','Vanadiinipentoksidi V₂O₅','Strategiset metallit','Kiina','https://www.metal.com/vanadium'),
    ('antimony','Antimoni','Strategiset metallit','Kiina / Eurooppa','https://www.metal.com/antimony'),
    ('gallium','Gallium 4N','Strategiset metallit','Kiina / Eurooppa','https://www.metal.com/minor-metals'),
    ('germanium','Germanium','Strategiset metallit','Kiina / Eurooppa','https://www.metal.com/minor-metals'),
    ('neodymium','NdPr-oksidi','Harvinaiset maametallit','Kiina','https://www.metal.com/rare-earth'),
    ('dysprosium','Dysprosiumoksidi','Harvinaiset maametallit','Kiina','https://www.metal.com/rare-earth'),
    ('terbium','Terbiumoksidi','Harvinaiset maametallit','Kiina','https://www.metal.com/rare-earth'),
    ('magnesium','Magnesiumharkko','Strategiset metallit','Kiina','https://www.metal.com/magnesium'),
    ('bauxite','Bauksiitti','Teollisuusmetallit','Kiina / kansainvälinen','https://www.metal.com/aluminum'),
]


def normalize(v):
    return re.sub(r'[^a-z0-9]+','',str(v).strip().lower())


def valid_num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (ValueError, TypeError):
        return None


def pct_change(points, back):
    if len(points) <= back:
        return None
    a = points[-1][1]; b = points[-back-1][1]
    return round((a / b - 1) * 100, 2) if b > 0 else None


def summarize_points(points, frequency):
    points = sorted({str(d): float(v) for d,v in points if valid_num(v) is not None}.items())
    if not points:
        return {'price':None, 'date':None, 'points':[], 'chg1':None, 'chg3':None, 'chg12':None,'chg60':None}
    back = [21,63,252,1260]
    tail = points[-1320:] if frequency == 'päivä' else points[-72:]
    if frequency == 'kuukausi':
        # Check matching calendar months; don't mislabel a gap as a 1-month move.
        current_y,current_m=map(int,points[-1][0][:7].split('-'))
        lookup={d[:7]:v for d,v in points}
        def monthly_change(months):
            total=current_y*12+current_m-1-months
            key=f'{total//12:04d}-{total%12+1:02d}'
            baseline=lookup.get(key)
            return round((points[-1][1]/baseline-1)*100,2) if baseline else None
        changes=[monthly_change(m) for m in (1,3,12,60)]
    else:
        changes=[pct_change(points,n) for n in back]
    return {'price': round(points[-1][1],5), 'date':points[-1][0], 'points':[[k,round(v,5)] for k,v in tail],
            'chg1':changes[0], 'chg3':changes[1],
            'chg12':changes[2], 'chg60':changes[3]}


def parse_worldbank_sheet(df):
    """Return {asset-id: summary}; scan for a header instead of fixed row offsets.

    Workbook convention: title, a header with 'Copper'/'Gold' etc,
    units on subsequent row, dates like 2026M10 below that.
    """
    header_idx = None
    for i in range(min(18,len(df))):
        row = [normalize(x) for x in df.iloc[i].tolist()]
        if 'copper' in row and 'gold' in row:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError('World Bank -tiedostosta ei löytynyt Monthly Prices -otsakkeita')
    columns = [(idx, normalize(x)) for idx,x in enumerate(df.iloc[header_idx].tolist())]
    output = {}
    for asset,(name, candidates, default_unit, group) in PHYSICAL.items():
        keys = [normalize(x) for x in candidates]
        # exact match first; partial only where name starts with candidate name.
        matching = [idx for idx, norm in columns if norm in keys]
        if not matching:
            matching = [idx for idx,norm in columns if any(norm.startswith(k) and k for k in keys)]
        if not matching:
            continue
        col = matching[0]
        points = []
        for i in range(header_idx + 1, len(df)):
            date_field = str(df.iat[i,0]).strip()
            m = re.match(r'^(\d{4})\s*[Mm]\s*(\d{1,2})$',date_field)
            if m:
                d = f'{m.group(1)}-{int(m.group(2)):02d}-01'
            else:
                # sometimes workbook may already contain real date types.
                val = df.iat[i,0]
                if hasattr(val,'year') and hasattr(val,'month'):
                    d = f'{val.year:04d}-{val.month:02d}-01'
                else:
                    continue
            v = valid_num(df.iat[i,col])
            if v is not None:
                points.append((d,v))
        if not points:
            continue
        s = summarize_points(points,'kuukausi')
        s.update({'id':asset, 'name':name,'group':group, 'unit':default_unit,
                  'market':'Maailman vertailuhinta', 'frequency':'kuukausi', 'type':'fyysinen',
                  'source':'World Bank – Pink Sheet', 'source_url':WORLD_BANK_URL})
        output[asset] = s
    return output


def fetch_worldbank(session):
    import pandas as pd
    resp = session.get(WORLD_BANK_URL,timeout=60)
    resp.raise_for_status()
    if not resp.content.startswith(b'PK'):
        raise ValueError('World Bank -vastaus ei ollut XLSX')
    wb = pd.read_excel(io.BytesIO(resp.content), sheet_name='Monthly Prices',header=None)
    return parse_worldbank_sheet(wb)


def parse_fred_csv(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    points=[]
    for row in reader:
        d = row.get('DATE') or row.get('observation_date') or row.get('date')
        v = valid_num(row.get('PURANUSDM'))
        if d and v is not None and re.match(r'^\d{4}-\d{2}-\d{2}$',d):
            points.append((d,v))
    if not points:
        raise ValueError('FRED-uraanisarjasta ei löytynyt havaintoja')
    s=summarize_points(points,'kuukausi')
    s.update({'id':'uranium','name':'Uraani U₃O₈ (IMF)', 'group':'Energia',
              'market':'Maailman kuukausikeskiarvo', 'unit':'USD/lb',
              'frequency':'kuukausi','type':'fyysinen', 'source':'IMF / FRED PURANUSDM',
              'source_url':'https://fred.stlouisfed.org/series/PURANUSDM'})
    return s


def fetch_fred(session):
    resp=session.get(FRED_URL,timeout=35)
    resp.raise_for_status()
    if 'PURANUSDM' not in resp.text[:400]:
        raise ValueError('FRED-palvelun vastaus ei ollut odotettu CSV')
    return parse_fred_csv(resp.text)


def parse_specialty(path):
    results=[]
    observations={}
    if path.exists():
        with path.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                rid=(row.get('id') or '').strip().lower()
                if rid not in {s[0] for s in SPECIALTY}: continue
                p=valid_num(row.get('price'))
                ds=(row.get('date') or '').strip()
                url=(row.get('source_url') or '').strip()
                unit=(row.get('unit') or '').strip()
                market=(row.get('market') or '').strip()
                if not p or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',ds) or not url.startswith('https://') or not unit or not market:
                    continue
                if date.fromisoformat(ds)>date.today(): continue
                observations.setdefault(rid,[]).append((ds,p,unit,market,url))
    for rid,name,group,market,reference in SPECIALTY:
        entries=sorted(observations.get(rid,[]))
        s={'id':rid,'name':name,'group':group,'market':market,'unit':None,
           'frequency':'erillinen','type':'erikoismetalli',
           'source':'Ei avointa vahvistettua hintasarjaa', 'source_url':reference,
           'price':None,'date':None,'points':[],'chg1':None,'chg3':None,'chg12':None,'chg60':None}
        if entries:
            latest=entries[-1]
            aligned=[(d,v) for d,v,u,m,url in entries if u==latest[2] and m==latest[3]]
            s.update({'price':latest[1], 'date':latest[0],'points':aligned[-60:],
                     'unit':latest[2],'market':latest[3],'source':'Oma lähdemerkintä – tarkistettava',
                     'source_url':latest[4]})
        results.append(s)
    return results


def flatten_yfinance(yf, tickers):
    """Download adjusted close to avoid split-related false trend changes."""
    import pandas as pd
    try:
        big=yf.download(tickers=tickers,period='5y',interval='1d',auto_adjust=True,
                        progress=False,threads=True,group_by='ticker',timeout=35)
    except TypeError:
        big=yf.download(tickers=tickers,period='5y',interval='1d',auto_adjust=True,
                        progress=False,threads=True,group_by='ticker')
    result={}
    if big is None or big.empty:
        raise RuntimeError('Yahoo Finance ei palauttanut hintasarjoja')
    for ticker in tickers:
        try:
            if isinstance(big.columns,pd.MultiIndex):
                if ticker in big.columns.get_level_values(0):
                    part=big[ticker]
                elif ticker in big.columns.get_level_values(1):
                    part=big.xs(ticker,axis=1,level=1)
                else:continue
            else:
                if len(tickers)>1:continue
                part=big
            c=part['Close'].dropna()
            pts=[]
            for day,value in c.items():
                v=valid_num(value)
                if v is not None:pts.append((str(day.date()),v))
            if len(pts)>25:result[ticker]=summarize_points(pts,'päivä')
        except (KeyError,AttributeError,TypeError):
            continue
    return result


def fetch_yahoo():
    import yfinance as yf
    tickers=list(MARKETS)+list(FUTURES)
    data=flatten_yfinance(yf,tickers)
    # If batch failed for an individual core index, retry once individually.
    for ticker in ['SPY','QQQ','IWM','DIA']:
        if ticker not in data:
            try: data.update(flatten_yfinance(yf,[ticker]))
            except Exception: pass
    return data


def load_previous(path=OUTPUT):
    try:
        x=json.loads(path.read_text(encoding='utf8'))
        return x if x.get('meta',{}).get('mode')=='live' else {}
    except (OSError,ValueError):return {}


def build(*, market_data, physical_data, specialty, errors=None, previous=None, now=None):
    """Separate provenance per asset; stale series can be reused transparently."""
    now=now or datetime.now(timezone.utc)
    errors=list(errors or []);previous=previous or {}
    old_markets=previous.get('markets',{})
    old_cmdty={r['id']:r for r in previous.get('commodities',[]) if 'id' in r}
    markets={}
    for ticker,(name,group) in MARKETS.items():
        data=market_data.get(ticker)
        if not data or not data.get('price'):
            data=old_markets.get(ticker)
        if not data or not data.get('price'):continue
        markets[ticker]={**data,'ticker':ticker,'name':name,'group':group,
             'source':'Yahoo Finance (viivästetty, epävirallinen)',
             'source_url':f'https://finance.yahoo.com/quote/{ticker.replace("=","%3D")}/',
             'frequency':'päivä','type':'ETF tai osake','unit':QUOTE_CURRENCY.get(ticker,'USD')}
    commodities=[]
    for ticker,(name,unit,group) in FUTURES.items():
        item=market_data.get(ticker)
        if not item or not item.get('price'):
            item=old_cmdty.get('future:'+ticker)
        if item and item.get('price'):
            commodities.append({**item,'id':'future:'+ticker,'name':name,'unit':unit,'group':group,
               'market':'Futuurin lähin sopimus, jatkuva sarja','frequency':'päivä',
               'type':'futuuri','source':'Yahoo Finance – futuuriproksi',
               'source_url':f'https://finance.yahoo.com/quote/{ticker.replace("=","%3D")}/'})
    for key in PHYSICAL:
        item=physical_data.get(key)
        if not item or not item.get('price'):item=old_cmdty.get(key)
        if item and item.get('price'):commodities.append(item)
    item=physical_data.get('uranium') or old_cmdty.get('uranium')
    if item and item.get('price'):commodities.append(item)
    commodities.extend(specialty)
    # Latest date shared by all four indices, not merely the newest individual quote.
    asof=min((markets[t]['date'] for t in ['SPY','QQQ','IWM','DIA'] if t in markets),default=None)
    wb_asof=max((r['date'] for r in commodities if r.get('type')=='fyysinen' and r.get('price') and r.get('date')),default=None)
    return {'meta':{'mode':'live','built_at_utc':now.isoformat(timespec='seconds').replace('+00:00','Z'),
             'market_asof':asof,'physical_asof':wb_asof,'errors':errors,
             'method':'päivä: auto-adjusted ETF/osake/futuuri; fyysinen: kuukausikeskiarvo; erikoishinnat: omat dokumentoidut havainnot'},
            'markets':markets,'commodities':commodities}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',default=str(OUTPUT));ap.add_argument('--strict',action='store_true')
    opts=ap.parse_args()
    import requests
    session=requests.Session()
    session.headers.update({'User-Agent':'Markkinavahti-personal-research/1.0'})
    errors=[];m={};p={}
    try:m=fetch_yahoo()
    except Exception as e:errors.append(f'Päiväkurssien haku epäonnistui: {str(e)[:180]}')
    try:p.update(fetch_worldbank(session))
    except Exception as e:errors.append(f'World Bank -hintojen haku epäonnistui: {str(e)[:180]}')
    try:p['uranium']=fetch_fred(session)
    except Exception as e:errors.append(f'FRED-uraanihinnan haku epäonnistui: {str(e)[:180]}')
    prev=load_previous(Path(opts.output))
    result=build(market_data=m,physical_data=p,specialty=parse_specialty(DATA_DIR/'specialty_prices.csv'),errors=errors,previous=prev)
    # Do not overwrite prior real data with an empty snapshot.
    if not all(t in result['markets'] for t in ('SPY','QQQ','IWM','DIA')):
        print('VIRHE: neljä keskeistä indeksiä puuttuu. Reaaliaineistoa ei kirjoiteta.',file=sys.stderr)
        sys.exit(2)
    if opts.strict and errors:
        print('Huomautukset:',*errors,sep='\n',file=sys.stderr)
    target=Path(opts.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print('Tallennettu:',target,'indeksipäivä:',result['meta']['market_asof'],
          'markkinasarjat:',len(result['markets']),'raaka-aineet:',len(result['commodities']))
    for err in errors:print('HUOM:',err)

if __name__=='__main__': main()
