"""Fetch a source-attributed market-data snapshot for Markkinavahti LIVE.

Activation: run on GitHub Actions after US exchange close. None of the internet
connectors below are guaranteed; missing metrics fail closed rather than
masquerade as zero / invent a spot commodity price.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
import re
import time
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path
from urllib.parse import quote
import pandas as pd
import requests
from bs4 import BeautifulSoup
from engine import equity_indicators,breadth_from_closes,risk_score,nfloat
import sources_v2 as old

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
OUT=DATA/'latest.json'

INDICES={'SPY':'S&P 500 (ETF)', 'QQQ':'Nasdaq 100 (ETF)', 'IWM':'Russell 2000 (ETF)','DIA':'Dow Jones (ETF)'}
SECTORS={'XLK':'Teknologia','XLC':'Viestintä','XLY':'Syklinen kulutus','XLF':'Rahoitus',
         'XLI':'Teollisuus','XLB':'Materiaalit','XLE':'Energia','XLV':'Terveydenhuolto',
         'XLP':'Päivittäistavarat','XLU':'Yhdyskuntapalvelut','XLRE':'Kiinteistöt'}
THEMES={'COPX':'Kuparikaivokset','URA':'Uraaniosakkeet','URNM':'Uraanikaivosyhtiöt','LIT':'Litiumin arvoketju',
        'REMX':'Harvinaiset maametallit','GDX':'Kultakaivokset','PICK':'Metalli- ja kaivossektori',
        'SMH':'Puolijohteet','BOTZ':'Robotiikka ja tekoäly','XME':'Metalli- ja kaivososakkeet'}
STOCKS={
    'NVDA':('Nvidia','Tekoäly ja puolijohteet','USD'), '000660.KS':('SK hynix','Tekoäly ja puolijohteet','KRW'),
    'AMD':('AMD','Tekoäly ja puolijohteet','USD'), 'MU':('Micron','Tekoäly ja puolijohteet','USD'),
    'ASML':('ASML','Tekoäly ja puolijohteet','USD'),'TSM':('TSMC ADR','Tekoäly ja puolijohteet','USD'),
    'IREN':('IREN','Datakeskukset ja energia','USD'),'VRT':('Vertiv','Datakeskukset ja energia','USD'),
    'CEG':('Constellation Energy','Datakeskukset ja energia','USD'), 'GEV':('GE Vernova','Datakeskukset ja energia','USD'),
    'FCX':('Freeport-McMoRan','Kupari ja perusmetallit','USD'), 'SCCO':('Southern Copper','Kupari ja perusmetallit','USD'),
    'TECK':('Teck Resources','Kupari ja perusmetallit','USD'), 'BHP':('BHP ADR','Kupari ja perusmetallit','USD'),
    'RIO':('Rio Tinto ADR','Kupari ja perusmetallit','USD'),
    'CCJ':('Cameco','Uraani ja ydinvoima','USD'),'UUUU':('Energy Fuels','Uraani ja ydinvoima','USD'),
    'NXE':('NexGen Energy','Uraani ja ydinvoima','USD'), 'DNN':('Denison Mines','Uraani ja ydinvoima','USD'),
    'MP':('MP Materials','REE ja kriittiset metallit','USD'), 'EQR.AX':('EQ Resources','REE ja kriittiset metallit','AUD'),
    'VR8.AX':('Vanadium Resources','REE ja kriittiset metallit','AUD'),
    'VBX.AX':('VBX Limited','REE ja kriittiset metallit','AUD'),
    'VNP.TO':('5N Plus','REE ja kriittiset metallit','CAD'),
    'MTLN.L':('METLEN','REE ja kriittiset metallit','EUR'),
    'ALB':('Albemarle','Litium','USD'),'SQM':('SQM ADR','Litium','USD'),
    'NEM':('Newmont','Kulta','USD'), 'AEM':('Agnico Eagle','Kulta','USD'),
    'TER':('Teradyne','Robotiikka','USD'),'SYM':('Symbotic','Robotiikka','USD'),
    'GOOGL':('Alphabet','Laaja teknologia','USD'),'MSFT':('Microsoft','Laaja teknologia','USD'),
    'AMZN':('Amazon','Laaja teknologia','USD'), 'JPM':('JPMorgan','Rahoitus','USD'),
    'V':('Visa','Rahoitus','USD'), 'JNJ':('Johnson & Johnson','Terveydenhuolto','USD'),
    'LLY':('Eli Lilly','Terveydenhuolto','USD'), 'XOM':('Exxon Mobil','Energia','USD'),
    'CVX':('Chevron','Energia','USD'), 'CAT':('Caterpillar','Teollisuus','USD'),
    'LMT':('Lockheed Martin','Puolustus','USD'),
}
# These are FUTURES, not physical cash quotes. Contract rolls may shift the series.
FUTURES={
    'HG=F':('Kupari · COMEX-futuuri','USD/lb','Perusmetallit'),
    'GC=F':('Kulta · COMEX-futuuri','USD/troy oz','Jalometallit'),
    'SI=F':('Hopea · COMEX-futuuri','USD/troy oz','Jalometallit'),
    'CL=F':('WTI-öljy · NYMEX-futuuri','USD/bbl','Energia'),
    'NG=F':('Maakaasu · NYMEX-futuuri','USD/MMBtu','Energia'),
}
# Prices below are MONTHLY averages published with >= 30 day lag.
ISE_SPECS={
    'gallium_ise':('Gallium 99,99 %','Gallium','Strategiset metallit','EUR/kg'),
    'germanium_ise':('Germanium 99,99 %','Germanium','Strategiset metallit','EUR/kg'),
    'antimony_ise':('Antimoni 50 % (toimitettuna Kiinaan)','Antimon','Strategiset metallit','EUR/t Sb'),
    'tungsten_ise':('Volframi 88,5 % (ei APT)','Wolfram','Strategiset metallit','EUR/kg'),
    'neodymium_ise':('Neodyymi 99 % (ei NdPr-oksidi)','Neodym','Harvinaiset maametallit','EUR/kg'),
    'dysprosium_ise':('Dysprosium 99,5 % (ei oksidi)','Dysprosium','Harvinaiset maametallit','EUR/kg'),
    'terbium_ise':('Terbium 99,9 % (ei oksidi)','Terbium','Harvinaiset maametallit','EUR/kg'),
    'indium_ise':('Indium 99,995 %','Indium','Strategiset metallit','EUR/kg'),
}
ISE_URL='https://ise-metal-quotes.com/critical-raw-materials-monitor?l=en'
FEAR_API='https://feargreedflow.com/api/fear-greed'
FRED_VIX_URL='https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS'
CNN_API='https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
VIX_API='https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
SP500_URL='https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'



# Public daily metals price tables. Unofficial HTML integrations: if markup or
# attribution changes, record an error and leave the observation unavailable.
WESTMETALL={
    'lme_copper_cash':('Kupari – LME cash settlement','Cu','Perusmetallit'),
    'lme_aluminum_cash':('Alumiini – LME cash settlement','Al','Perusmetallit'),
    'lme_nickel_cash':('Nikkeli – LME cash settlement','Ni','Perusmetallit'),
    'lme_zinc_cash':('Sinkki – LME cash settlement','Zn','Perusmetallit'),
    'lme_tin_cash':('Tina – LME cash settlement','Sn','Perusmetallit'),
    'lme_lead_cash':('Lyijy – LME cash settlement','Pb','Perusmetallit'),
}
SMM_SPEC={
    'lithium_smm':('Battery-Grade Lithium Carbonate','SMM-Li-LC-001','Litiumkarbonaatti – SMM, akkul.','Akkumetallit'),
    'lithium_hydroxide_smm':('SMM Battery-Grade Lithium Hydroxide Index Price','SMM-Li-LH-001','Litiumhydroksidi – SMM-indeksi','Akkumetallit'),
    'copper_china_smm':('SMM 1# Copper Cathode','SMM-CU-RC-001','Kuparikatodi – SMM Kiina','Perusmetallit'),
    'aluminum_china_smm':('SMM A00 Aluminum Ingot','SMM-AL-AL-001','Alumiiniharkko – SMM Kiina','Perusmetallit'),
    'cobalt_china_smm':('China Cobalt Metal','SMM-CO-CM-001','Koboltti – SMM Kiina','Strategiset metallit'),
}
MONTHS={
    'january':1,'januar':1,'february':2,'februar':2,'march':3,'märz':3,
    'april':4,'may':5,'mai':5,'june':6,'juni':6,'july':7,'juli':7,
    'august':8,'september':9,'october':10,'oktober':10,'november':11,
    'december':12,'dezember':12,
}

def parse_westmetall_date(s):
    m=re.search(r'(\d{1,2})\.?\s+([A-Za-zÄäÖöÜü]+)\s+(\d{4})',str(s))
    if not m:return None
    month=MONTHS.get(m.group(2).casefold())
    if month is None:return None
    try:return date(int(m.group(3)),month,int(m.group(1))).isoformat()
    except ValueError:return None


def parse_westmetall_html(html,asset_id,url):
    name,short,group=WESTMETALL[asset_id]
    soup=BeautifulSoup(html,'html.parser');daily={}
    for tr in soup.find_all('tr'):
        cells=[td.get_text(' ',strip=True) for td in tr.find_all(['td'])]
        if len(cells)<2:continue
        ds=parse_westmetall_date(cells[0]);v=parse_locale_number(cells[1])
        if ds and v is not None and v>0 and date.fromisoformat(ds)<=date.today():daily[ds]=v
    if len(daily)<2:raise ValueError('LME/Westmetall-taulukosta ei löytynyt 2 päivää')
    pts=sorted(daily.items());summary=old.summarize_points(pts,'päivä')
    summary.update({'id':asset_id,'name':name,'group':group,'market':'LME cash settlement – Westmetall-julkaisu',
        'frequency':'päivä','type':'fyysinen päivähinta','unit':'USD/tonni',
        'source':'Westmetall – LME cash settlement','source_url':url,
        'note':'LME:n cash settlement -viitehinta Westmetallin julkaisemana; ei yksittäisen ostajan fyysisen toimituksen hinta.'})
    return summary


def fetch_westmetall(session):
    out=[]
    for key,(_,short,_) in WESTMETALL.items():
        url=f'https://www.westmetall.com/en/markdaten.php?action=table&field=LME_{short}_cash'
        try:
            r=session.get(url,timeout=20);r.raise_for_status()
            out.append(parse_westmetall_html(r.text,key,url))
        except Exception as e:print('LME/Westmetall',key,repr(e)[:130])
    return out


def parse_smm_html(html):
    soup=BeautifulSoup(html,'html.parser');out=[]
    for tr in soup.find_all('tr'):
        cells=[v.get_text(' ',strip=True) for v in tr.find_all(['td'])]
        if len(cells)<4:continue
        name=' '.join(cells[:2])
        hit=next(((key,row) for key,row in SMM_SPEC.items() if row[1].casefold() in name.casefold()),None)
        if not hit:continue
        key,(_,code,label,group)=hit
        prices=[(i,re.search(r'([0-9][0-9,.]*)\s*(USD/tonne|USD/kg|CNY/tonne|CNY/kg)',v,re.I)) for i,v in enumerate(cells)]
        prices=[x for x in prices if x[1]]
        if not prices:continue
        _,price=prices[0]
        value=parse_locale_number(price.group(1));unit=price.group(2)
        ds=next((safe_date(v) for v in cells if safe_date(v)),None)
        if value is None or ds is None or date.fromisoformat(ds)>date.today():continue
        out.append({'id':key,'name':label,'group':group,'price':nfloat(value,4),'date':ds,
                    'unit':unit,'market':name,'frequency':'päivä','type':'fyysinen päivähinta',
                    'source':'SMM / Metal.com – julkinen hintataulukko',
                    'source_url':'https://www.metal.com/','note':'Julkinen SMM-arvio; tuotemuoto ja SMM:n metodologia ovat hintakohtaisia. Automatiikan saatavuus riippuu palvelun käyttöehdoista ja sivuston rakenteesta.',
                    'points':[[ds,nfloat(value,4)]],'chg1':None,'chg3':None,'chg12':None,'chg60':None})
    # Dedupe on id with latest quote
    out_by_id={}
    for x in out:
        if x['id'] not in out_by_id or x['date']>out_by_id[x['id']]['date']:out_by_id[x['id']]=x
    return list(out_by_id.values())


def fetch_smm(session):
    combined=[]
    for url in ('https://www.metal.com/','https://www.metal.com/lithium'):
        try:
            r=session.get(url,timeout=20);r.raise_for_status()
            combined+=parse_smm_html(r.text)
        except Exception as e:print('SMM',url,repr(e)[:130])
    if not combined:raise ValueError('SMM:n julkisesta HTML-taulukosta ei löytynyt yhtään vahvistettua hintariviä')
    by_id={}
    for x in combined:
        if x['id'] not in by_id or x['date']>by_id[x['id']]['date']:by_id[x['id']]=x
    return list(by_id.values())


def safe_date(s):
    s=str(s).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',s):
        try: date.fromisoformat(s);return s
        except ValueError:pass
    return None


def last_good(out,prev,key):
    return out or prev.get(key)


def fetch_yfinance(tickers, *, period='2y', chunk=30, pause=1.0):
    """Yield split-adjusted OHLCV for valid symbols, without fake fills."""
    import yfinance as yf
    result={}
    tickers=list(dict.fromkeys(tickers))
    for ix in range(0,len(tickers),chunk):
        group=tickers[ix:ix+chunk]
        try:
            data=yf.download(group,period=period,interval='1d',auto_adjust=True,
                             group_by='ticker',threads=False,progress=False,timeout=25)
            if data is None or data.empty:continue
            for ticker in group:
                try:
                    if isinstance(data.columns,pd.MultiIndex):
                        if ticker in data.columns.get_level_values(0):df=data[ticker]
                        elif ticker in data.columns.get_level_values(1):df=data.xs(ticker,axis=1,level=1)
                        else: continue
                    else:
                        if len(group)!=1:continue
                        df=data
                    df=df[[col for col in ('Open','High','Low','Close','Volume') if col in df.columns]].dropna(subset=['Close'])
                    if len(df)>=20:result[ticker]=df
                except (KeyError,ValueError,TypeError):pass
        except Exception as e:print('Kurssierän virhe',ix,repr(e)[:160])
        if ix+chunk<len(tickers):time.sleep(pause)
    return result


def fetch_sp500_constituents(session):
    r=session.get(SP500_URL,timeout=25);r.raise_for_status()
    rows=list(csv.DictReader(io.StringIO(r.text)))
    tickers=list(dict.fromkeys((x.get('Symbol') or '').strip().replace('.','-') for x in rows))
    tickers=[t for t in tickers if t]
    if not 450<=len(tickers)<=525:raise ValueError('S&P500-jäsenluettelo ei ole odotetun kokoinen')
    return tickers


def get_vix(session):
    r=session.get(VIX_API,timeout=25);r.raise_for_status()
    rows=list(csv.DictReader(io.StringIO(r.text)))
    points=[]
    for row in rows:
        raw=row.get('DATE') or row.get('Date') or ''
        ds=safe_date(raw)
        if not ds:
            try:ds=datetime.strptime(raw,'%m/%d/%Y').date().isoformat()
            except ValueError:continue
        p=old.valid_num(row.get('CLOSE') or row.get('Close'))
        if p is not None:points.append((ds,p))
    if not points:raise ValueError('Cboe VIX CSV tyhjä')
    points.sort()
    return {'value':nfloat(points[-1][1]),'date':points[-1][0],'source':'Cboe – VIX, päätöskurssi',
            'url':'https://www.cboe.com/tradable_products/vix/vix_historical_data',
            'history':[[d,nfloat(v)] for d,v in points[-260:]]}


def get_vix_fred(session):
    """Fallback to a real historical Cboe VIX close republished by FRED.

    We never mix VIXCLS with a volatility ETF or an estimate.
    """
    response=session.get(FRED_VIX_URL,timeout=25)
    response.raise_for_status()
    points=[]
    for row in csv.DictReader(io.StringIO(response.text)):
        ds=safe_date(row.get('DATE') or row.get('observation_date') or '')
        value=old.valid_num(row.get('VIXCLS'))
        if ds and value is not None:
            points.append([ds,nfloat(value)])
    if not points:raise ValueError('FRED VIXCLS ei palauttanut vahvistettuja arvoja')
    points.sort(key=lambda x:x[0])
    return {'value':points[-1][1],'date':points[-1][0],
            'source':'Cboe VIX / FRED VIXCLS (varalähde)',
            'url':'https://fred.stlouisfed.org/series/VIXCLS','history':points[-260:]}


def get_fear(session):
    """Prefer CNN's index; third-party feed must be explicitly labeled."""
    try:
        r=session.get(CNN_API,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cnn.com/markets/fear-and-greed'},timeout=16)
        r.raise_for_status();data=r.json();item=data['fear_and_greed']
        value=float(item['score']);timestamp=item.get('timestamp')
        dt=(datetime.fromisoformat(timestamp.replace('Z','+00:00')).date().isoformat() if timestamp else None)
        hist=data.get('fear_and_greed_historical',{}).get('data',[])
        daily=[]
        for x in hist:
            try:daily.append([datetime.fromtimestamp(float(x['x'])/1000,timezone.utc).date().isoformat(),nfloat(x['y'])])
            except (KeyError,ValueError,TypeError):pass
        if 0<=value<=100 and dt:return {'value':nfloat(value,1),'date':dt,
                    'source':'CNN Fear & Greed (epävirallinen rajapintayhteys)',
                    'url':'https://www.cnn.com/markets/fear-and-greed','history':daily[-260:]}
    except Exception as e:
        print('CNN F&G ei saatavilla:',repr(e)[:130])
    r=session.get(FEAR_API,timeout=24);r.raise_for_status();data=r.json()
    ds=data.get('dates',[]);values=data.get('values',[])
    pts=[]
    for d,v in zip(ds,values):
        if safe_date(d) and v is not None:
            try:
                fv=float(v)
                if 0<=fv<=100:pts.append([d,nfloat(fv,1)])
            except (ValueError,TypeError):pass
    if not pts:raise ValueError('FearGreedFlow JSON tyhjä')
    pts.sort(key=lambda x:x[0])
    return {'value':pts[-1][1],'date':pts[-1][0],
            'source':'FearGreedFlow – kolmannen osapuolen F&G-sarja',
            'url':'https://feargreedflow.com/data','history':pts[-260:]}


def parse_locale_number(s):
    # e.g. 2.710,07 EUR -> 2710.07. Also tolerate 2710.07.
    cleaned=re.sub(r'[^0-9,.-]','',s).strip()
    if not cleaned:return None
    if ',' in cleaned and '.' in cleaned:
        cleaned=(cleaned.replace(',','') if cleaned.rfind('.')>cleaned.rfind(',') else cleaned.replace('.','').replace(',','.'))
    elif ',' in cleaned:
        cleaned=(cleaned.replace(',','') if re.fullmatch(r'-?\d{1,3}(,\d{3})+',cleaned) else cleaned.replace(',','.'))
    elif '.' in cleaned and re.fullmatch(r'-?\d{1,3}(\.\d{3})+',cleaned):
        cleaned=cleaned.replace('.','')
    try:
        n=float(cleaned)
        return n if math.isfinite(n) else None
    except ValueError:return None


def parse_ise_html(html):
    soup=BeautifulSoup(html,'html.parser')
    result=[]
    for tr in soup.select('tr'):
        cells=[x.get_text(' ',strip=True) for x in tr.select('td,th')]
        if len(cells)<6:continue
        metal,spec,avg,mom,change,rawdate=cells[:6]
        k=next((key for key,config in ISE_SPECS.items() if metal.casefold()==config[1].casefold()),None)
        if not k:continue
        try: ds=datetime.strptime(rawdate.strip(),'%d.%m.%Y').date().isoformat()
        except ValueError:continue
        if date.fromisoformat(ds)>date.today():continue
        price=parse_locale_number(avg)
        if price is None:continue
        name,match,group,unit=ISE_SPECS[k]
        result.append({'id':k,'name':name,'group':group,'price':nfloat(price,4),
             'date':ds,'frequency':'viive ≥30 pv, kuukausiarvo','unit':unit,
             'market':spec,'type':'fyysinen viiveellinen',
             'source':'ISE Critical Raw Materials Price Monitor','source_url':ISE_URL,
             'chg1':parse_locale_number(mom) if '%' in mom else None,
             'chg3':None,'chg12':None,'chg60':None, 'points':[[ds,nfloat(price,4)]],
             'note':'Julkinen hintavertailu vähintään 30 päivää jäljessä; ei spot-noteeraus. Tuotemuoto täsmälleen lähteen mukainen.'})
    return result


def get_ise(session):
    r=session.get(ISE_URL,timeout=35);r.raise_for_status()
    data=parse_ise_html(r.text)
    if len(data)<4:raise ValueError('ISE-taulukosta löytyi alle neljä noteerausta')
    return data


def as_futures(ticker,frame):
    name,unit,group=FUTURES[ticker]
    s=equity_indicators(frame)
    if not s:return None
    return {'id':'future:'+ticker,'name':name,'group':group,'price':s['close'],
            'date':s['date'],'unit':unit,'market':'Lähimmän sopimuksen jatkuva futuurisarja',
            'type':'futuuri','frequency':'päivä','source':'Yahoo Finance (viiveellinen; epävirallinen)',
            'source_url':'https://finance.yahoo.com/quote/'+quote(ticker,safe='')+'/',
            'chg1':s['pct20'],'chg3':s['pct60'],'chg12':s['pct252'],'chg60':None,
            'points':s['chart'],'note':'Futuurin sopimusvaihto voi aiheuttaa epäjatkuvuuksia; ei fyysinen spot-hinta.'}


def newest_by_id(*groups):
    out={}
    for group in groups:
        for x in group:
            if x and x.get('id') and (x.get('price') is not None or x.get('id') not in out):
                prior=out.get(x['id'])
                if prior is None or ((x.get('date') or '') >= (prior.get('date') or '')):out[x['id']]=x
    return list(out.values())


def stock_record(ticker,definition,frame):
    name,sector,currency=definition
    s=equity_indicators(frame,currency)
    if s:
        s.update({'ticker':ticker,'name':name,'sector':sector,'url':'https://finance.yahoo.com/quote/'+quote(ticker,safe='')+'/',
                  'source':'Yahoo Finance (viivästetty, epävirallinen)'})
    return s


def warn_if_stale(marketdate, datequote, max_days=7):
    if not marketdate or not datequote:return True
    try:return abs((date.fromisoformat(marketdate)-date.fromisoformat(datequote)).days)>max_days
    except ValueError:return True


def build_snapshot(*, frames, sp500_tickers=None, vix=None,fear=None,worldbank=None,uranium=None,
                   ise=None,special=None,daily_metals=None,previous=None,errors=None,utcnow=None):
    previous=previous or {};errors=list(errors or []);utcnow=utcnow or datetime.now(timezone.utc)
    markets={}
    for ticker,name in INDICES.items():
        frame=frames.get(ticker)
        fresh=equity_indicators(frame) if frame is not None else None
        if fresh:
            markets[ticker]={**fresh,'ticker':ticker,'name':name}
        elif ticker in (previous.get('indices') or {}):markets[ticker]=previous['indices'][ticker]
    spy=markets.get('SPY')
    marketdate=spy['date'] if spy else None
    if not spy:raise RuntimeError('SPY-päätöskurssi puuttuu eikä edellistä tallennetta löydy')

    sectorlist=[]
    for ticker,name in SECTORS.items():
        frame=frames.get(ticker);s=equity_indicators(frame) if frame is not None else None
        if not s: continue
        rel20=nfloat(s['pct20']-spy['pct20']) if s.get('pct20') is not None and spy.get('pct20') is not None and s['date']==spy['date'] else None
        rel60=nfloat(s['pct60']-spy['pct60']) if s.get('pct60') is not None and spy.get('pct60') is not None and s['date']==spy['date'] else None
        sectorlist.append({'ticker':ticker,'name':name,'close':s['close'],'date':s['date'],
             'pct20':s['pct20'],'pct60':s['pct60'],'rel20':rel20,'rel60':rel60,
             'rsi':s['rsi'],'sma50':s['sma50'],'above200':s['dist200'] is not None and s['dist200']>0})
    if not sectorlist:sectorlist=previous.get('sectors',[])

    theme_list=[]
    for ticker,name in THEMES.items():
        frame=frames.get(ticker);s=equity_indicators(frame) if frame is not None else None
        if not s:continue
        theme_list.append({'ticker':ticker,'name':name,'date':s['date'],'pct20':s['pct20'],
              'rel20':nfloat(s['pct20']-spy['pct20']) if s['date']==spy['date'] and s.get('pct20') is not None and spy.get('pct20') is not None else None,
              'rsi':s['rsi'],'above200':s['dist200'] is not None and s['dist200']>0})
    if not theme_list:theme_list=previous.get('themes',[])

    stocks=[]
    for ticker,details in STOCKS.items():
        frame=frames.get(ticker);s=stock_record(ticker,details,frame) if frame is not None else None
        if s:stocks.append(s)
    if not stocks:stocks=previous.get('stocks',[])

    breadth=None
    if sp500_tickers:
        series={t:frames[t]['Close'] for t in sp500_tickers if t in frames and 'Close' in frames[t]}
        breadth=breadth_from_closes(series,marketdate,len(sp500_tickers))
    if not breadth or breadth.get('p200') is None:
        prior=previous.get('breadth')
        if prior and not warn_if_stale(marketdate,prior.get('date'),5):
            breadth=prior
    if not breadth:breadth={'date':marketdate,'coverage':0,'included':0,'universe':len(sp500_tickers or []),'p20':None,'p50':None,'p200':None,'warning':'Kattavaa S&P 500 -laskentaa ei saatavilla'}

    vix=last_good(vix,previous,'vix')
    fear=last_good(fear,previous,'fear')
    # Don't use stale VIX/F&G to make new aggregate score.
    rvix=vix if vix and not warn_if_stale(marketdate,vix.get('date'),5) else None
    rfear=fear if fear and not warn_if_stale(marketdate,fear.get('date'),5) else None
    rbreadth=breadth if breadth and not warn_if_stale(marketdate,breadth.get('date'),0) else None
    risk=risk_score(spy,rbreadth,rvix,rfear)
    if risk['coverage']<75:
        risk['score']=None
        risk['label']='Ei riittävästi tietoa'
        risk['note']='Yhdistelmäarviota ei näytetä, kun kattavuus jää alle 75 %:n.'
    # A stale SPY series is still real data but not a valid current-market risk reading.
    risk['stale']=warn_if_stale(utcnow.date().isoformat(),marketdate,7)
    if risk['stale']:
        risk['score']=None
        risk['label']='Kurssidataa odotetaan'
        risk['note']='SPY-havainto on vanhentunut. Älä tulkitse vanhaa pistelukua nykytilaksi.'

    cmdties=[]
    for ticker in FUTURES:
        f=frames.get(ticker)
        if f is not None:
            item=as_futures(ticker,f)
            if item:cmdties.append(item)
    cmdties+=list((worldbank or {}).values())
    if uranium:cmdties.append(uranium)
    cmdties+=list(ise or [])
    cmdties+=list(daily_metals or [])
    cmdties+=list(special or [])
    prev_commodities=previous.get('commodities',[])
    # Keep older observations when an upstream source fails, without changing date or type.
    cmdties=newest_by_id(prev_commodities,cmdties)

    # Retain timeseries on a source update when current publisher only returns one data point.
    old_by_id={x['id']:x for x in prev_commodities if x.get('id')}
    for x in cmdties:
        oldx=old_by_id.get(x.get('id'))
        if oldx and x.get('source')==oldx.get('source') and x.get('unit')==oldx.get('unit') and x.get('date')!=oldx.get('date') and x.get('points') and oldx.get('points'):
            x['points']=sorted({str(d):v for d,v in (oldx['points']+x['points'])}.items())[-1300:]
            if x.get('frequency')=='päivä':
                changes=old.summarize_points(x['points'],'päivä')
                for key in ('chg1','chg3','chg12'):
                    x[key]=changes[key]

    asof=utcnow.isoformat(timespec='seconds').replace('+00:00','Z')
    # Store machine-readable source/age diagnostics for auditing the page.
    latest_status=[
        {'name':'S&P 500 / SPY','date':marketdate,'available':bool(spy),'source':'Yahoo Finance / yfinance'},
        {'name':'S&P 500 -markkinaleveys','date':(breadth or {}).get('date'),
         'available':(breadth or {}).get('p200') is not None,
         'source':'Indeksijäsenet + yfinance'},
        {'name':'VIX','date':(vix or {}).get('date'),'available':(vix or {}).get('value') is not None,
         'source':(vix or {}).get('source','ei saatavilla')},
        {'name':'Fear & Greed','date':(fear or {}).get('date'),
         'available':(fear or {}).get('value') is not None,
         'source':(fear or {}).get('source','ei saatavilla')},
        {'name':'LME:n päivämetallit','date':max((x.get('date') or '' for x in cmdties if x.get('source','').startswith('Westmetall')),default=None),
         'available':any(x.get('price') is not None and x.get('source','').startswith('Westmetall') for x in cmdties),
         'source':'Westmetall / LME cash'},
        {'name':'Uraani U₃O₈ kuukausi','date':next((x.get('date') for x in cmdties if x.get('id')=='uranium'),None),
         'available':any(x.get('id')=='uranium' and x.get('price') is not None for x in cmdties),
         'source':'IMF/FRED'},
        {'name':'Erikoismetallien julkiset viivehinnat','date':max((x.get('date') or '' for x in cmdties if x.get('source','').startswith('ISE')),default=None),
         'available':any(x.get('source','').startswith('ISE') and x.get('price') is not None for x in cmdties),
         'source':'ISE'},
    ]
    record={'meta':{'version':'LIVE 1.0','mode':'live','built_at_utc':asof,'market_date':marketdate,'errors':errors,
                    'price_disclaimer':'Pörssipäivän päätöskurssit ja viiveelliset / kuukausittaiset raaka-ainehinnat; ei reaaliaikainen streaming-palvelu'},
            'risk':risk,'indices':markets,'breadth':breadth,'vix':vix,'fear':fear,'sectors':sectorlist,
            'themes':theme_list,'stocks':stocks,'commodities':cmdties, 'sources_status':latest_status}
    if len(stocks)<10:record['meta']['errors'].append('Osakkeiden seurantalista vajaa; kurssihaku voi olla rajoitettu')
    return record


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default=str(OUT));p.add_argument('--no-breadth',action='store_true');args=p.parse_args()
    session=requests.Session();session.headers.update({'User-Agent':'Mozilla/5.0 (compatible; MarkkinavahtiPersonal/3.0)'})
    prev={};errors=[]
    try:
        prev=json.loads(Path(args.output).read_text(encoding='utf8'))
        if prev.get('meta',{}).get('mode')!='live':prev={}
    except (OSError,ValueError):pass
    tickers=list(dict.fromkeys([*INDICES,*SECTORS,*THEMES,*STOCKS,*FUTURES]))
    print('Haetaan markkinat:',len(tickers))
    frames=fetch_yfinance(tickers,period='2y',chunk=28,pause=1)
    membership=[]
    if not args.no_breadth:
        try:
            membership=fetch_sp500_constituents(session)
            extras=[t for t in membership if t not in frames]
            print('S&P500-jäsenet:',len(membership),'lisäkurssit:',len(extras))
            frames.update(fetch_yfinance(extras,period='15mo',chunk=45,pause=2.0))
        except Exception as e:errors.append(f'S&P 500 -jäsenlistaa tai markkinaleveyttä ei saatu: {str(e)[:140]}')
    vix=fear=None; worldbank={};uranium=None;ise=[];daily_metals=[]
    try:vix=get_vix(session)
    except Exception as e:
        errors.append('Cboe VIX päälähde: '+str(e)[:110])
        try:vix=get_vix_fred(session)
        except Exception as backup:errors.append('FRED VIXCLS varalähde: '+str(backup)[:110])
    try:fear=get_fear(session)
    except Exception as e:errors.append('Fear & Greed: '+str(e)[:140])
    try:worldbank=old.fetch_worldbank(session)
    except Exception as e:errors.append('Maailmanpankki: '+str(e)[:140])
    try:uranium=old.fetch_fred(session)
    except Exception as e:errors.append('Uraani / FRED: '+str(e)[:140])
    try:ise=get_ise(session)
    except Exception as e:errors.append('ISE-erikoismetallit: '+str(e)[:140])
    try:daily_metals+=fetch_westmetall(session)
    except Exception as e:errors.append('LME:n julkiset päiväarvot: '+str(e)[:130])
    try:daily_metals+=fetch_smm(session)
    except Exception as e:errors.append('SMM:n julkiset päiväarvot: '+str(e)[:130])
    special=old.parse_specialty(DATA/'specialty_prices.csv')
    doc=build_snapshot(frames=frames,sp500_tickers=membership,vix=vix,fear=fear,worldbank=worldbank,
              uranium=uranium,ise=ise,special=special,daily_metals=daily_metals,previous=prev,errors=errors)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(doc,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf8')
    print('Snapshot:',out,'markets:',len(doc['indices']),'breadth:',doc['breadth'].get('coverage'),
          'stocks:',len(doc['stocks']),'commodities:',len(doc['commodities']))
    for err in errors:print('HUOM:',err)

if __name__=='__main__':main()
