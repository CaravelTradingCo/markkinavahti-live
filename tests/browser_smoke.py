"""Smoke test of real-data frontend with a temporary structurally valid fixture.
Fixture is not part of release; no simulated observations are shipped to users.
"""
from pathlib import Path
import sys
import json
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'scripts'))
from build_live import build_snapshot

def make_fixture():
    ix=pd.bdate_range(end='2026-11-20',periods=320)
    values=np.linspace(100,122,len(ix))
    f=pd.DataFrame({'Open':values,'High':values,'Low':values,'Close':values,'Volume':np.repeat(10000,len(ix))},index=ix)
    frames={key:f for key in ('SPY','QQQ','XLK','NVDA','FCX','MP','UUUU')}
    members=[f'S{i:03}' for i in range(500)]
    frames.update({t:f for t in members})
    s=build_snapshot(frames=frames,sp500_tickers=members,vix={'date':'2026-11-20','value':20,'source':'Test source','history':[]},fear={'date':'2026-11-20','value':40,'source':'Test source','history':[]},worldbank={},daily_metals=[{'id':'lme_copper_cash','name':'Kupari – LME cash settlement','group':'Perusmetallit','price':12345.0,'unit':'USD/tonni','date':'2026-11-20','type':'fyysinen päivähinta','frequency':'päivä','source':'Test fixture','source_url':'https://www.westmetall.com/','points':[['2026-11-19',12400],['2026-11-20',12345]],'chg1':None}],utcnow=datetime(2026,11,22,tzinfo=timezone.utc))
    assert s['meta']['mode']=='live' and s['risk']['score'] is not None
    return s

# Inject a structurally valid mock snapshot only into the test HTML in memory.
# The published HTML and ZIP do not contain this data.
html=(root/'index.html').read_text(encoding='utf8')
fixture=json.dumps(make_fixture(),ensure_ascii=False)
html=html.replace('async function load(){',f'async function load(){{DB={fixture};MODE="live";render();return;')
with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1280,'height':850})
        errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
        page.set_content(html,wait_until='load');page.wait_for_function("document.querySelector('#mode').textContent.includes('Lähteistä haettu data')",timeout=10000)
        assert 'Missä markkina menee?' in page.locator('#app').inner_text()
        assert 'Fear & Greed' in page.locator('#app').inner_text()
        assert 'S&P 500' in page.locator('#app').inner_text()
        page.locator('[data-page="raaka"]').click()
        assert 'Kupari' in page.locator('#app').inner_text()
        page.locator('[data-page="ostot"]').click()
        assert 'Nvidia' in page.locator('#app').inner_text()
        page.locator('[data-page="ohje"]').click()
        assert 'Datayhteyksien tilanne' in page.locator('#app').inner_text()
        assert 'VIX' in page.locator('#app').inner_text()
        # No false LIVE badge when the data file is unavailable.
        # The production missing-data path is also executed with no external request.
        missing=(root/'index.html').read_text(encoding='utf8').replace('async function load(){','async function load(){DB=emptyData();MODE="missing";render();return;')
        page2=browser.new_page(viewport={'width':1280,'height':850})
        page2.on('pageerror',lambda err:errors.append(str(err)))
        page2.set_content(missing,wait_until='load')
        page2.wait_for_function("document.querySelector('#mode').textContent.includes('Ei live-dataa')",timeout=10000)
        assert 'Tietoja ei korvata keksityillä luvuilla' in page2.locator('#feedback').inner_text()
        assert errors==[],errors
        browser.close()
print('BROWSER_SMOKE_OK: sources, commodities, stocks, missing-data state, no JS errors')
