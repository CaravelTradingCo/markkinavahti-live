# Markkinavahti LIVE — oikeat päätöskurssit ja lähteistetyt raaka-ainehinnat

Tämä versio **ei sisällä demo- tai keksittyjä hintoja**. Sovellus on staattinen verkkosivu, jonka GitHub Actions täyttää julkisista datalähteistä haettavalla `data/latest.json`-tiedostolla. Ensimmäisen onnistuneen pilviajon jälkeen sama verkko-osoite päivittyy **tiistaista lauantaihin klo 03.40 UTC**. Lauantain ajo käsittelee perjantain USA-pörssipäivää. Päivitykset eivät ole pörssin sisäisiä reaaliaikaisia kursseja.

**Oleellinen käyttörajoitus:** pakettia ei ole julkaistu valmiiksi verkkoon. Ennen GitHub-julkaisua `index.html` näyttää rehellisesti ”Ei live-dataa”. Pelkkä tiedoston avaaminen Windowsin Edgellä ei käynnistä ulkoisia hintahakuja. Tämä estää aiemmissa demoissa koetun sekaannuksen kuvitteellisten lukujen kanssa.

## Julkaisu ilman Python-asennusta Windowsiin

1. Pura ZIP-paketti Windowsissa. Luo GitHubiin tyhjä julkinen repository nimellä `markkinavahti-live`.
2. Lataa **koko puretun paketin sisältö** GitHubiin. GitHub Desktopilla tämä onnistuu: `Clone repository` → kopioi puretut tiedostot kloonattuun kansioon → `Commit` → `Push`. **Varmista, että piilotettu `.github/workflows/paivita-ja-julkaise.yml` on mukana.** Jos käytät GitHubin verkkokäyttöliittymää, kansiorakenne pitää säilyttää.
3. Avaa GitHubissa repositoryn `Settings → Pages → Build and deployment → Source: GitHub Actions`.
4. Avaa `Actions → Markkinavahti LIVE – päivitä ja julkaise → Run workflow`. Ensimmäinen onnistunut ajo luo lähteistä haetun `data/latest.json`-tiedoston ja julkaisee sivuston. Verkko-osoite näkyy `Settings → Pages` -kohdassa.

**Mikäli Pagesin työhön tulee virhe:** avaa Actions → epäonnistunut työnkulku → `Fetch last completed market session and commodity benchmarks`. Virhe näkyy lokissa. Pörssi-, raaka-aine- ja S&P 500 -lähteet voivat rajoittaa automaattista hakua. Koodi ei esitä demoarvoja varatietona.

## Mistä oikea data tulee?

| Mittari | Lähde | Päivitys | Käytännön rajaus |
| --- | --- | --- | --- |
| SPY, QQQ, sektorit, valitut osakkeet, ETF:t, futuurit | Yahoo Finance -päivähistoria `yfinance`-kirjastolla | Viimeisen päätöspäivän jälkeen | Epävirallinen rajapinta, rajoitukset mahdollisia |
| S&P 500:n osakkeet SMA20/50/200:n yläpuolella | Ajantasainen S&P-yhtiöluettelo + noin 500 osakesarjan päätöshinnat | Päivittäin onnistuneen haun jälkeen | Vähintään 85 % sarjoista ja 400 validia sarjaa vaaditaan; muuten `—` |
| VIX | Cboe VIX History; varalähde FRED VIXCLS | Päivittäinen päätösluku | Ei intraday-volatiliteetti |
| Fear & Greed | CNN:n julkisesti saatava kuvaajadatarajapinta; varalähteenä FearGreedFlow, merkitty | Päivittäin jos palvelu vastaa | Epävirallisten rajapintojen saatavuus vaihtelee |
| Kupari, alumiini, nikkeli, sinkki, tina, lyijy | Westmetallin julkaisemat LME Cash Settlement -arvot | Päivittäin, jos lähde vastaa | USD/tonni, ei COMEX eikä yksilöllinen toimitustarjous |
| Kulta, kupari ja energia (futuurit) | Yahoo Finance | Päivittäin | Futuurit eivät ole fyysisiä spot-noteerauksia; sopimusvaihto näkyy sarjassa |
| Uraani U₃O₈ | IMF:n sarja FREDissä (`PURANUSDM`) | Kuukausittain | Ei reaaliaikainen spot-hinta |
| Kulta, kupari, alumiini, muut perusmetallit | World Bank Pink Sheet | Kuukausittain | Maailmanpankin vertailusarjat |
| Litiumkarbonaatti, litiumhydroksidi, Kiina-kupari/-alumiini | SMM/Metal.com julkiset rivit (best effort) | Vain, jos julkinen taulukko sisältää päiväarvon | HTML-rakenteen muutos voi katkaista haun; maksullista dataa ei ohiteta |
| Gallium, germanium, antimoni, wolframi, neodyymi, dysprosium, terbium | ISE Critical Raw Materials Monitor | Julkinen data vähintään ~30 päivää jäljessä | Tuote ja puhtausaste eri kuin APT / NdPr-oksidi |
| APT, V₂O₅, NdPr-oksidi, magnesium, bauksiitti | Oma lähteistetty `data/specialty_prices.csv` | Vain, jos päivitetty | Ei automaattisesti avointa ja varmennettua hintalähdettä; näyttää `—` |

**Hintalähde, mittayksikkö ja havaintopäivä näkyvät aina käyttöliittymässä.** Saman metallin eri tuotemuotoja ja markkinoita ei yhdistetä samaan aikasarjaan.

## Seurantalista ja ostopaikkojen ehdot

Mukana on Nvidia, SK hynix (Korean ensisijainen listaus), IREN, FCX, MP, UUUU, EQR, VR8, VBX, METLEN, 5N Plus, ALB ja muita. Näytetään RSI(14), 20/50/200 päivän liukuvat, 20 päivän keskiarvovolyymiin suhteutettu vaihto ja seulontaluokka. RSI alle 30 **ei** yksin tuota ostosignaalia. Seulontapisteet eivät ole tuottoennusteita.

Markkinan riskimittari painottaa SPY-trendiä 30 %, S&P-osakeleveydestä 30 %, VIX:ää 25 % ja Fear & Greediä 15 %. Jos kattavuus on alle 75 % tai SPY-data on vanhentunut, yhdistettyä lukua ei näytetä. Osittainen lähdekattavuus ja pörssipäivämäärä ilmoitetaan.

## Oma lähdekohtainen erikoismetallihinta

Lisää täsmällisen vertailutuotteen havainto tiedostoon `data/specialty_prices.csv`:

```csv
id,date,price,unit,market,source_url
```

Sallitut tunnisteet on määritelty tiedostossa `scripts/sources_v2.py`. Ole erityisen tarkka tuotemuodosta: wolframi 88,5 % ei ole APT ja neodyymimetalli ei ole NdPr-oksidi.

## Päivittäinen päivitys, testaus ja lisenssit

Työ käynnistyy ajastetusti GitHub Actionsissa. Jos dataa ei pystytä hakemaan, lähdevirheet merkitään lokiin; edellisen havainnon päivämäärä ei muutu. GitHubin ajoajat voivat viivästyä ja vuoden mittaisissa historiatiedoissa voi olla lähdekorjauksia.

Kehittäjälle (valinnainen, **ei** tarvita GitHub-julkaisussa):

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/build_live.py
python -m http.server 8000
```

Sivu: `http://localhost:8000/`. Ensimmäisessä päivityksessä tarvitaan ulkoinen verkkoyhteys ja onnistunut hintahaku.

Tämä on henkilökohtaisen sijoitustutkimuksen prototyyppi, ei varmennettu kaupallinen markkinadatalisenssi. Yahoo, Cboe, CNN, LME, SMM, ISE ja IMF voivat edellyttää lisenssejä datan kaupalliseen jakeluun. Kaikki lähderajapinnat eivät ole virallisesti tuettuja. Historiallisessa S&P 500 -markkinaleveydessä käytetään **nykyistä** jäsenistöä, joten sen käyttäminen vanhojen vuosien backtestissä tuottaisi selviytymisharhan.
