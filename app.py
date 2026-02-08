import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io
import requests

# --- 1. 页面基础配置 ---
st.set_page_config(page_title="宏观流动性回测系统 Pro", layout="wide")
st.title("🔬 宏观流动性 vs 崩盘归因分析系统 (Pro Ver.)")

# --- 2. 侧边栏配置 ---
st.sidebar.header("回测参数")
years_back = st.sidebar.slider("回溯年份", 1, 5, 3)
start_date = datetime.now() - timedelta(days=years_back*365)
start_date_str = start_date.strftime('%Y-%m-%d')

st.sidebar.markdown("---")
st.sidebar.info("数据源: Yahoo Finance + FRED (直连修复版)")

# --- 3. 核心函数：从 FRED 获取数据 (无需第三方库) ---
def fetch_fred_series(series_id, start_date_str):
    """
    使用 requests 直接读取 FRED 的 CSV 接口，
    并强制转换为无时区格式，防止与 Yahoo 数据冲突。
    """
    try:
        # 伪装 User-Agent 防止被拦截
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date_str}"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            # 读取 CSV
            df = pd.read_csv(io.StringIO(response.text), index_col=0, parse_dates=True)
            # 确保是日期索引
            df.index = pd.to_datetime(df.index)
            # 【关键修复】强制去除时区信息
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
        else:
            return pd.DataFrame() # 返回空表
    except Exception:
        return pd.DataFrame()

# --- 4. 主数据获取逻辑 ---
@st.cache_data(ttl=3600)
def get_macro_data(start_str):
    # --- A. 获取市场数据 (Yahoo) ---
    market_tickers = {
        "Nasdaq": "^IXIC",          
        "USD_JPY": "JPY=X",         
        "BTC": "BTC-USD",           
        "VIX": "^VIX"               
    }
    
    # 下载数据
    try:
        market_data = yf.download(list(market_tickers.values()), start=start_str, progress=False)['Close']
    except Exception as e:
        st.error(f"Yahoo Finance 数据下载失败: {e}")
        return pd.DataFrame()
    
    # 清洗 Yahoo 数据 (处理 MultiIndex)
    if isinstance(market_data.columns, pd.MultiIndex):
        market_data.columns = market_data.columns.get_level_values(0)
    
    # 【关键修复】强制去除 Yahoo 数据的时区信息
    if market_data.index.tz is not None:
        market_data.index = market_data.index.tz_localize(None)
    
    # 重命名列
    inv_map = {v: k for k, v in market_tickers.items()}
    market_data = market_data.rename(columns=inv_map)
    
    # --- B. 获取美联储数据 (FRED) ---
    # WALCL: 美联储总资产 (Millions)
    # WTREGEN: 财政部TGA账户 (Billions)
    # RRPONTSYD: 逆回购RRP (Billions)
    fred_ids = {'WALCL': 'WALCL', 'WTREGEN': 'WTREGEN', 'RRPONTSYD': 'RRPONTSYD'}
    fred_frames = {}
    
    for key, series_id in fred_ids.items():
        data = fetch_fred_series(series_id, start_str)
        if not data.empty:
            fred_frames[key] = data.iloc[:, 0] # 取第一列数据
        else:
            # 如果下载失败，创建一个全空的 Series，防止后续报错
            fred_frames[key] = pd.Series(index=market_data.index, dtype=float)

    # --- C. 数据对齐与合并 ---
    # 创建一个对齐后的 DataFrame
    fred_aligned = pd.DataFrame(index=market_data.index)
    
    # 将 FRED 数据 (通常是周度/月度) 填充到 市场数据 (日度)
    for key, series in fred_frames.items():
        fred_aligned[key] = series.reindex(market_data.index, method='ffill')
    
    # 合并所有数据
    df = market_data.join(fred_aligned).ffill().dropna()
    
    # --- D. 计算净流动性 (Net Liquidity) ---
    # 公式: Fed Balance Sheet - TGA - RRP
    # 注意单位换算：WALCL 是 Millions，需要除以 1000 变成 Billions
    if 'WALCL' in df.columns and 'WTREGEN' in df.columns:
        df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
    else:
        df['Net_Liquidity'] = 0
    
    return df

# --- 5. 执行数据加载 ---
df = get_macro_data(start_date_str)

# 容错：如果数据为空
if df.empty:
    st.error("无法获取数据。可能是 Yahoo Finance 或 FRED 接口暂时不可用，请稍后刷新重试。")
    st.stop()

# 计算相关性矩阵
corr_matrix = df.corr()

# --- 6. 界面展示层 ---
tab1, tab2, tab3 = st.tabs(["📈 深度趋势对比", "⚠️ 预警信号回测", "🧮 原始数据"])

# === TAB 1: 趋势图 ===
with tab1:
    st.subheader("流动性 vs 资产价格历史走势")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        fig = go.Figure()
        # 左轴：纳斯达克
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq Index", line=dict(color='cyan', width=2)))
        
        # 右轴：净流动性 (如果有数据)
        if df['Net_Liquidity'].sum() != 0:
            fig.add_trace(go.Scatter(x=df.index, y=df['Net_Liquidity'], name="Fed Net Liquidity (B$)", 
                                     line=dict(color='orange', dash='dot'), yaxis='y2'))
        
        # 右轴：日元
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
        st.write("#### 核心相关性")
        if 'Nasdaq' in corr_matrix.columns:
            # 提取相关性并转为 DataFrame 避免样式报错
            target_corr = corr_matrix['Nasdaq'].sort_values(ascending=False).to_frame(name="Correlation")
            st.dataframe(target_corr)
            st.caption("正相关性越高(接近1)，说明股市越依赖该指标。")

# === TAB 2: 回测系统 ===
with tab2:
    st.subheader("🕵️‍♀️ 危机预警回测 (Backtesting)")
    st.markdown("逻辑：当 **USD/JPY** 在 10 天内快速升值（数值下跌）超过 3%，标记为流动性冲击信号。")

    if 'USD_JPY' in df.columns:
        # 计算 10 天变化率
        df['JPY_Chg_10d'] = df['USD_JPY'].pct_change(10)
        
        # 筛选信号点
        signals = df[df['JPY_Chg_10d'] < -0.03].index
        
        results = []
        for date in signals:
            try:
                price_at_signal = df.loc[date]['Nasdaq']
                target_date = date + timedelta(days=20)
                
                # 如果超出数据范围则跳过
                if target_date > df.index[-1]: continue
                
                # 寻找最近的交易日
                idx_loc = df.index.get_indexer([target_date], method='nearest')[0]
                price_after_20d = df.iloc[idx_loc]['Nasdaq']
                
                # 计算跌幅
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
            
            # 标记信号
            y_vals = df.loc[signals]['Nasdaq']
            fig_sig.add_trace(go.Scatter(
                x=signals, y=y_vals, mode='markers', name='流动性警报',
                marker=dict(color='red', size=10, symbol='triangle-down')
            ))
            st.plotly_chart(fig_sig, use_container_width=True)
            
        with col_b:
            st.write("#### 历史警报统计")
            if not res_df.empty:
                # 简单展示数据，不使用复杂的样式以防报错
                st.dataframe(res_df.style.format({
                    'USD/JPY 10天跌幅': '{:.2%}', 
                    'Nasdaq 20天后表现': '{:.2%}'
                }))
            else:
                st.info("当前参数下，过去几年未触发极端警报。")

# === TAB 3: 原始数据 ===
with tab3:
    st.dataframe(df.tail(50))