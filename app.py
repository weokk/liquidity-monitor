import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests

# --- 配置 ---
st.set_page_config(page_title="宏观流动性回测系统 Pro", layout="wide")
st.title("🔬 宏观流动性 vs 崩盘归因分析系统 (Pro Ver.)")

# --- 侧边栏 ---
st.sidebar.header("回测参数")
years_back = st.sidebar.slider("回溯年份", 1, 5, 3)
start_date = datetime.now() - timedelta(days=years_back*365)
start_date_str = start_date.strftime('%Y-%m-%d')

st.sidebar.markdown("---")
st.sidebar.info("数据源: Yahoo Finance + FRED (修复版)")

# --- 核心辅助函数：稳健获取 FRED 数据 ---
def fetch_fred_series(series_id, start_date_str):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date_str}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text), index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index)
            # 强制去除时区信息
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

# --- 核心数据逻辑 ---
@st.cache_data(ttl=3600)
def get_macro_data(start_str):
    # 1. 获取市场数据
    market_tickers = {
        "Nasdaq": "^IXIC",          
        "USD_JPY": "JPY=X",         
        "BTC": "BTC-USD",           
        "VIX": "^VIX"               
    }
    
    market_data = yf.download(list(market_tickers.values()), start=start_str, progress=False)['Close']
    
    # 清洗 Yahoo 数据
    if isinstance(market_data.columns, pd.MultiIndex):
        market_data.columns = market_data.columns.get_level_values(0)
    
    # 强制去除 Yahoo 时区
    if market_data.index.tz is not None:
        market_data.index = market_data.index.tz_localize(None)
    
    inv_map = {v: k for k, v in market_tickers.items()}
    market_data = market_data.rename(columns=inv_map)
    
    # 2. 获取美联储数据
    fred_ids = {'WALCL': 'WALCL', 'WTREGEN': 'WTREGEN', 'RRPONTSYD': 'RRPONTSYD'}
    fred_frames = {}
    
    for key, series_id in fred_ids.items():
        data = fetch_fred_series(series_id, start_str)
        if not data.empty:
            fred_frames[key] = data.iloc[:, 0]
        else:
            fred_frames[key] = pd.Series(index=market_data.index, dtype=float)

    # 3. 对齐与合并
    fred_aligned = pd.DataFrame(index=market_data.index)
    for key, series in fred_frames.items():
        fred_aligned[key] = series.reindex(market_data.index, method='ffill')
    
    df = market_data.join(fred_aligned).ffill().dropna()
    
    # 4. 计算净流动性
    if 'WALCL' in df.columns and 'WTREGEN' in df.columns:
        # 单位统一为 Billions
        df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
    else:
        df['Net_Liquidity'] = 0
    
    return df

# 执行获取
try:
    df = get_macro_data(start_date_str)
except Exception as e:
    st.error(f"数据处理发生严重错误: {e}")
    st.stop()

if df.empty:
    st.error("未获取到有效数据，请稍后重试。")
    st.stop()

# --- 逻辑分析层 ---
corr_matrix = df.corr()

# --- 界面展示 ---
tab1, tab2, tab3 = st.tabs(["📈 深度趋势对比", "⚠️ 预警信号回测", "🧮 原始数据"])

with tab1:
    st.subheader("流动性 vs 资产价格历史走势")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq Index", line=dict(color='cyan', width=2)))
        
        if df['Net_Liquidity'].sum() != 0:
            fig.add_trace(go.Scatter(x=df.index, y=df['Net_Liquidity'], name="Fed Net Liquidity (B$)", 
                                     line=dict(color='orange', dash='dot'), yaxis='y2'))
        
        fig.add_trace(go.Scatter(x=df.index, y=df['USD_JPY'], name="USD/JPY (汇率)", 
                                 line=dict(color='red', width=1), yaxis='y2', visible='legendonly'))

        fig.update_layout(
            title="美联储净流动性 vs 纳斯达克",
            yaxis=dict(title="Nasdaq Index"),
            yaxis2=dict(title="Liquidity / JPY", overlaying='y', side='right'),
            hovermode="x unified",
            height=500,
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.write("#### 核心相关性矩阵")
        if 'Nasdaq' in corr_matrix.columns:
            target_corr = corr_matrix['Nasdaq'].sort_values(ascending=False)
            # --- 修复点：将 Series 转为 DataFrame 再应用样式 ---
            target_corr_df = target_corr.to_frame(name="Correlation")
            st.dataframe(target_corr_df.style.background_gradient(cmap='RdYlGn'))

with tab2:
    st.subheader("🕵️‍♀️ 危机预警回测 (Backtesting Signals)")
    st.markdown("定义: 当 **USD/JPY** 10天内快速升值(数值跌)超 3%，视为流动性抽离。")

    if 'USD_JPY' in df.columns:
        df['JPY_Chg_10d'] = df['USD_JPY'].pct_change(10)
        signals = df[df['JPY_Chg_10d'] < -0.03].index
        
        results = []
        for date in signals:
            try:
                price_at_signal = df.loc[date]['Nasdaq']
                target_date = date + timedelta(days=20)
                if target_date > df.index[-1]: continue
                
                idx_loc = df.index.get_indexer([target_date], method='nearest')[0]
                price_after_20d = df.iloc[idx_loc]['Nasdaq']
                
                drawdown = (price_after_20d - price_at_signal) / price_at_signal
                results.append({
                    "信号日期": date.strftime('%Y-%m-%d'),
                    "USD/JPY 10天跌幅": df.loc[date]['JPY_Chg_10d'],
                    "Nasdaq 20天后表现": drawdown
                })
            except: pass
        
        res_df = pd.DataFrame(results)
        
        col_a, col_b = st.columns([2, 1])
        with col_a:
            fig_sig = go.Figure()
            fig_sig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq"))
            y_vals = df.loc[signals]['Nasdaq']
            fig_sig.add_trace(go.Scatter(
                x=signals, y=y_vals, mode='markers', name='流动性警报',
                marker=dict(color='red', size=10, symbol='triangle-down')
            ))
            st.plotly_chart(fig_sig, use_container_width=True)
        with col_b:
            if not res_df.empty:
                # 同样的修复：应用样式前确保它是 DataFrame（虽然 res_df 本身就是 DataFrame，这里安全起见）
                st.dataframe(res_df.style.format({'USD/JPY 10天跌幅': '{:.2%}', 'Nasdaq 20天后表现': '{:.2%}'})
                             .applymap(lambda x: 'color: red' if x < 0 else 'color: green', subset=['Nasdaq 20天后表现']))
            else:
                st.write("未触发警报。")

with tab3:
    st.dataframe(df.tail(50))