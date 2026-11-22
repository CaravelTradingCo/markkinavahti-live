import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'scripts'))
from engine import equity_indicators,breadth_from_closes,risk_score,rsi_wilder,setup
from build_live import parse_ise_html,parse_locale_number,parse_westmetall_html,parse_smm_html,build_snapshot,STOCKS


def frame(start='2025-01-01',n=350,price=100,slope=0.05):
    dates=pd.bdate_range(start,periods=n)
    prices=np.array([price+slope*i for i in range(n)])
    return pd.DataFrame({'Close':prices,'Open':prices,'High':prices,'Low':prices,'Volume':[1000]*n},index=dates)

class EngineTest(unittest.TestCase):
    def test_rsi_monotonic_up(self):
        s=pd.Series(np.arange(100,dtype=float))
        self.assertEqual(rsi_wilder(s).iloc[-1],100)
    def test_rsi_flat(self):
        self.assertEqual(rsi_wilder(pd.Series([3.0]*100)).iloc[-1],50)
    def test_sma_non_lookahead(self):
        f=frame()
        a=equity_indicators(f.iloc[:-1]);b=equity_indicators(f.iloc[:-1].copy())
        f.iloc[-1,f.columns.get_loc('Close')]=99999
        self.assertEqual(a['sma200'],b['sma200'])
    def test_sma_200(self):
        f=frame(n=300,price=100,slope=1)
        s=equity_indicators(f)
        self.assertAlmostEqual(s['sma200'],(200+399)/2,places=4)
    def test_rsi_oversold_not_buy(self):
        x={'close':40,'sma50':100,'sma200':120,'ema20':60,'rsi':18,'rsi_5d_ago':15,'volume_ratio':1.4,'positive_day':True,'dist50':-60,'sma200_slope20':-3}
        self.assertEqual(setup(x)[0],'Ylimyyty – odota vahvistusta')
    def test_confirmed_uptrend(self):
        x={'close':103,'sma50':102,'sma200':85,'ema20':101,'rsi':52,'rsi_5d_ago':45,'volume_ratio':1.4,'positive_day':True,'dist50':.98,'sma200_slope20':2}
        self.assertEqual(setup(x)[0],'Nousutrendin ostopaikka')
    def test_reversal_not_confirmed_uptrend(self):
        x={'close':90,'sma50':100,'sma200':110,'ema20':88,'rsi':46,'rsi_5d_ago':38,'volume_ratio':1.4,'positive_day':True,'dist50':-10,'sma200_slope20':-2}
        self.assertEqual(setup(x)[0],'Käänne tarkkailuun')
    def test_breadth_coverage_guard(self):
        f=frame(n=300)
        series={str(i):f.Close for i in range(400)}
        s=breadth_from_closes(series,str(f.index[-1].date()),500)
        self.assertIsNone(s['p50'])
    def test_breadth_percentage_correct(self):
        f=frame(n=300)
        series={str(i):(f.Close if i<250 else f.Close.iloc[::-1].set_axis(f.Close.index)) for i in range(500)}
        s=breadth_from_closes(series,str(f.index[-1].date()),500)
        self.assertEqual(s['p50'],50.0)
        self.assertEqual(s['n200'],250)
    def test_breadth_point_in_time(self):
        f=frame(n=300)
        series={str(i):f.Close for i in range(500)}
        a=breadth_from_closes(series,str(f.index[-2].date()),500)
        f.iloc[-1,f.columns.get_loc('Close')]=1
        b=breadth_from_closes({str(i):f.Close for i in range(500)},str(f.index[-2].date()),500)
        self.assertEqual(a['p50'],b['p50'])
    def test_risk_full_coverage_and_partial(self):
        spy={'close':105,'sma50':100,'sma200':90,'sma200_slope20':1}
        breadth={'p50':70,'p200':80}
        full=risk_score(spy,breadth,{'value':12},{'value':60})
        self.assertEqual(full['coverage'],100);self.assertTrue(full['complete'])
        partial=risk_score(spy,None,None,None)
        self.assertEqual(partial['coverage'],30);self.assertFalse(partial['complete'])
    def test_ise_parsing_has_correct_product_qualifier(self):
        html='<table><tr><th>Metal</th><th>Reference specification</th><th>Monthly average</th><th>MoM</th><th>Period</th><th>Date</th></tr><tr><td>Wolfram</td><td>88.5%min EXW China</td><td>69,66 EUR/kg</td><td>-15,9 %</td><td>+47,8 %</td><td>23.10.2026</td></tr><tr><td>Gallium</td><td>99.99%min EXW China</td><td>258,46 EUR/kg</td><td>+3,1 %</td><td>+29,5 %</td><td>23.10.2026</td></tr></table>'
        results=parse_ise_html(html)
        self.assertEqual(len(results),2)
        self.assertEqual(results[0]['id'],'tungsten_ise')
        self.assertEqual(results[0]['price'],69.66)
        self.assertNotEqual(results[0]['id'],'tungsten')
        self.assertEqual(results[1]['id'],'gallium_ise')
    def test_locale_numbers(self):
        self.assertEqual(parse_locale_number('12,230.50'),12230.5)
        self.assertEqual(parse_locale_number('14.110,50'),14110.50)
        self.assertEqual(parse_locale_number('-15,9 %'),-15.9)
    def test_westmetall_html(self):
        html='<table><tr><td>20. November 2026</td><td>12,230.50</td><td>12,237.00</td></tr><tr><td>19. November 2026</td><td>12,570.00</td><td>12,555.00</td></tr></table>'
        result=parse_westmetall_html(html,'lme_copper_cash','https://www.westmetall.com/')
        self.assertEqual(result['price'],12230.5)
        self.assertEqual(result['date'],'2026-11-20')
        self.assertEqual(result['type'],'fyysinen päivähinta')
    def test_smm_html(self):
        html='<table><tr><td>Battery-Grade Lithium Carbonate SMM-Li-LC-001</td><td>13,690.53 USD/tonne</td><td>-26.21</td><td>2026-11-20</td></tr></table>'
        x=parse_smm_html(html)
        self.assertEqual(x[0]['id'],'lithium_smm')
        self.assertEqual(x[0]['price'],13690.53)
    def test_partial_live_requires_spy(self):
        with self.assertRaises(RuntimeError):build_snapshot(frames={},worldbank={},errors=[])
    def test_live_meta_and_risk(self):
        f=frame(n=320)
        b=build_snapshot(frames={'SPY':f,'QQQ':f,'XLK':f},sp500_tickers=[],vix=None,fear=None,worldbank={},previous={},errors=[],utcnow=datetime(2026,11,22,tzinfo=timezone.utc))
        self.assertEqual(b['meta']['mode'],'live')
        self.assertEqual(b['risk']['coverage'],30)

if __name__=='__main__':unittest.main()
