from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import yfinance as yf
import requests
from curl_cffi import requests as curl_requests
from datetime import datetime
import pandas as pd
import os
import math
import feedparser

app = Flask(__name__)
CORS(app)

yf_session = curl_requests.Session(impersonate="chrome")

def twse_clean_symbol(symbol):
    symbol = symbol.split(':')[0].upper()
    if symbol.endswith('.TW'):
        symbol = symbol[:-3]
    return symbol

def get_twse_history(symbol, period='6mo'):
    """從台灣證券交易所取得日 K 線，並移除不完整或非法資料。"""
    stock_no = twse_clean_symbol(symbol)
    all_candles = []

    # 依照前端傳入的 period 決定抓幾個月
    period_months = {
        '1mo': 1,
        '3mo': 3,
        '6mo': 6,
        '1y': 12,
        '2y': 24,
    }
    months_back = period_months.get(period, 6)

    current = datetime.now()

    for i in range(months_back):
        year = current.year
        month = current.month - i

        while month <= 0:
            month += 12
            year -= 1

        date_str = f"{year}{month:02d}01"
        url = (
            "https://www.twse.com.tw/exchangeReport/"
            f"STOCK_DAY?response=json&date={date_str}&stockNo={stock_no}"
         )

        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get('stat') != 'OK' or not data.get('data'):
                continue

            for row in data['data']:
                try:
                    # TWSE 回傳的數字有時會包含逗號，例如 24,040,916
                    def to_float(value):
                        if value is None:
                            return float('nan')
                        val = str(value).replace(',', '').strip()
                        return float(val) if val else float('nan')

                    o = to_float(row[3])
                    h = to_float(row[4])
                    l = to_float(row[5])
                    c = to_float(row[6])
                    v = to_float(row[1]) if len(row) > 1 else 0

                    # 任何 OHLC 是 NaN 或無限大，都不要送到前端，避免 JSON 解析失敗
                    if not all(math.isfinite(x) for x in [o, h, l, c]):
                        continue

                    # 成交量若不是有效數字，就以 0 處理
                    volume = int(v) if math.isfinite(v) and v >= 0 else 0

                    all_candles.append({
                        'time': row[0],
                        'open': round(o, 2),
                        'high': round(h, 2),
                        'low': round(l, 2),
                        'close': round(c, 2),
                        'volume': volume,
                    })

                except (ValueError, TypeError, IndexError):
                    continue

        except Exception as e:
            print(f"TWSE Fetch Error: {e}")

    # 同一天可能因不同月份查詢而重複，依日期去重
    unique_candles = {}
    for candle in all_candles:
        unique_candles[candle['time']] = candle

    # 由舊到新排列
    return sorted(unique_candles.values(), key=lambda x: x['time'])

def get_twse_quote(symbol):
    stock_no = twse_clean_symbol(symbol)
    url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=tse_{stock_no}.tw'
    try:
        resp = requests.get(url, timeout=5 )
        data = resp.json()
        if data and data.get('msgArray'):
            d = data['msgArray'][0]
            price = float(d.get('z', d.get('t', 0)))
            prev = float(d.get('y', 0))
            chg = price - prev
            chg_pct = (chg / prev * 100) if prev else 0
            return {
                'symbol': symbol, 
                'price': round(price, 2), 
                'change': round(chg, 2), 
                'changePct': round(chg_pct, 2)
            }
    except Exception as e:
        print(f"TWSE Quote Error: {e}")
    return None

def clean_symbol(symbol):
    if not symbol:
        return ''
    symbol = symbol.split(':')[0].upper()
    return symbol

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/ping')
def ping():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/yahoo/kline')
def yahoo_kline():
    symbol = request.args.get('symbol', '').upper()
    period = request.args.get('period', '6mo')
    interval = request.args.get('interval', '1d')
    
    if not symbol:
        return jsonify({'error': '請提供股票代號'}), 400

    # 優先嘗試從台灣證券交易所抓取 (台股代號通常是純數字或包含 .TW)
    if '.TW' in symbol or symbol.isdigit():
        candles = get_twse_history(symbol, period)
        if candles:
            return jsonify({
                'success': True, 
                'symbol': symbol, 
                'count': len(candles), 
                'candles': candles, 
                'info': {'name': symbol, 'exchange': 'TWSE', 'currency': 'TWD', 'sector': '—'}
            })

    # 備援或美股則使用 yfinance
    try:
        ticker = yf.Ticker(symbol, session=yf_session)
        hist = ticker.history(period=period, interval=interval)
        
        if hist.empty:
            return jsonify({'error': f'無法取得 {symbol} 的資料'}), 404
            
        candles = []
        for idx, row in hist.iterrows():
            try:
                o, h, l, c = float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])
                # 過濾 NaN，避免 JSON 損壞
                if not all(math.isfinite(x) for x in [o, h, l, c]):
                    continue
                
                v = row['Volume']
                volume = int(v) if pd.notna(v) and math.isfinite(float(v)) else 0
                
                candles.append({
                    'time': idx.strftime('%Y-%m-%d'),
                    'open': round(o, 2),
                    'high': round(h, 2),
                    'low': round(l, 2),
                    'close': round(c, 2),
                    'volume': volume
                })
            except:
                continue
                
        try:
            info = ticker.info
            info_data = {
                'name': info.get('longName', symbol),
                'exchange': info.get('exchange', '—'),
                'currency': info.get('currency', 'USD'),
                'sector': info.get('sector', '—')
            }
        except:
            info_data = {'name': symbol, 'exchange': '—', 'currency': 'USD', 'sector': '—'}
            
        return jsonify({'success': True, 'symbol': symbol, 'count': len(candles), 'candles': candles, 'info': info_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/yahoo/quote')
def yahoo_quote():
    symbol = request.args.get('symbol', '').upper()
    
    if not symbol:
        return jsonify({'error': '請提供股票代號'}), 400

    if '.TW' in symbol or symbol.isdigit():
        stock_no = twse_clean_symbol(symbol)
        url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=tse_{stock_no}.tw'
        try:
            resp = requests.get(url, timeout=5 )
            data = resp.json()
            if data and data.get('msgArray'):
                d = data['msgArray'][0]
                price = float(d.get('z', d.get('t', 0)))
                prev = float(d.get('y', 0))
                chg = price - prev
                chg_pct = (chg / prev * 100) if prev else 0
                return jsonify({'symbol': symbol, 'price': round(price, 2), 'change': round(chg, 2), 'changePct': round(chg_pct, 2)})
        except Exception as e:
            print(f"TWSE Quote Error: {e}")
    
    try:
        ticker = yf.Ticker(symbol, session=yf_session)
        hist = ticker.history(period="2d")
        if hist.empty:
            return jsonify({'error': f'無法取得 {symbol} 的資料'}), 404
            
        close_price = float(hist['Close'].iloc[-1])
        prev_close = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else close_price
        change = close_price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        
        return jsonify({
            'symbol': symbol, 
            'price': round(close_price, 2), 
            'change': round(change, 2), 
            'changePct': round(change_pct, 2)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/okx/kline')
def okx_kline():
    symbol = clean_symbol(request.args.get('symbol', ''))
    bar = request.args.get('bar', '1D')
    limit = int(request.args.get('limit', 300))
    if not symbol:
        return jsonify({'error': '請提供交易對代號'}), 400
        
    if '-USDT' in symbol and '-SWAP' not in symbol:
        symbol = symbol.replace('-USDT', '-USDT-SWAP')
        
    try:
        url = 'https://www.okx.com/api/v5/market/history-candles'
        params = {'instId': symbol, 'bar': bar, 'limit': limit}
        response = requests.get(url, params=params, timeout=10 )
        data = response.json()
        if data.get('code') != '0':
            return jsonify({'error': f'OKX API 錯誤: {data.get("msg")}'}), 400
        candles = []
        for item in data.get('data', []):
            ts = int(item[0])
            dt = datetime.fromtimestamp(ts / 1000)
            candles.append({
                'time': dt.strftime('%Y-%m-%d %H:%M'),
                'open': round(float(item[1]), 2),
                'high': round(float(item[2]), 2),
                'low': round(float(item[3]), 2),
                'close': round(float(item[4]), 2),
                'volume': int(float(item[5])) if item[5] else 0
            })
        return jsonify({'success': True, 'symbol': symbol, 'count': len(candles), 'candles': candles, 'info': {'name': symbol, 'exchange': 'OKX', 'currency': 'USDT', 'sector': '加密貨幣'}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/okx/ticker')
def okx_ticker():
    symbol = clean_symbol(request.args.get('symbol', ''))
    if not symbol:
        return jsonify({'error': '請提供交易對代號'}), 400
        
    if '-USDT' in symbol and '-SWAP' not in symbol:
        symbol = symbol.replace('-USDT', '-USDT-SWAP')
        
    try:
        url = 'https://www.okx.com/api/v5/market/ticker'
        response = requests.get(url, params={'instId': symbol}, timeout=10 )
        data = response.json()
        if data.get('code') != '0':
            return jsonify({'error': data.get('msg')}), 400
        ticker_data = data.get('data', [{}])[0]
        price = float(ticker_data.get('last', 0))
        open_24h = float(ticker_data.get('open24h', price))
        change = price - open_24h
        change_pct = (change / open_24h * 100) if open_24h else 0
        return jsonify({'symbol': symbol, 'price': round(price, 2), 'change': round(change, 2), 'changePct': round(change_pct, 2)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/news')
def news():
    q = request.args.get('q', '台積電')
    url = f'https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant'
    try:
        feed = feedparser.parse(url )
        items = []
        for entry in feed.entries[:10]:
            time_str = '最新'
            try:
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt = datetime(*entry.published_parsed[:6])
                    time_str = dt.strftime('%m-%d %H:%M')
            except:
                time_str = '最新'
                
            items.append({
                'title': entry.title,
                'url': entry.link,
                'time': time_str,
                'src': entry.source.title if hasattr(entry, 'source') else 'Google News',
                'sent': 'neu' 
            })
        return jsonify({'items': items})
    except Exception as e:
        return jsonify({'error': str(e), 'items': []}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
