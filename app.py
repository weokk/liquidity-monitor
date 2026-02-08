import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 配置 ---
st.set_page_config(page_title="宏观流动性回测系统 Pro", layout="wide")
st.title("🔬 宏观流动性 vs 崩盘归因分析系统 (Pro Ver.)")

# --- 侧边栏 ---
st.sidebar.header("回测参数")
years_back = st.sidebar.slider("回溯年份", 1, 5, 3)
# 计算开始时间
start_date = datetime.now() - timedelta(days=years_back*365)
start_date_str = start_date.strftime('%Y-%m-%d')

st.sidebar.markdown("---")
st.sidebar.info("数据源: Yahoo Finance (市场) + FRED (美联储直连)")

# --- 辅助函数：直接从 FRED 获取 CSV ---
# 这是一个更稳健的方法，不需要 pandas_datareader
def fetch_fred_series(series_id, start_date):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}"
        df = pd.read_csv(url, index_col='DATE', parse_dates=True)
        return df
    except Exception as e:
        st.warning(f"无法获取 FRED 数据 {series_id}: {e}")
        return pd.DataFrame()

# --- 核心数据获取 ---
@st.cache_data(ttl=3600)
def get_macro_data(start_str):
    # 1. 获取市场数据 (Yahoo)
    market_tickers = {
        "Nasdaq": "^IXIC",          # 科技股
        "USD_JPY": "JPY=X",         # 日元汇率
        "BTC": "BTC-USD",           # 流动性敏锐度
        "VIX": "^VIX"               # 恐慌
    }
    # yfinance 这里的 start 需要是 string 格式
    market_data = yf.download(list(market_tickers.values()), start=start_str, progress=False)['Close']
    
    # 清洗 Yahoo 数据格式
    if isinstance(market_data.columns, pd.MultiIndex):
        market_data.columns = market_data.columns.get_level_values(0)
    inv_map = {v: k for k, v in market_tickers.items()}
    market_data = market_data.rename(columns=inv_map)
    
    # 2. 获取美联储数据 (直接 CSV 链接)
    # WALCL: 美联储总资产
    # WTREGEN: 财政部账户 (TGA)
    # RRPONTSYD: 逆回购 (RRP)
    fred_walcl = fetch_fred_series('WALCL', start_str)
    fred_tga = fetch_fred_series('WTREGEN', start_str)
    fred_rrp = fetch_fred_series('RRPONTSYD', start_str)

    # 3. 合并数据
    # 先把 FRED 数据拼起来
    fred_df = pd.DataFrame(index=market_data.index) # 以市场交易日为基准
    
    # 将 FRED 的周度/日度数据映射到市场交易日（前值填充）
    fred_df['WALCL'] = fred_walcl.reindex(market_data.index, method='ffill')
    fred_df['WTREGEN'] = fred_tga.reindex(market_data.index, method='ffill')
    fred_df['RRPONTSYD'] = fred_rrp.reindex(market_data.index, method='ffill')
    
    # 合并所有数据
    df = market_data.join(fred_df).ffill().dropna()
    
    # 4. 计算"净流动性" (Net Liquidity)
    # 公式: Fed Balance Sheet - TGA - RRP (单位转换成 Billions)
    # 注意：原始数据单位可能不同，通常 FRED 这些数据单位是 Millions (百万) 或 Billions
    # WALCL 是 Millions, WTREGEN 是 Billions, RRP 是 Billions. 
    # 统一转换成 Billions:
    
    # 修正数据单位逻辑：
    # WALCL (Millions) -> /1000 -> Billions
    # WTREGEN (Billions) -> 保持
    # RRPONTSYD (Billions) -> 保持
    
    df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
    
    return df

# 获取数据
df = get_macro_data(start_date_str)

# --- 逻辑分析层 ---
corr_matrix = df.corr()

# --- 界面展示 ---
tab1, tab2, tab3 = st.tabs(["📈 深度趋势对比", "⚠️ 预警信号回测", "🧮 原始数据"])

with tab1:
    st.subheader("流动性 vs 资产价格历史走势")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        fig = go.Figure()
        # 左轴：纳斯达克
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq Index", line=dict(color='cyan', width=2)))
        
        # 右轴：净流动性
        fig.add_trace(go.Scatter(x=df.index, y=df['Net_Liquidity'], name="Fed Net Liquidity (B$)", 
                                 line=dict(color='orange', dash='dot'), yaxis='y2'))
        
        # 右轴：日元
        fig.add_trace(go.Scatter(x=df.index, y=df['USD_JPY'], name="USD/JPY (汇率)", 
                                 line=dict(color='red', width=1), yaxis='y2', visible='legendonly'))

        fig.update_layout(
            title="美联储净流动性 vs 纳斯达克 (这就是'真钱'去向)",
            yaxis=dict(title="Nasdaq Index"),
            yaxis2=dict(title="Liquidity / JPY", overlaying='y', side='right'),
            hovermode="x unified",
            height=500,
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.write("#### 核心相关性矩阵")
        # 重点展示 Nasdaq 与各因子的相关性
        if 'Nasdaq' in corr_matrix.columns:
            target_corr = corr_matrix['Nasdaq'].sort_values(ascending=False)
            st.dataframe(target_corr.style.background_gradient(cmap='RdYlGn'))
        st.caption("注：Net_Liquidity 正相关性越高，说明股市越依赖央行放水。")

with tab2:
    st.subheader("🕵️‍♀️ 危机预警回测 (Backtesting Signals)")
    st.markdown("我们定义一个**'流动性冲击信号'**: 当 USD/JPY 在 10 天内快速升值（数值下跌）超过 3%，视为流动性抽离。")

    # 计算 USD/JPY 10天变化率
    df['JPY_Chg_10d'] = df['USD_JPY'].pct_change(10)
    
    # 触发信号：USD/JPY 跌幅超过 3%
    signals = df[df['JPY_Chg_10d'] < -0.03].index
    
    results = []
    for date in signals:
        try:
            price_at_signal = df.loc[date]['Nasdaq']
            # 寻找信号后 20 天的表现
            target_date = date + timedelta(days=20)
            if target_date > df.index[-1]: continue
            
            # 找到最近的交易日
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
        # 标记信号点
        y_vals = df.loc[signals]['Nasdaq']
        fig_sig.add_trace(go.Scatter(
            x=signals, y=y_vals, mode='markers', name='流动性警报',
            marker=dict(color='red', size=10, symbol='triangle-down')
        ))
        st.plotly_chart(fig_sig, use_container_width=True)
        
    with col_b:
        st.write("#### 历史警报列表")
        if not res_df.empty:
            st.dataframe(
                res_df.style.format({
                    'USD/JPY 10天跌幅': '{:.2%}',
                    'Nasdaq 20天后表现': '{:.2%}'
                }).applymap(lambda x: 'color: red' if x < 0 else 'color: green', subset=['Nasdaq 20天后表现']),
                height=400
            )
        else:
            st.write("当前参数下，过去几年未触发极端警报。")

with tab3:
    st.dataframe(df.tail(50))