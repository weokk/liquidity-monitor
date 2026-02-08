import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 页面配置 ---
st.set_page_config(page_title="宏观流动性观测仪", layout="wide")

st.title("🌊 宏观流动性 vs AI叙事 观测模型")
st.markdown("Based on XinGPT Logic: **The Crash is about Liquidity (JPY Carry Trade), not AI.**")

# --- 侧边栏配置 ---
st.sidebar.header("参数设置")
days_back = st.sidebar.selectbox("观测时间窗口", ["1mo", "3mo", "6mo", "1y", "ytd"], index=1)
st.sidebar.info("数据来源: Yahoo Finance (约15分钟延迟)")

# --- 核心数据定义 ---
# 字典格式: {"显示名称": "Yahoo代码"}
ASSETS = {
    "🇯🇵 日元汇率 (JPY=X)": "JPY=X",   # USD/JPY: 下跌代表日元升值(流动性紧缩)
    "🇺🇸 10年美债 (US10Y)": "^TNX",    # 无风险利率
    "😨 恐慌指数 (VIX)": "^VIX",      # 市场恐慌度
    "📉 纳斯达克 (Nasdaq)": "^IXIC",  # 科技股整体
    "☁️ SaaS软件 (IGV)": "IGV",       # 被认为"受AI冲击"的板块
    "🤖 英伟达 (NVDA)": "NVDA"        # AI 信仰核心
}

# --- 数据获取函数 (带缓存，防止重复下载) ---
@st.cache_data(ttl=300) # 缓存5分钟
def get_market_data(period):
    tickers = list(ASSETS.values())
    # 批量下载数据
    data = yf.download(tickers, period=period, progress=False)['Close']
    
    # yfinance 有时会返回多层索引，这里做一下清洗
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    
    # 重命名列名为易读名称
    rename_map = {v: k for k, v in ASSETS.items()}
    data = data.rename(columns=rename_map)
    
    # 填充空值（用前值填充）
    data = data.ffill().dropna()
    return data

# --- 加载数据 ---
try:
    df = get_market_data(days_back)
    
    # 计算最新价格和涨跌幅
    latest_price = df.iloc[-1]
    prev_price = df.iloc[-2]
    pct_change = (latest_price - prev_price) / prev_price

    # --- 第一部分：关键指标仪表盘 ---
    st.subheader("📊 实时压力指标")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        name = "🇯🇵 日元汇率 (JPY=X)"
        val = latest_price[name]
        chg = pct_change[name]
        st.metric(name, f"{val:.2f}", f"{chg:.2%}", delta_color="inverse") 
        st.caption("注：此值大跌 = 日元升值 = 流动性危机")

    with col2:
        name = "🇺🇸 10年美债 (US10Y)"
        val = latest_price[name]
        chg = pct_change[name]
        st.metric(name, f"{val:.2f}", f"{chg:.2%}", delta_color="inverse")

    with col3:
        name = "📉 纳斯达克 (Nasdaq)"
        val = latest_price[name]
        chg = pct_change[name]
        st.metric(name, f"{val:.0f}", f"{chg:.2%}")

    with col4:
        name = "☁️ SaaS软件 (IGV)"
        val = latest_price[name]
        chg = pct_change[name]
        st.metric(name, f"{val:.2f}", f"{chg:.2%}")

    # --- 第二部分：核心逻辑验证图表 ---
    st.divider()
    st.subheader("🧐 核心验证：谁在主导下跌？")
    
    # 数据归一化（Normalize），让所有资产从起点(0%)开始比较
    normalized_df = (df / df.iloc[0] - 1) * 100
    
    assets_to_plot = st.multiselect(
        "选择对比资产 (默认对比日元汇率与纳斯达克)",
        list(ASSETS.keys()),
        default=["🇯🇵 日元汇率 (JPY=X)", "📉 纳斯达克 (Nasdaq)", "☁️ SaaS软件 (IGV)"]
    )
    
    if assets_to_plot:
        fig = go.Figure()
        for asset in assets_to_plot:
            fig.add_trace(go.Scatter(x=normalized_df.index, y=normalized_df[asset], mode='lines', name=asset))
        
        fig.update_layout(
            title=f"过去 {days_back} 走势对比 (归一化 %)",
            xaxis_title="日期",
            yaxis_title="累计涨跌幅 (%)",
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- 第三部分：结论区 ---
    st.info("""
    **如何解读？**
    1. **流动性危机模式：** 如果 `日元汇率` 线条大幅向下（升值），且 `纳斯达克` 同步向下。 -> 验证 XinGPT 观点。
    2. **AI 泡沫破裂模式：** 如果 `日元汇率` 平稳，但 `SaaS软件` 和 `纳斯达克` 独自暴跌。 -> 可能是 AI 替代逻辑或行业内因。
    """)

except Exception as e:
    st.error(f"数据加载失败，可能是 Yahoo Finance 暂时限流，请稍后刷新页面。错误信息: {e}")