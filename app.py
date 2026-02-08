import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests

# --- 1. 页面基础配置 ---
st.set_page_config(page_title="宏观流动性与硬资产观测站", layout="wide")
st.title("🔬 宏观流动性 vs 崩盘归因分析系统 (Pro Ver. 2.0)")

# --- 2. 侧边栏配置 ---
st.sidebar.header("回测参数设置")
years_back = st.sidebar.slider("历史回溯年份", 1, 5, 3)
start_date = datetime.now() - timedelta(days=years_back*365)
start_date_str = start_date.strftime('%Y-%m-%d')

st.sidebar.markdown("---")
st.sidebar.write("**资产池状态：** 实时连接 Yahoo Finance & FRED")

# --- 3. 核心辅助函数：数据获取 ---
def fetch_fred_series(series_id, start_date_str):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date_str}"
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text), index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_full_data(start_str):
    # 定义所有观测标的
    tickers = {
        "Nasdaq": "^IXIC",          # 科技大盘
        "USD_JPY": "JPY=X",         # 日元汇率 (流动性)
        "Gold": "GC=F",             # 黄金 (避险/抗通胀)
        "XLE_Energy": "XLE",        # 能源板块 (硬资产)
        "XME_Metals": "XME",        # 金属采矿 (硬资产)
        "TLT_Bonds": "TLT",         # 20年美债价格 (利率风向标)
        "VIX": "^VIX",              # 恐慌指数
        "BTC": "BTC-USD"            # 数字黄金/流动性敏感指标
    }
    
    # 获取市场数据
    try:
        m_data = yf.download(list(tickers.values()), start=start_str, progress=False)['Close']
        if isinstance(m_data.columns, pd.MultiIndex):
            m_data.columns = m_data.columns.get_level_values(0)
        if m_data.index.tz is not None:
            m_data.index = m_data.index.tz_localize(None)
        m_data = m_data.rename(columns={v: k for k, v in tickers.items()})
    except Exception:
        return pd.DataFrame()

    # 获取 FRED 流动性指标
    fred_ids = {'WALCL': 'WALCL', 'WTREGEN': 'WTREGEN', 'RRPONTSYD': 'RRPONTSYD'}
    f_aligned = pd.DataFrame(index=m_data.index)
    for key, s_id in fred_ids.items():
        f_data = fetch_fred_series(s_id, start_str)
        if not f_data.empty:
            f_aligned[key] = f_data.iloc[:, 0].reindex(m_data.index, method='ffill')
    
    # 合并
    df = m_data.join(f_aligned).ffill().dropna()
    
    # 计算美联储净流动性
    if 'WALCL' in df.columns:
        df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
        
    return df

# 执行加载
df = get_full_data(start_date_str)

if df.empty:
    st.error("无法加载数据，请检查网络后刷新。")
    st.stop()

# --- 4. 界面展示：分析与对比 ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 动态对比分析", "⚠️ 危机信号回测", "📖 指标百科", "📑 原始数据"])

# === TAB 1: 动态对比 ===
with tab1:
    st.subheader("纳斯达克 vs 宏观因子 对比图")
    
    # 选择要对比的指标
    comparison_options = [col for col in df.columns if col != "Nasdaq"]
    target_indicator = st.selectbox("选择对比指标 (右轴展示):", comparison_options, index=comparison_options.index("Net_Liquidity") if "Net_Liquidity" in comparison_options else 0)
    
    col_chart, col_stat = st.columns([3, 1])
    
    with col_chart:
        fig = go.Figure()
        # 左轴：纳斯达克
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq Index", line=dict(color='cyan', width=2)))
        
        # 右轴：所选指标
        fig.add_trace(go.Scatter(x=df.index, y=df[target_indicator], name=target_indicator, 
                                 line=dict(color='orange', dash='dot'), yaxis='y2'))

        fig.update_layout(
            title=f"Nasdaq vs {target_indicator}",
            yaxis=dict(title="Nasdaq Index (Price)"),
            yaxis2=dict(title=target_indicator, overlaying='y', side='right'),
            hovermode="x unified",
            height=600,
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
    with col_stat:
        st.write("#### 实时相关性")
        corr_val = df['Nasdaq'].corr(df[target_indicator])
        st.metric("相关系数 (Corr)", f"{corr_val:.2f}")
        
        st.write("#### 涨跌幅对比 (10日)")
        n_chg = df['Nasdaq'].pct_change(10).iloc[-1]
        i_chg = df[target_indicator].pct_change(10).iloc[-1]
        st.metric("Nasdaq (10D)", f"{n_chg:.2%}")
        st.metric(f"{target_indicator} (10D)", f"{i_chg:.2%}")

# === TAB 2: 信号回测 ===
with tab2:
    st.subheader("流动性冲击预警 (USD/JPY 模式)")
    st.write("逻辑：当日元在10天内升值超过3%（USD/JPY下跌），观察之后20天纳斯达克的表现。")
    
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
            results.append({"信号日期": d.strftime('%Y-%m-%d'), "日元变动": df.loc[d, 'JPY_Chg_10d'], "Nasdaq 20天后表现": (p_end/p_start)-1})
        except: pass

    if results:
        res_df = pd.DataFrame(results)
        c1, c2 = st.columns([2, 1])
        with c1:
            fig_sig = go.Figure()
            fig_sig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq"))
            fig_sig.add_trace(go.Scatter(x=signals, y=df.loc[signals, 'Nasdaq'], mode='markers', name='信号触发', marker=dict(color='red', size=8, symbol='triangle-down')))
            st.plotly_chart(fig_sig, use_container_width=True)
        with c2:
            st.dataframe(res_df.style.format({'日元变动': '{:.2%}', 'Nasdaq 20天后表现': '{:.2%}'}))
    else:
        st.info("所选时间范围内未触发信号。")

# === TAB 3: 指标百科 ===
with tab3:
    st.subheader("💡 核心观测指标深度解析")
    
    descriptions = {
        "🇯🇵 USD_JPY (日元汇率)": """
        **宏观逻辑**：这是“流动性抽离”的第一风向标。
        - **下跌（日元升值）**：代表全球套利交易平仓（Carry Trade Unwind）。投资者卖出美股换回日元还债。
        - **预警意义**：如果日元剧烈暴涨而股市下跌，验证了“流动性是真凶”理论。
        """,
        "🌊 Net_Liquidity (净流动性)": """
        **计算公式**：美联储总资产 - 财政部TGA账户 - 逆回购RRP。
        - **意义**：这是市场上流通的“真钱”。
        - **预警意义**：当此指标与纳斯达克出现顶背离（流动性下行而股市上行）时，意味着股市处于纯估值扩张（泡沫）阶段，极易崩盘。
        """,
        "⛽ XLE_Energy (能源板块)": """
        **宏观逻辑**：代表原油与天然气资产。
        - **股债双杀场景**：如果美元跌、美债跌、股市跌，由于能源是生存刚需，且以美元计价，XLE通常能提供避险收益。
        - **核心标的**：Exxon Mobil (XOM), Chevron (CVX)。
        """,
        "⛏️ XME_Metals (金属采矿)": """
        **宏观逻辑**：硬资产的典型代表。
        - **意义**：包含铜、钢铁和铝。在美元信用受损、通胀飙升的场景下，这些物理资产具有保值属性。
        - **观测点**：当美元指数下跌时，XME通常逆势走强。
        """,
        "🥇 Gold (黄金)": """
        **宏观逻辑**：最终防线。
        - **意义**：不属于任何政府的负债。在“股债汇三杀”中，黄金是唯一的终极避险资产。
        - **预警意义**：黄金价格突破历史新高往往伴随着市场对美元信用的不信任。
        """,
        "📉 TLT_Bonds (长债价格)": """
        **宏观逻辑**：无风险利率的反向指标。
        - **下跌（收益率涨）**：代表通胀预期失控或财政压力巨大。
        - **预警意义**：如果股市下跌时TLT也下跌，说明传统避险模式失效，市场处于最危险的“滞胀式崩盘”。
        """
    }
    
    for title, text in descriptions.items():
        with st.expander(title):
            st.write(text)

# === TAB 4: 原始数据 ===
with tab3:
    st.write("#### 最近 100 个交易日数据明细")
    st.dataframe(df.tail(100))