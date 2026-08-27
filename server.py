# 记得在终端执行：pip install yfinance --upgrade
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import yfinance as yf
import requests
from datetime import datetime
import pandas as pd

app = Flask(__name__)
CORS(app)

# 新增一个清洗函数，处理前端可能带来的错误后缀（如 :1）
def clean_symbol(symbol):
    if not symbol:
        return ''
    # 去掉可能存在的 :1, :2 等后缀
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
    symbol = clean_symbol(request.args.get('symbol', ''))
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
        # 获取 info 可能会失败，所以加了 try-except 或者直接给默认值
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
    symbol = clean_symbol(request.args.get('symbol', ''))
    if not symbol:
        return jsonify({'error': '請提供股票代號'}), 400
    try:
        # 规避 Yahoo 的 info 接口限制：使用 history 计算最新价格
        # 也可以先尝试获取 history 
        ticker = yf.Ticker(symbol)
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
        
    # 建议根据你的需求决定是否自动转合约，如果需要查现货，可注释掉下面两行
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
    symbol = clean_symbol(request.args.get('symbol', ''))
    if not symbol:
        return jsonify({'error': '請提供交易對代號'}), 400
        
    # 同 kline 注释
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

import os
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # Render 会自动分配端口
    app.run(host='0.0.0.0', port=port)