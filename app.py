import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests

# --- 1. 指标元数据配置 (定义、解释与回测逻辑) ---
METADATA = {
    "USD_JPY": {
        "name": "🇯🇵 日元汇率 (USD/JPY)",
        "desc": "**日元套利平仓风向标**。当日元大幅升值（汇率下跌），意味着借日元买美股的投机者正在抛售资产还债。",
        "why": "这是 XinGPT 理论的核心。日元暴力升值通常领先于美股暴跌 5-10 天。",
        "threshold": -0.03, # 10天跌3%
        "signal_desc": "10天内汇率下跌（日元升值）超过 3%"
    },
    "Net_Liquidity": {
        "name": "🌊 美联储净流动性 (Net Liquidity)",
        "desc": "**市场的‘真钱’总量**。由美联储资产负债表减去政府存款和逆回购得出。",
        "why": "当钱变少时，股市即便上涨也是虚火（背离），随后必有踩踏。",
        "threshold": -0.02, # 10天跌2%
        "signal_desc": "10天内净流动性萎缩超过 2%"
    },
    "TLT_Bonds": {
        "name": "📉 长债价格 (TLT)",
        "desc": "**20年期以上美国国债价格**。它跌意味着利率涨，折现率压力增大。",
        "why": "如果股市跌、债市也跌（TLT跌），说明避险失效，进入‘股债双杀’的流动性枯竭模式。",
        "threshold": -0.04, # 10天跌4%
        "signal_desc": "10天内长债价格下跌超过 4%"
    },
    "VIX": {
        "name": "😨 恐慌指数 (VIX)",
        "desc": "**市场波动率预期**。反映投资者对未来30天市场剧烈波动的担忧程度。",
        "why": "VIX 暴力拉升通常预示着机构正在疯狂买入期权避险，是暴跌进行时的信号。",
        "threshold": 0.20, # 10天涨20%
        "signal_desc": "10天内 VIX 飙升超过 20%"
    },
    "Gold": {
        "name": "🥇 黄金 (Gold)",
        "desc": "**终极信用对冲工具**。不属于任何政府的负债。",
        "why": "如果黄金与美元同涨，说明市场在担忧美元信用或地缘政治危机。",
        "threshold": 0.04, # 10天涨4%
        "signal_desc": "10天内金价上涨超过 4%"
    },
    "XLE_Energy": {
        "name": "⛽ 能源板块 (XLE)",
        "desc": "**标普能源行业 ETF**。代表石油与天然气的硬资产价格。",
        "why": "在滞胀或美元贬值背景下，能源股是极少数能提供正向收益的‘硬资产’。",
        "threshold": -0.05,
        "signal_desc": "10天内能源板块下跌超过 5% (潜在衰退信号)"
    }
}

# --- 2. 页面配置 ---
st.set_page_config(page_title="宏观监控 Pro", layout="wide")
st.title("🔬 宏观流动性与硬资产观测系统")

# --- 3. 侧边栏 ---
st.sidebar.header("参数设置")
years_back = st.sidebar.slider("回溯年份", 1, 5, 3)
start_date = datetime.now() - timedelta(days=years_back*365)
start_date_str = start_date.strftime('%Y-%m-%d')

# --- 4. 数据获取 ---
def fetch_fred_series(series_id, start_date_str):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date_str}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index).tz_localize(None)
            return df
        return pd.DataFrame()
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_data(start_str):
    tickers = {"Nasdaq": "^IXIC", "USD_JPY": "JPY=X", "Gold": "GC=F", "XLE_Energy": "XLE", "TLT_Bonds": "TLT", "VIX": "^VIX"}
    m_data = yf.download(list(tickers.values()), start=start_str, progress=False)['Close']
    if isinstance(m_data.columns, pd.MultiIndex): m_data.columns = m_data.columns.get_level_values(0)
    m_data.index = m_data.index.tz_localize(None)
    m_data = m_data.rename(columns={v: k for k, v in tickers.items()})

    f_ids = {'WALCL': 'WALCL', 'WTREGEN': 'WTREGEN', 'RRPONTSYD': 'RRPONTSYD'}
    f_aligned = pd.DataFrame(index=m_data.index)
    for key, s_id in f_ids.items():
        data = fetch_fred_series(s_id, start_str)
        if not data.empty: f_aligned[key] = data.iloc[:, 0].reindex(m_data.index, method='ffill')
    
    df = m_data.join(f_aligned).ffill().dropna()
    if 'WALCL' in df.columns:
        df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
    return df

df = load_data(start_date_str)

# --- 5. 核心页面逻辑 ---
tab1, tab2, tab3 = st.tabs(["📊 动态对比分析", "⚠️ 危机信号回测", "📑 原始数据明细"])

# === TAB 1: 动态对比 ===
with tab1:
    col_sel, col_desc = st.columns([1, 2])
    with col_sel:
        target = st.selectbox("选择对比指标 (右轴):", [k for k in METADATA.keys() if k in df.columns])
    
    # 动态显示指标百科内容
    with col_desc:
        info = METADATA[target]
        st.markdown(f"**指标定义**: {info['desc']}")
        st.markdown(f"**宏观逻辑**: {info['why']}")

    st.divider()
    
    c_chart, c_stat = st.columns([3, 1])
    with c_chart:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq", line=dict(color='cyan', width=2)))
        fig.add_trace(go.Scatter(x=df.index, y=df[target], name=target, yaxis='y2', line=dict(color='orange', dash='dot')))
        fig.update_layout(
            yaxis=dict(title="Nasdaq Index"),
            yaxis2=dict(title=target, overlaying='y', side='right'),
            hovermode="x unified", height=500, margin=dict(t=20, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with c_stat:
        st.metric("相关系数 (Corr)", f"{df['Nasdaq'].corr(df[target]):.2f}")
        st.write("**最近10日变动**")
        st.write(f"Nasdaq: {df['Nasdaq'].pct_change(10).iloc[-1]:.2%}")
        st.write(f"{target}: {df[target].pct_change(10).iloc[-1]:.2%}")

# === TAB 2: 危机信号回测 ===
with tab2:
    col_t2_sel, col_t2_desc = st.columns([1, 2])
    with col_t2_sel:
        signal_target = st.selectbox("选择预警因子:", [k for k in METADATA.keys() if k in df.columns], key="t2_sel")
    
    with col_t2_desc:
        s_info = METADATA[signal_target]
        st.markdown(f"**触发逻辑**: {s_info['signal_desc']}")
        st.caption("回测规则：当该因子触发显著变动时，计算 20 个交易日后纳斯达克的累计涨跌幅。")

    st.divider()
    
    # 计算信号
    threshold = METADATA[signal_target]['threshold']
    df['change_10d'] = df[signal_target].pct_change(10)
    
    # 根据正负方向判定信号
    if threshold < 0:
        signals = df[df['change_10d'] < threshold].index
    else:
        signals = df[df['change_10d'] > threshold].index

    results = []
    for d in signals:
        try:
            p_start = df.loc[d, 'Nasdaq']
            future_d = d + timedelta(days=20)
            if future_d > df.index[-1]: continue
            idx = df.index.get_indexer([future_d], method='nearest')[0]
            p_end = df.iloc[idx]['Nasdaq']
            results.append({
                "触发日期": d.strftime('%Y-%m-%d'),
                "因子变动": df.loc[d, 'change_10d'],
                "Nasdaq 20天后涨跌": (p_end/p_start)-1
            })
        except: pass

    if results:
        res_df = pd.DataFrame(results).drop_duplicates(subset=['触发日期'])
        c1, c2 = st.columns([2, 1])
        with c1:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq"))
            fig2.add_trace(go.Scatter(x=signals, y=df.loc[signals, 'Nasdaq'], mode='markers', name='预警信号', 
                                     marker=dict(color='red', size=8, symbol='triangle-down')))
            st.plotly_chart(fig2, use_container_width=True)
        with c2:
            st.write("**历史触发明细**")
            st.dataframe(res_df.style.format({'因子变动': '{:.2%}', 'Nasdaq 20天后涨跌': '{:.2%}'}))
            
            win_rate = (res_df['Nasdaq 20天后涨跌'] < 0).mean()
            st.metric("预警准确率 (下跌概率)", f"{win_rate:.1%}")
    else:
        st.info("该因子在当前参数下未触发任何历史信号。")

# === TAB 3: 原始数据 ===
with tab3:
    st.write(f"数据范围: {df.index[0].date()} 至 {df.index[-1].date()}")
    # 修复显示 Bug，确保 dataframe 正常渲染
    st.dataframe(df.sort_index(ascending=False), use_container_width=True)
    st.caption("注：WALCL, WTREGEN, RRPONTSYD 单位为百万/十亿美元，Net_Liquidity 为计算后的净额。")