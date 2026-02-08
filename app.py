import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests

# --- 1. 基础配置 ---
st.set_page_config(page_title="流动性观测 Pro", layout="wide")
st.title("🔬 宏观流动性 vs 崩盘归因分析系统")

# --- 2. 侧边栏 ---
st.sidebar.header("回测参数")
years_back = st.sidebar.slider("回溯年份", 1, 5, 3)
start_date = datetime.now() - timedelta(days=years_back*365)
start_date_str = start_date.strftime('%Y-%m-%d')

# --- 3. 核心数据获取函数 ---
def fetch_fred_series(series_id, start_date_str):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date_str}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text), index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_macro_data(start_str):
    # A. 获取 Yahoo 市场数据
    tickers = {"Nasdaq": "^IXIC", "USD_JPY": "JPY=X", "BTC": "BTC-USD", "VIX": "^VIX"}
    try:
        m_data = yf.download(list(tickers.values()), start=start_str, progress=False)['Close']
        if isinstance(m_data.columns, pd.MultiIndex):
            m_data.columns = m_data.columns.get_level_values(0)
        if m_data.index.tz is not None:
            m_data.index = m_data.index.tz_localize(None)
        m_data = m_data.rename(columns={v: k for k, v in tickers.items()})
    except:
        return pd.DataFrame()

    # B. 获取 FRED 宏观数据并对齐
    fred_ids = {'WALCL': 'WALCL', 'WTREGEN': 'WTREGEN', 'RRPONTSYD': 'RRPONTSYD'}
    f_aligned = pd.DataFrame(index=m_data.index)
    for key, s_id in fred_ids.items():
        f_data = fetch_fred_series(s_id, start_str)
        if not f_data.empty:
            f_aligned[key] = f_data.iloc[:, 0].reindex(m_data.index, method='ffill')
    
    # C. 合并数据
    df = m_data.join(f_aligned).ffill().dropna()
    if 'WALCL' in df.columns:
        df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
    return df

# --- 4. 运行逻辑 ---
df = get_macro_data(start_date_str)

if df.empty:
    st.error("数据加载失败，请检查网络并刷新页面。")
    st.stop()

tab1, tab2, tab3 = st.tabs(["📊 分析图表", "⚠️ 信号回测", "📑 原始数据"])

with tab1:
    col_main, col_side = st.columns([3, 1])
    with col_main:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq Index", line=dict(color='cyan')))
        if 'Net_Liquidity' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['Net_Liquidity'], name="Net Liquidity (B$)", yaxis="y2", line=dict(dash='dot', color='orange')))
        fig.update_layout(title="流动性与纳斯达克走势对比", yaxis=dict(title="Nasdaq"), yaxis2=dict(title="Liquidity", overlaying="y", side="right"), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    
    with col_side:
        st.write("#### 资产相关性")
        # --- 核心修复：直接显示 DataFrame，禁止使用 .style ---
        corr = df.corr()['Nasdaq'].sort_values(ascending=False).to_frame(name="相关度")
        st.dataframe(corr)

with tab2:
    st.subheader("USD/JPY 冲击信号回测")
    df['JPY_Chg_10d'] = df['USD_JPY'].pct_change(10)
    signals = df[df['JPY_Chg_10d'] < -0.03].index
    
    results = []
    for d in signals:
        try:
            p_start = df.loc[d, 'Nasdaq']
            future_d = d + timedelta(days=20)
            if future_d > df.index[-1]: continue
            idx = df.index.get_indexer([future_d], method='nearest')[0]
            p_end = df.iloc[idx]['Nasdaq']
            results.append({"日期": d.strftime('%Y-%m-%d'), "JPY 变动": df.loc[d, 'JPY_Chg_10d'], "Nasdaq 20天后表现": (p_end/p_start)-1})
        except: pass
    
    if results:
        res_df = pd.DataFrame(results)
        c1, c2 = st.columns([2, 1])
        with c1:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq"))
            fig2.add_trace(go.Scatter(x=signals, y=df.loc[signals, 'Nasdaq'], mode='markers', name='信号点', marker=dict(color='red', size=8, symbol='triangle-down')))
            st.plotly_chart(fig2, use_container_width=True)
        with c2:
            # --- 核心修复：仅保留基础格式化，不使用渐变色 ---
            st.dataframe(res_df)
    else:
        st.info("未触发流动性冲击信号")

with tab3:
    st.dataframe(df.tail(100))