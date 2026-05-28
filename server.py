from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import yfinance as yf
import requests
from datetime import datetime
import pandas as pd

app = Flask(__name__)
CORS(app)

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
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        if hist.empty:
            return jsonify({'error': f'無法取得 {symbol} 的資料'}), 404
        candles = []
        for idx, row in hist.iterrows():
            candles.append({
                'time': idx.strftime('%Y-%m-%d'),
                'open': round(row['Open'], 2),
                'high': round(row['High'], 2),
                'low': round(row['Low'], 2),
                'close': round(row['Close'], 2),
                'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0
            })
        info = ticker.info
        info_data = {
            'name': info.get('longName', symbol),
            'exchange': info.get('exchange', '—'),
            'currency': info.get('currency', 'TWD'),
            'sector': info.get('sector', '—')
        }
        return jsonify({'success': True, 'symbol': symbol, 'count': len(candles), 'candles': candles, 'info': info_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/yahoo/quote')
def yahoo_quote():
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': '請提供股票代號'}), 400
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        prev_close = info.get('regularMarketPreviousClose', info.get('previousClose', price))
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        return jsonify({'symbol': symbol, 'price': round(price, 2), 'change': round(change, 2), 'changePct': round(change_pct, 2)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/okx/kline')
def okx_kline():
    symbol = request.args.get('symbol', '').upper()
    bar = request.args.get('bar', '1D')
    limit = int(request.args.get('limit', 300))
    if not symbol:
        return jsonify({'error': '請提供交易對代號'}), 400
    if '-USDT' in symbol and '-SWAP' not in symbol:
        symbol = symbol.replace('-USDT', '-USDT-SWAP')
    try:
        url = 'https://www.okx.com/api/v5/market/history-candles'
        params = {'instId': symbol, 'bar': bar, 'limit': limit}
        response = requests.get(url, params=params, timeout=10)
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
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': '請提供交易對代號'}), 400
    if '-USDT' in symbol and '-SWAP' not in symbol:
        symbol = symbol.replace('-USDT', '-USDT-SWAP')
    try:
        url = 'https://www.okx.com/api/v5/market/ticker'
        response = requests.get(url, params={'instId': symbol}, timeout=10)
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

if __name__ == '__main__':
    print("\n✅ 網格交易系統後端已啟動")
    print("🌐 請打開瀏覽器訪問: http://localhost:5000\n")
    app.run(debug=True, host='0.0.0.0', port=5000)