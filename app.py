import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests

# --- 1. 页面配置 ---
st.set_page_config(page_title="宏观流动性观测模型", layout="wide")
st.title("🔬 宏观流动性 vs 崩盘归因分析系统")

# --- 2. 侧边栏 ---
st.sidebar.header("回测参数")
years_back = st.sidebar.slider("回溯年份", 1, 5, 3)
start_date = datetime.now() - timedelta(days=years_back*365)
start_date_str = start_date.strftime('%Y-%m-%d')

st.sidebar.markdown("---")
st.sidebar.info("数据源: Yahoo Finance + FRED (修复版)")

# --- 3. 辅助函数：从 FRED 获取数据 ---
def fetch_fred_series(series_id, start_date_str):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date_str}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text), index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index)
            # 强制去除时区信息，防止与 Yahoo 数据合并报错
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 4. 核心数据获取逻辑 ---
@st.cache_data(ttl=3600)
def get_combined_data(start_str):
    # A. 获取市场数据 (Yahoo)
    tickers = {"Nasdaq": "^IXIC", "USD_JPY": "JPY=X", "BTC": "BTC-USD", "VIX": "^VIX"}
    try:
        m_data = yf.download(list(tickers.values()), start=start_str, progress=False)['Close']
        if isinstance(m_data.columns, pd.MultiIndex):
            m_data.columns = m_data.columns.get_level_values(0)
        # 去除时区
        if m_data.index.tz is not None:
            m_data.index = m_data.index.tz_localize(None)
        m_data = m_data.rename(columns={v: k for k, v in tickers.items()})
    except:
        return pd.DataFrame()

    # B. 获取 FRED 宏观数据
    fred_ids = {'WALCL': 'WALCL', 'WTREGEN': 'WTREGEN', 'RRPONTSYD': 'RRPONTSYD'}
    f_aligned = pd.DataFrame(index=m_data.index)
    
    for key, s_id in fred_ids.items():
        f_data = fetch_fred_series(s_id, start_str)
        if not f_data.empty:
            # 将 FRED 周/月数据映射到每日交易日
            f_aligned[key] = f_data.iloc[:, 0].reindex(m_data.index, method='ffill')
    
    # C. 合并并计算净流动性
    df = m_data.join(f_aligned).ffill().dropna()
    if 'WALCL' in df.columns:
        # 公式: 总资产/1000 - TGA - 逆回购
        df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
    
    return df

# 加载数据
df = get_combined_data(start_date_str)

if df.empty:
    st.error("数据加载失败，请检查网络或稍后刷新。")
    st.stop()

# --- 5. 界面展示 ---
tab1, tab2, tab3 = st.tabs(["📊 趋势分析", "⚠️ 信号回测", "📑 原始数据"])

with tab1:
    col1, col2 = st.columns([3, 1])
    with col1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq Index"))
        if 'Net_Liquidity' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['Net_Liquidity'], name="Net Liquidity (B$)", yaxis="y2", line=dict(dash='dot')))
        
        fig.update_layout(
            title="流动性 vs 纳斯达克",
            yaxis=dict(title="Nasdaq"),
            yaxis2=dict(title="Liquidity", overlaying="y", side="right"),
            hovermode="x unified", height=500
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.write("#### 资产相关性")
        corr = df.corr()['Nasdaq'].sort_values(ascending=False).to_frame(name="相关系数")
        # --- 修复点：直接显示表格，不再调用 .style.background_gradient ---
        st.dataframe(corr, use_container_width=True)

with tab2:
    st.subheader("流动性冲击回测")
    st.write("逻辑：当 USD/JPY 10天内跌超 3% (即日元暴涨)，标记警报。")
    
    df['JPY_Chg_10d'] = df['USD_JPY'].pct_change(10)
    signals = df[df['JPY_Chg_10d'] < -0.03].index
    
    results = []
    for d in signals:
        try:
            p_now = df.loc[d, 'Nasdaq']
            future_d = d + timedelta(days=20)
            if future_d > df.index[-1]: continue
            idx = df.index.get_indexer([future_d], method='nearest')[0]
            p_future = df.iloc[idx]['Nasdaq']
            results.append({"日期": d.strftime('%Y-%m-%d'), "USD/JPY变动": df.loc[d, 'JPY_Chg_10d'], "Nasdaq 20天后涨跌": (p_future/p_now)-1})
        except: pass

    res_df = pd.DataFrame(results)
    
    c_a, c_b = st.columns([2, 1])
    with c_a:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq"))
        fig2.add_trace(go.Scatter(x=signals, y=df.loc[signals, 'Nasdaq'], mode='markers', name='信号点', marker=dict(color='red', size=8, symbol='triangle-down')))
        st.plotly_chart(fig2, use_container_width=True)
    with c_b:
        if not res_df.empty:
            # --- 修复点：使用简单的格式化，不再使用容易报错的 Styler ---
            st.dataframe(res_df.style.format({'USD/JPY变动': '{:.2%}', 'Nasdaq 20天后涨跌': '{:.2%}'}))
        else:
            st.write("未触发警报")

with tab3:
    st.dataframe(df.tail(100))