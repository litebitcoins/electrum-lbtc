from datetime import datetime
import inspect
import requests
import sys
from threading import Thread
import time
import traceback
import csv
from decimal import Decimal

from bitcoin import COIN
from i18n import _
from util import PrintError, ThreadJob
from util import format_satoshis


# See https://en.wikipedia.org/wiki/ISO_4217
CCY_PRECISIONS = {'BHD': 3, 'BIF': 0, 'BYR': 0, 'CLF': 4, 'CLP': 0,
                  'CVE': 0, 'DJF': 0, 'GNF': 0, 'IQD': 3, 'ISK': 0,
                  'JOD': 3, 'JPY': 0, 'KMF': 0, 'KRW': 0, 'KWD': 3,
                  'LYD': 3, 'MGA': 1, 'MRO': 1, 'OMR': 3, 'PYG': 0,
                  'RWF': 0, 'TND': 3, 'UGX': 0, 'UYI': 0, 'VND': 0,
                  'VUV': 0, 'XAF': 0, 'XAU': 4, 'XOF': 0, 'XPF': 0}

class ExchangeBase(PrintError):

    def __init__(self, on_quotes, on_history):
        self.history = {}
        self.quotes = {}
        self.on_quotes = on_quotes
        self.on_history = on_history

    def get_json(self, site, get_string):
        # APIs must have https
        url = ''.join(['https://', site, get_string])
        response = requests.request('GET', url, headers={'User-Agent' : 'Electrum'})
        return response.json()

    def get_csv(self, site, get_string):
        url = ''.join(['https://', site, get_string])
        response = requests.request('GET', url, headers={'User-Agent' : 'Electrum'})
        reader = csv.DictReader(response.content.split('\n'))
        return list(reader)

    def name(self):
        return self.__class__.__name__

    def update_safe(self, ccy):
        try:
            self.print_error("getting fx quotes for", ccy)
            self.quotes = self.get_rates(ccy)
            self.print_error("received fx quotes")
        except BaseException as e:
            self.print_error("failed fx quotes:", e)
        self.on_quotes()

    def update(self, ccy):
        t = Thread(target=self.update_safe, args=(ccy,))
        t.setDaemon(True)
        t.start()

    def get_historical_rates_safe(self, ccy):
        try:
            self.print_error("requesting fx history for", ccy)
            self.history[ccy] = self.historical_rates(ccy)
            self.print_error("received fx history for", ccy)
            self.on_history()
        except BaseException as e:
            self.print_error("failed fx history:", e)

    def get_historical_rates(self, ccy):
        result = self.history.get(ccy)
        if not result and ccy in self.history_ccys():
            t = Thread(target=self.get_historical_rates_safe, args=(ccy,))
            t.setDaemon(True)
            t.start()
        return result

    def history_ccys(self):
        return []

    def historical_rate(self, ccy, d_t):
        return self.history.get(ccy, {}).get(d_t.strftime('%Y-%m-%d'))

    def get_currencies(self):
        rates = self.get_rates('')
        return sorted([str(a) for (a, b) in rates.iteritems() if b is not None and len(a)==3])


class Bit2C(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('www.bit2c.co.il', '/Exchanges/LBTCNIS/Ticker.json')
        return {'NIS': Decimal(json['ll'])}


class BitcoinAverage(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('apiv2.bitcoinaverage.com', '/indices/global/ticker/short')
        return dict([(r.replace("LBTC", ""), Decimal(json[r]['last']))
                     for r in json if r != 'timestamp'])

    def history_ccys(self):
        return ['AUD', 'BRL', 'CAD', 'CHF', 'CNY', 'EUR', 'GBP', 'IDR', 'ILS',
                'MXN', 'NOK', 'NZD', 'PLN', 'RON', 'RUB', 'SEK', 'SGD', 'USD',
                'ZAR']

    def historical_rates(self, ccy):
        history = self.get_csv('apiv2.bitcoinaverage.com',
                               "/indices/global/history/LBTC%s?period=alltime&format=csv" % ccy)
        return dict([(h['DateTime'][:10], h['Average'])
                     for h in history])


class BitcoinVenezuela(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('api.bitcoinvenezuela.com', '/')
        rates = [(r, json['LBTC'][r]) for r in json['LBTC']
                 if json['LBTC'][r] is not None]  # Giving NULL sometimes
        return dict(rates)

    def history_ccys(self):
        return ['ARS', 'EUR', 'USD', 'VEF']

    def historical_rates(self, ccy):
        return self.get_json('api.bitcoinvenezuela.com',
                             "/historical/index.php?coin=LBTC")[ccy +'_LBTC']

class Bitfinex(ExchangeBase):
    def get_rates(self, ccy):
        json = self.get_json('api.bitfinex.com', '/v1/pubticker/lbtcusd')
        return {'USD': Decimal(json['last_price'])}


class BitStamp(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('www.bitstamp.net', '/api/v2/ticker/lbtcusd/')
        return {'USD': Decimal(json['last'])}


class BTCChina(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('data.btcchina.com', '/data/ticker?market=lbtccny')
        return {'CNY': Decimal(json['ticker']['last'])}


class BTCe(ExchangeBase):

    def get_rates(self, ccy):
        json_eur = self.get_json('btc-e.nz', '/api/3/ticker/lbtc_eur')
        json_rub = self.get_json('btc-e.nz', '/api/3/ticker/lbtc_rur')
        json_usd = self.get_json('btc-e.nz', '/api/3/ticker/lbtc_usd')
        return {'EUR': Decimal(json_eur['lbtc_eur']['last']),
                'RUB': Decimal(json_rub['lbtc_rur']['last']),
                'USD': Decimal(json_usd['lbtc_usd']['last'])}

class coinmarketcap(ExchangeBase):

    def get_rates(self, ccy):
        json_aud = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=AUD')
        json_aed = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=AED') 
        json_afn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=AFN') 
        json_all = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ALL') 
        json_amd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=AMD') 
        json_ang = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ANG') 
        json_aoa = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=AOA') 
        json_ars = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ARS') 
        json_awg = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=AWG') 
        json_azn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=AZN') 
        json_bam = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BAM') 
        json_bbd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BBD') 
        json_bdt = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BDT') 
        json_bgn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BGN') 
        json_bhd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BHD') 
        json_bif = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BIF') 
        json_bmd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BMD') 
        json_bnd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BND') 
        json_bob = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BOB') 
        json_brl = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BRL') 
        json_bsd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BSD') 
        json_btc = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BTC') 
        json_btn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BTN') 
        json_bwp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BWP') 
        json_byn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BYN') 
        json_bzd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=BZD') 
        json_cad = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CAD') 
        json_cdf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CDF') 
        json_chf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CHF') 
        json_clf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CLF') 
        json_cpl = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CLP') 
        json_cnh = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CNH') 
        json_cny = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CNY') 
        json_cop = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=COP') 
        json_crc = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CRC') 
        json_cuc = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CUC') 
        json_cup = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CUP') 
        json_cve = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CVE') 
        json_czk = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=CZK') 
        json_djf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=DJF') 
        json_dkk = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=DKK') 
        json_dop = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=DOP') 
        json_dzd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=DZD') 
        json_egp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=EGP') 
        json_ern = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ERN') 
        json_etb = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ETB') 
        json_eth = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ETH') 
        json_eur = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=EUR') 
        json_fjd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=FJD') 
        json_fkp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=FKP') 
        json_gbp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GBP') 
        json_gel = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GEL') 
        json_ggp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GGP') 
        json_ghs = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GHS') 
        json_gip = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GIP') 
        json_gmd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GMD') 
        json_gnf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GNF') 
        json_gtq = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GTQ') 
        json_gyd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=GYD') 
        json_hkd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=HKD') 
        json_hnl = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=HNL') 
        json_hrk = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=HRK') 
        json_htg = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=HTG') 
        json_huf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=HUF') 
        json_idr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=IDR') 
        json_ils = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ILS') 
        json_imp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=IMP') 
        json_inr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=INR') 
        json_iqd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=IQD') 
        json_irr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=IRR') 
        json_isk = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ISK') 
        json_jep = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=JEP') 
        json_jmd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=JMD') 
        json_jos = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=JOD') 
        json_jpy = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=JPY') 
        json_kes = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KES') 
        json_kgs = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KGS') 
        json_khr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KHR') 
        json_kmf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KMF') 
        json_kpw = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KPW') 
        json_krw = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KRW') 
        json_kwd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KWD') 
        json_kyd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KYD') 
        json_kzt = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=KZT') 
        json_lak = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=LAK') 
        json_lbp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=LBP') 
        json_lkr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=LKR') 
        json_lrd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=LRD') 
        json_lsl = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=LSL') 
        json_lyd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=LYD') 
        json_mad = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MAD') 
        json_mdl = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MDL') 
        json_mga = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MGA') 
        json_mkd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MKD') 
        json_mmk = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MMK') 
        json_mnt = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MNT') 
        json_mop = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MOP') 
        json_mro = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MRO') 
        json_mur = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MUR') 
        json_mvr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MVR') 
        json_mwk = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MWK') 
        json_mxn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MXN') 
        json_myr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MYR') 
        json_mzn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=MZN') 
        json_nad = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=NAD') 
        json_ngn = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=NGN') 
        json_nio = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=NIO') 
        json_nok = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=NOK') 
        json_npr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=NPR') 
        json_nzd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=NZD') 
        json_omr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=OMR') 
        json_pab = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=PAB') 
        json_pen = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=PEN') 
        json_pgk = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=PGK') 
        json_php = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=PHP') 
        json_pkr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=PKR') 
        json_pln = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=PLN') 
        json_pyg = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=PYG') 
        json_qar = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=QAR') 
        json_ron = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=RON') 
        json_rsd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=RSD') 
        json_rub = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=RUB') 
        json_rwf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=RWF') 
        json_sar = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SAR') 
        json_sbd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SBD') 
        json_scr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SCR') 
        json_sdg = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SDG') 
        json_sek = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SEK') 
        json_sgd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SGD') 
        json_shp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SHP') 
        json_sll = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SLL') 
        json_sos = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SOS') 
        json_srd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SRD') 
        json_ssp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SSP') 
        json_std = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=STD') 
        json_svc = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SVC') 
        json_syp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SYP') 
        json_szl = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=SZL') 
        json_thb = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=THB') 
        json_tjs = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TJS') 
        json_tmt = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TMT') 
        json_tnd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TND') 
        json_top = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TOP') 
        json_try = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TRY') 
        json_ttd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TTD') 
        json_twd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TWD') 
        json_tzs = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=TZS') 
        json_uah = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=UAH') 
        json_ugx = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=UGX') 
        json_usd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=USD') 
        json_uyu = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=UYU') 
        json_uzs = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=UZS') 
        json_vef = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=VEF') 
        json_vnd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=VND') 
        json_vuv = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=VUV') 
        json_wst = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=WST') 
        json_xaf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XAF') 
        json_xag = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XAG') 
        json_xau = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XAU') 
        json_xcd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XCD') 
        json_xdr = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XDR') 
        json_xof = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XOF') 
        json_xpd = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XPD') 
        json_xpf = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XPF') 
        json_xpt = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XPT') 
        json_xrp = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=XRP') 
        json_yer = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=YER') 
        json_zar = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ZAR') 
        json_zec = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ZEC') 
        json_zmw = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ZMW') 
        json_zwl = self.get_json('api.coinmarketcap.com', '/v1/ticker/litebitcoin/?convert=ZWL')
        return {'AUD': Decimal(json_aud['price_aud']),
                'AED': Decimal(json_aed['price_aed']),
                'AFN': Decimal(json_afn['price_afn']),
                'ALL': Decimal(json_all['price_all']),
                'AMD': Decimal(json_amd['price_amd']),
                'ANG': Decimal(json_ang['price_ang']),
                'AOA': Decimal(json_aoa['price_aoa']),
                'ARS': Decimal(json_ars['price_ars']),
                'AWG': Decimal(json_awg['price_awg']),
                'AZN': Decimal(json_azn['price_azn']),
                'BAM': Decimal(json_bam['price_bam']),
                'BBD': Decimal(json_bbd['price_bbd']),
                'BDT': Decimal(json_bdt['price_bdt']),
                'BGN': Decimal(json_bgn['price_bgn']),
                'BHD': Decimal(json_bhd['price_bhd']),
                'BIF': Decimal(json_bif['price_bif']),
                'BMD': Decimal(json_bmd['price_bmd']),
                'BND': Decimal(json_bnd['price_bnd']),
                'BOB': Decimal(json_bob['price_bob']),
                'BRL': Decimal(json_brl['price_brl']),
                'BSD': Decimal(json_bsd['price_bsd']),
                'BTC': Decimal(json_btc['price_btc']),
                'BTN': Decimal(json_btn['price_btn']),
                'BWP': Decimal(json_bwp['price_bwp']),
                'BYN': Decimal(json_byn['price_byn']),
                'BZD': Decimal(json_bzd['price_bzd']),
                'CAD': Decimal(json_cad['price_cad']),
                'CDF': Decimal(json_cdf['price_cdf']),
                'CHF': Decimal(json_chf['price_chf']),
                'CLF': Decimal(json_clf['price_clf']),
                'CLP': Decimal(json_cpl['price_cpl']),
                'CNH': Decimal(json_cnh['price_cnh']),
                'CNY': Decimal(json_cny['price_cny']),
                'COP': Decimal(json_cop['price_cop']),
                'CRC': Decimal(json_crc['price_crc']),
                'CUC': Decimal(json_cuc['price_cuc']),
                'CUP': Decimal(json_cup['price_cup']),
                'CVE': Decimal(json_cve['price_cve']),
                'CZK': Decimal(json_czk['price_czk']),
                'DJF': Decimal(json_djf['price_djf']),
                'DKK': Decimal(json_dkk['price_dkk']),
                'DOP': Decimal(json_dop['price_dop']),
                'DZD': Decimal(json_dzd['price_dzd']),
                'EGP': Decimal(json_egp['price_egp']),
                'ERN': Decimal(json_ern['price_ern']),
                'ETB': Decimal(json_etb['price_etb']),
                'ETH': Decimal(json_eth['price_eth']),
                'EUR': Decimal(json_eur['price_eur']),
                'FJD': Decimal(json_fjd['price_fjd']),
                'FKP': Decimal(json_fkp['price_fkp']),
                'GBP': Decimal(json_gbp['price_gbp']),
                'GEL': Decimal(json_gel['price_gel']),
                'GGP': Decimal(json_ggp['price_ggp']),
                'GHS': Decimal(json_ghs['price_ghs']),
                'GIP': Decimal(json_gip['price_gip']),
                'GMD': Decimal(json_gmd['price_gmd']),
                'GNF': Decimal(json_gnf['price_gnf']),
                'GTQ': Decimal(json_gtq['price_gtq']),
                'GYD': Decimal(json_gyd['price_gyd']),
                'HKD': Decimal(json_hkd['price_hkd']),
                'HNL': Decimal(json_hnl['price_hnl']),
                'HRK': Decimal(json_hrk['price_hrk']),
                'HTG': Decimal(json_htg['price_htg']),
                'HUF': Decimal(json_huf['price_huf']),
                'IDR': Decimal(json_idr['price_idr']),
                'ILS': Decimal(json_ils['price_ils']),
                'IMP': Decimal(json_imp['price_imp']),
                'INR': Decimal(json_inr['price_inr']),
                'IQD': Decimal(json_iqd['price_iqd']),
                'IRR': Decimal(json_irr['price_irr']),
                'ISK': Decimal(json_isk['price_isk']),
                'JEP': Decimal(json_jep['price_jep']),
                'JMD': Decimal(json_jmd['price_jmd']),
                'JOD': Decimal(json_jos['price_jos']),
                'JPY': Decimal(json_jpy['price_jpy']),
                'KES': Decimal(json_kes['price_kes']),
                'KGS': Decimal(json_kgs['price_kgs']),
                'KHR': Decimal(json_khr['price_khr']),
                'KMF': Decimal(json_kmf['price_kmf']),
                'KPW': Decimal(json_kpw['price_kpw']),
                'KRW': Decimal(json_krw['price_krw']),
                'KWD': Decimal(json_kwd['price_kwd']),
                'KYD': Decimal(json_kyd['price_kyd']),
                'KZT': Decimal(json_kzt['price_kzt']),
                'LAK': Decimal(json_lak['price_lak']),
                'LBP': Decimal(json_lbp['price_lbp']),
                'LKR': Decimal(json_lkr['price_lkr']),
                'LRD': Decimal(json_lrd['price_lrd']),
                'LSL': Decimal(json_lsl['price_lsl']),
                'LYD': Decimal(json_lyd['price_lyd']),
                'MAD': Decimal(json_mad['price_mad']),
                'MDL': Decimal(json_mdl['price_mdl']),
                'MGA': Decimal(json_mga['price_mga']),
                'MKD': Decimal(json_mkd['price_mkd']),
                'MMK': Decimal(json_mmk['price_mmk']),
                'MNT': Decimal(json_mnt['price_mnt']),
                'MOP': Decimal(json_mop['price_mop']),
                'MRO': Decimal(json_mro['price_mro']),
                'MUR': Decimal(json_mur['price_mur']),
                'MVR': Decimal(json_mvr['price_mvr']),
                'MWK': Decimal(json_mwk['price_mwk']),
                'MXN': Decimal(json_mxn['price_mxn']),
                'MYR': Decimal(json_myr['price_myr']),
                'MZN': Decimal(json_mzn['price_mzn']),
                'NAD': Decimal(json_nad['price_nad']),
                'NGN': Decimal(json_ngn['price_ngn']),
                'NIO': Decimal(json_nio['price_nio']),
                'NOK': Decimal(json_nok['price_nok']),
                'NPR': Decimal(json_npr['price_npr']),
                'NZD': Decimal(json_nzd['price_nzd']),
                'OMR': Decimal(json_omr['price_omr']),
                'PAB': Decimal(json_pab['price_pab']),
                'PEN': Decimal(json_pen['price_pen']),
                'PGK': Decimal(json_pgk['price_pgk']),
                'PHP': Decimal(json_php['price_php']),
                'PKR': Decimal(json_pkr['price_pkr']),
                'PLN': Decimal(json_pln['price_pln']),
                'PYG': Decimal(json_pyg['price_pyg']),
                'QAR': Decimal(json_qar['price_qar']),
                'RON': Decimal(json_ron['price_ron']),
                'RSD': Decimal(json_rsd['price_rsd']),
                'RUB': Decimal(json_rub['price_rub']),
                'RWF': Decimal(json_rwf['price_rwf']),
                'SAR': Decimal(json_sar['price_sar']),
                'SBD': Decimal(json_sbd['price_sbd']),
                'SCR': Decimal(json_scr['price_scr']),
                'SDG': Decimal(json_sdg['price_sdg']),
                'SEK': Decimal(json_sek['price_sek']),
                'SGD': Decimal(json_sgd['price_sgd']),
                'SHP': Decimal(json_shp['price_shp']),
                'SLL': Decimal(json_sll['price_sll']),
                'SOS': Decimal(json_sos['price_sos']),
                'SRD': Decimal(json_srd['price_srd']),
                'SSP': Decimal(json_ssp['price_ssp']),
                'STD': Decimal(json_std['price_std']),
                'SVC': Decimal(json_svc['price_svc']),
                'SYP': Decimal(json_syp['price_syp']),
                'SZL': Decimal(json_szl['price_szl']),
                'THB': Decimal(json_thb['price_thb']),
                'TJS': Decimal(json_tjs['price_tjs']),
                'TMT': Decimal(json_tmt['price_tmt']),
                'TND': Decimal(json_tnd['price_tnd']),
                'TOP': Decimal(json_top['price_top']),
                'TRY': Decimal(json_try['price_try']),
                'TTD': Decimal(json_ttd['price_ttd']),
                'TWD': Decimal(json_twd['price_twd']),
                'TZS': Decimal(json_tzs['price_tzs']),
                'UAH': Decimal(json_uah['price_uah']),
                'UGX': Decimal(json_ugx['price_ugx']),
                'USD': Decimal(json_usd['price_usd']),
                'UYU': Decimal(json_uyu['price_uyu']),
                'UZS': Decimal(json_uzs['price_uzs']),
                'VEF': Decimal(json_vef['price_vef']),
                'VND': Decimal(json_vnd['price_vnd']),
                'VUV': Decimal(json_vuv['price_vuv']),
                'WST': Decimal(json_wst['price_wst']),
                'XAF': Decimal(json_xaf['price_xaf']),
                'XAG': Decimal(json_xag['price_xag']),
                'XAU': Decimal(json_xau['price_xau']),
                'XCD': Decimal(json_xcd['price_xcd']),
                'XDR': Decimal(json_xdr['price_xdr']),
                'XOF': Decimal(json_xof['price_xof']),
                'XPD': Decimal(json_xpd['price_xpd']),
                'XPF': Decimal(json_xpf['price_xpf']),
                'XPT': Decimal(json_xpt['price_xpt']),
                'XRP': Decimal(json_xrp['price_xrp']),
                'YER': Decimal(json_yer['price_yer']),
                'ZAR': Decimal(json_zar['price_zar']),
                'ZEC': Decimal(json_zec['price_zec']),
                'ZMW': Decimal(json_zmw['price_zmw']),
                'ZWL': Decimal(json_zwl['price_zwl'])}				

class CaVirtEx(ExchangeBase):
    def get_rates(self, ccy):
        json = self.get_json('www.cavirtex.com', '/api2/ticker.json?currencypair=LBTCCAD')
        return {'CAD': Decimal(json['ticker']['LBTCCAD']['last'])}


class CoinSpot(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('www.coinspot.com.au', '/pubapi/latest')
        return {'AUD': Decimal(json['prices']['lbtc']['last'])}


class GoCoin(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('x.g0cn.com', '/prices')
        lbtc_prices = json['prices']['LBTC']
        return dict([(r, Decimal(lbtc_prices[r])) for r in lbtc_prices])


class HitBTC(ExchangeBase):

    def get_rates(self, ccy):
        ccys = ['EUR', 'USD']
        json = self.get_json('api.hitbtc.com', '/api/1/public/LBTC%s/ticker' % ccy)
        result = dict.fromkeys(ccys)
        if ccy in ccys:
            result[ccy] = Decimal(json['last'])
        return result


class Kraken(ExchangeBase):

    def get_rates(self, ccy):
        dicts = self.get_json('api.kraken.com', '/0/public/AssetPairs')
        pairs = [k for k in dicts['result'] if k.startswith('XLBTCZ')]
        json = self.get_json('api.kraken.com',
                             '/0/public/Ticker?pair=%s' % ','.join(pairs))
        ccys = [p[5:] for p in pairs]
        result = dict.fromkeys(ccys)
        result[ccy] = Decimal(json['result']['XLBTCZ'+ccy]['c'][0])
        return result

    def history_ccys(self):
        return ['EUR', 'USD']

    def historical_rates(self, ccy):
        query = '/0/public/OHLC?pair=LBTC%s&interval=1440' % ccy
        json = self.get_json('api.kraken.com', query)
        history = json['result']['XLBTCZ'+ccy]
        return dict([(time.strftime('%Y-%m-%d', time.localtime(t[0])), t[4])
                                    for t in history])


class OKCoin(ExchangeBase):

    def get_rates(self, ccy):
        json = self.get_json('www.okcoin.cn', '/api/ticker.do?symbol=lbtc_cny')
        return {'CNY': Decimal(json['ticker']['last'])}


class MercadoBitcoin(ExchangeBase):

    def get_rates(self,ccy):
        json = self.get_json('mercadobitcoin.net',
                                "/api/v2/ticker_litebitcoin")
        return {'BRL': Decimal(json['ticker']['last'])}


class Bitcointoyou(ExchangeBase):

    def get_rates(self,ccy):
        json = self.get_json('bitcointoyou.com',
                                "/API/ticker_litebitcoin.aspx")
        return {'BRL': Decimal(json['ticker']['last'])}


def dictinvert(d):
    inv = {}
    for k, vlist in d.iteritems():
        for v in vlist:
            keys = inv.setdefault(v, [])
            keys.append(k)
    return inv

def get_exchanges_and_currencies():
    import os, json
    path = os.path.join(os.path.dirname(__file__), 'currencies.json')
    try:
        return json.loads(open(path, 'r').read())
    except:
        pass
    d = {}
    is_exchange = lambda obj: (inspect.isclass(obj)
                               and issubclass(obj, ExchangeBase)
                               and obj != ExchangeBase)
    exchanges = dict(inspect.getmembers(sys.modules[__name__], is_exchange))
    for name, klass in exchanges.items():
        exchange = klass(None, None)
        try:
            d[name] = exchange.get_currencies()
        except:
            continue
    with open(path, 'w') as f:
        f.write(json.dumps(d, indent=4, sort_keys=True))
    return d


CURRENCIES = get_exchanges_and_currencies()


def get_exchanges_by_ccy(history=True):
    if not history:
        return dictinvert(CURRENCIES)
    d = {}
    exchanges = CURRENCIES.keys()
    for name in exchanges:
        klass = globals()[name]
        exchange = klass(None, None)
        d[name] = exchange.history_ccys()
    return dictinvert(d)


class FxThread(ThreadJob):

    def __init__(self, config, network):
        self.config = config
        self.network = network
        self.ccy = self.get_currency()
        self.history_used_spot = False
        self.ccy_combo = None
        self.hist_checkbox = None
        self.set_exchange(self.config_exchange())

    def get_currencies(self, h):
        d = get_exchanges_by_ccy(h)
        return sorted(d.keys())

    def get_exchanges_by_ccy(self, ccy, h):
        d = get_exchanges_by_ccy(h)
        return d.get(ccy, [])

    def ccy_amount_str(self, amount, commas):
        prec = CCY_PRECISIONS.get(self.ccy, 2)
        fmt_str = "{:%s.%df}" % ("," if commas else "", max(0, prec))
        return fmt_str.format(round(amount, prec))

    def run(self):
        # This runs from the plugins thread which catches exceptions
        if self.is_enabled():
            if self.timeout ==0 and self.show_history():
                self.exchange.get_historical_rates(self.ccy)
            if self.timeout <= time.time():
                self.timeout = time.time() + 150
                self.exchange.update(self.ccy)

    def is_enabled(self):
        return bool(self.config.get('use_exchange_rate'))

    def set_enabled(self, b):
        return self.config.set_key('use_exchange_rate', bool(b))

    def get_history_config(self):
        return bool(self.config.get('history_rates'))

    def set_history_config(self, b):
        self.config.set_key('history_rates', bool(b))

    def get_currency(self):
        '''Use when dynamic fetching is needed'''
        return self.config.get("currency", "EUR")

    def config_exchange(self):
        return self.config.get('use_exchange', 'BitcoinAverage')

    def show_history(self):
        return self.is_enabled() and self.get_history_config() and self.ccy in self.exchange.history_ccys()

    def set_currency(self, ccy):
        self.ccy = ccy
        self.config.set_key('currency', ccy, True)
        self.timeout = 0 # Because self.ccy changes
        self.on_quotes()

    def set_exchange(self, name):
        class_ = globals().get(name, BitcoinAverage)
        self.print_error("using exchange", name)
        if self.config_exchange() != name:
            self.config.set_key('use_exchange', name, True)
        self.exchange = class_(self.on_quotes, self.on_history)
        # A new exchange means new fx quotes, initially empty.  Force
        # a quote refresh
        self.timeout = 0

    def on_quotes(self):
        self.network.trigger_callback('on_quotes')

    def on_history(self):
        self.network.trigger_callback('on_history')

    def exchange_rate(self):
        '''Returns None, or the exchange rate as a Decimal'''
        rate = self.exchange.quotes.get(self.ccy)
        if rate:
            return Decimal(rate)

    def format_amount_and_units(self, btc_balance):
        rate = self.exchange_rate()
        return '' if rate is None else "%s %s" % (self.value_str(btc_balance, rate), self.ccy)

    def get_fiat_status_text(self, btc_balance, base_unit, decimal_point):
        rate = self.exchange_rate()
        return _("  (No FX rate available)") if rate is None else " 1 %s~%s %s" % (base_unit,
            self.value_str(COIN / (10**(8 - decimal_point)), rate), self.ccy)

    def value_str(self, satoshis, rate):
        if satoshis is None:  # Can happen with incomplete history
            return _("Unknown")
        if rate:
            value = Decimal(satoshis) / COIN * Decimal(rate)
            return "%s" % (self.ccy_amount_str(value, True))
        return _("No data")

    def history_rate(self, d_t):
        rate = self.exchange.historical_rate(self.ccy, d_t)
        # Frequently there is no rate for today, until tomorrow :)
        # Use spot quotes in that case
        if rate is None and (datetime.today().date() - d_t.date()).days <= 2:
            rate = self.exchange.quotes.get(self.ccy)
            self.history_used_spot = True
        return rate

    def historical_value_str(self, satoshis, d_t):
        rate = self.history_rate(d_t)
        return self.value_str(satoshis, rate)
