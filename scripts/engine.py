"""Markkinavahti 3.0 - deterministic, point-in-time technical indicator engine.

All SMAs, RSI (Wilder/RMA), volume ratios, ranks and risk scores use historical
prices through the observation date. They are NOT a validated prediction model.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
import math
import numpy as np
import pandas as pd


def nfloat(x, digits=2):
    try:
        v = float(x)
        return round(v, digits) if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def rsi_wilder(closes: pd.Series, window: int = 14) -> pd.Series:
    changes=closes.diff()
    ups=changes.clip(lower=0)
    dns=(-changes.clip(upper=0))
    # Wilder's RMA: start with SMA of first 14 price changes, then RMA.
    values=np.full(len(closes),np.nan,dtype=float)
    if len(closes)<window+1:
        return pd.Series(values,index=closes.index)
    up=float(ups.iloc[1:window+1].mean()); down=float(dns.iloc[1:window+1].mean())
    for i in range(window,len(closes)):
        if i>window:
            up=(up*(window-1)+float(ups.iloc[i]))/window
            down=(down*(window-1)+float(dns.iloc[i]))/window
        values[i] = 50.0 if up==0 and down==0 else (100.0 if down==0 else 100.0-(100.0/(1.0+up/down)))
    return pd.Series(values,index=closes.index)


def equity_indicators(frame: pd.DataFrame, currency='USD') -> dict|None:
    """frame: date index, unadjusted volume, split-adjusted OHLC; >= 20 days."""
    if frame is None or frame.empty or 'Close' not in frame:
        return None
    df=frame.copy();df=df.sort_index()
    for col in ('Open','High','Low','Close','Volume'):
        if col in df:df[col]=pd.to_numeric(df[col],errors='coerce')
    df=df.dropna(subset=['Close'])
    df=df[df.Close>0]
    if len(df)<20:return None
    close=df.Close.astype(float)
    volume=df.Volume if 'Volume' in df else pd.Series(np.nan,index=df.index)
    sma20=close.rolling(20,min_periods=20).mean()
    sma50=close.rolling(50,min_periods=50).mean()
    sma200=close.rolling(200,min_periods=200).mean()
    ema20=close.ewm(span=20,adjust=False).mean()
    ema50=close.ewm(span=50,adjust=False).mean()
    rsis=rsi_wilder(close)
    cur=float(close.iloc[-1])
    def pct_at(back):
        return nfloat(100*(cur/float(close.iloc[-back-1])-1)) if len(close)>back and close.iloc[-back-1]>0 else None
    vol20=volume.iloc[-21:-1].mean() if len(volume)>=21 else np.nan
    volratio=(float(volume.iloc[-1])/vol20 if pd.notna(vol20) and vol20>0 and pd.notna(volume.iloc[-1]) and volume.iloc[-1]>0 else None)
    prior_rsi=nfloat(rsis.iloc[-6]) if len(rsis)>=6 else None
    last_rsi=nfloat(rsis.iloc[-1]); prev=float(close.iloc[-2]);
    trend={
        'close':nfloat(cur,4), 'date':str(df.index[-1].date()) if hasattr(df.index[-1],'date') else str(df.index[-1])[:10],
        'currency':currency, 'sma20':nfloat(sma20.iloc[-1],4),'sma50':nfloat(sma50.iloc[-1],4),'sma200':nfloat(sma200.iloc[-1],4),
        'ema20':nfloat(ema20.iloc[-1],4),'ema50':nfloat(ema50.iloc[-1],4),
        'sma200_slope20':nfloat(100*(sma200.iloc[-1]/sma200.iloc[-21]-1)) if len(df)>=220 and pd.notna(sma200.iloc[-21]) else None,
        'rsi':last_rsi,'rsi_5d_ago':prior_rsi,'volume_ratio':nfloat(volratio),'volume':nfloat(volume.iloc[-1],0),
        'pct5':pct_at(5),'pct20':pct_at(20),'pct60':pct_at(60),'pct252':pct_at(252),
        'dist50':nfloat(100*(cur/sma50.iloc[-1]-1)) if pd.notna(sma50.iloc[-1]) else None,
        'dist200':nfloat(100*(cur/sma200.iloc[-1]-1)) if pd.notna(sma200.iloc[-1]) else None,
        'drawdown_1y':nfloat(100*(cur/close.tail(252).max()-1)),
        'higher_low':bool(cur>float(close.iloc[-6:-1].min())) if len(df)>7 else None,
        'positive_day':bool(cur>prev),
        'chart': [[str(d.date()) if hasattr(d,'date') else str(d)[:10],nfloat(v,4)] for d,v in close.iloc[-260:].items()],
    }
    signal,score,reasons=setup(trend)
    trend.update({'setup':signal,'setup_score':score,'reasons':reasons})
    return trend


def setup(t:dict):
    """All signals are screening hypotheses, NOT individualized buy orders."""
    c=t.get('close'); m50=t.get('sma50');m200=t.get('sma200'); ema=t.get('ema20'); r=t.get('rsi'); old=t.get('rsi_5d_ago')
    v=t.get('volume_ratio');
    if any(x is None for x in (c,r,ema,m50,m200)):
        return 'Ei riittävästi historiaa',0,['200 päivän keskiarvon laskentaan tarvitaan riittävästi hintahistoriaa']
    above200=c>m200; above50=c>m50; above20=c>ema
    rising=old is not None and r-old>=3
    vol_confirm=t.get('positive_day') and v is not None and v>=1.15
    pullback=above200 and t.get('dist50') is not None and -3<=t['dist50']<=6
    score=0
    if above200:score+=22
    if m50>m200:score+=13
    if above50:score+=12
    if above20:score+=12
    if 40<=r<=65:score+=17
    elif 33<=r<40 or 65<r<=70:score+=8
    if rising:score+=10
    if vol_confirm:score+=8
    if pullback:score+=6
    if t.get('sma200_slope20') is not None and t['sma200_slope20']>0:score+=4
    score=min(score,100)
    reasons=[]
    reasons.append('Kurssi 200 pv keskiarvon yläpuolella' if above200 else 'Kurssi 200 pv keskiarvon alapuolella')
    reasons.append(f'RSI(14) {r:.1f}' + (' – ylimyyty' if r<=30 else (' – ylikuumentunut' if r>=70 else '')))
    if vol_confirm: reasons.append('Nousupäivän volyymi yli 1,15 × 20 pv keskiarvo')
    elif v is not None: reasons.append(f'Volyymi {v:.2f} × 20 pv keskiarvoa (ei vahvistusta)')
    if pullback:reasons.append('Kurssi lähellä 50 päivän keskiarvoa')
    if rising: reasons.append('RSI on vahvistunut viimeisten viiden pörssipäivän aikana')
    if r>=72:return 'Ylikuumentunut',score,reasons
    if r<=30:return 'Ylimyyty – odota vahvistusta',score,reasons
    if above200 and m50>m200 and above20 and 40<=r<=65 and pullback and score>=65:
        return 'Nousutrendin ostopaikka',score,reasons
    if not above200 and above20 and rising and vol_confirm and 35<=r<=58:
        return 'Käänne tarkkailuun',score,reasons
    return 'Seuraa – ei vahvistettua ostopaikkaa',score,reasons


def breadth_from_closes(closes: dict[str,pd.Series], asof: str, universe_size:int):
    """Use exactly matching calendar date and 200 prior observed sessions; fail closed.

    The universe is today's constituents; not valid for historical backtests.
    """
    asof=pd.Timestamp(asof)
    available=[]; valid={}
    for ticker,s in closes.items():
        if s is None or s.empty:continue
        s=s.sort_index();s.index=pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        s=s[~s.index.duplicated(keep='last')]
        if asof not in s.index:continue
        idx=s.index.get_loc(asof)
        if idx<199:continue
        cur=float(s.iloc[idx]);before=s.iloc[:idx+1].tail(200)
        if not math.isfinite(cur) or cur<=0 or before.isna().any():continue
        valid[ticker]=(cur, [float(before.tail(n).mean()) for n in (20,50,200)])
    n=len(valid); ratio=n/universe_size if universe_size else 0
    result={'date':str(asof.date()),'coverage':round(ratio*100,1),'included':n,'universe':universe_size,
            'p20':None,'p50':None,'p200':None,'n20':None,'n50':None,'n200':None,
            'method':'S&P 500 nykyiset osakesarjat; sama päätöspäivä, SMA 20/50/200; yhtä suuri paino, osakesarjat eivät yhtiöt'}
    if ratio<0.85 or n<400:
        result['warning']='Alle 85 % osakesarjoista mukana tai havaintoja alle 400; prosentteja ei näytetä'
        return result
    for period,i in ((20,0),(50,1),(200,2)):
        above=sum(c>avgs[i] for c,avgs in valid.values())
        result['p'+str(period)]=round(100*above/n,1)
        result['n'+str(period)]=int(above)
    return result


def risk_score(spy:dict|None,breadth:dict|None,vix:dict|None,fear:dict|None):
    groups=[]
    if spy and spy.get('sma50') and spy.get('sma200') and spy.get('close'):
        c=spy['close']; points=(15 if c>spy['sma200'] else 0)+(10 if c>spy['sma50'] else 0)+(5 if (spy.get('sma200_slope20') or 0)>0 else 0)
        groups.append(('Trendi',points,30))
    if breadth and breadth.get('p50') is not None and breadth.get('p200') is not None:
        p50,p200=breadth['p50'],breadth['p200']
        q=lambda v,levels:15 if v>=levels[0] else (8 if v>=levels[1] else (3 if v>=levels[2] else 0))
        groups.append(('Markkinaleveys',q(p50,(60,45,30))+q(p200,(65,50,35)),30))
    if vix and vix.get('value') is not None:
        x=vix['value']; groups.append(('VIX',25 if x<15 else 20 if x<20 else 13 if x<25 else 6 if x<30 else 0,25))
    if fear and fear.get('value') is not None:
        x=fear['value']; groups.append(('Fear & Greed',15 if x>=65 else 10 if x>=45 else 5 if x>=25 else 0,15))
    denom=sum(max_ for _,_,max_ in groups)
    if not denom:return {'score':None,'label':'Ei riittävää dataa','complete':False,'components':[],'coverage':0}
    score=int(round(sum(x for _,x,_ in groups)/denom*100))
    label='Puolusta' if score<35 else ('Varovaisuus' if score<55 else ('Neutraali' if score<75 else 'Myötäinen trendi'))
    return {'score':score,'label':label,'complete':denom==100,'coverage':denom,
            'components':[{'name':k,'points':v,'max':mx} for k,v,mx in groups],
            'note':'Heuristinen riskimittari, ei testattu ennuste. Puuttuvat osat normalisoidaan; tarkista kattavuus.'}
