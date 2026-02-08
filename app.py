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
    """
    尝试从 FRED 获取数据，如果失败返回空 Series，
    并强制转换为无时区格式以匹配 Yahoo 数据。
    """
    try:
        # 使用 FRED 的直接下载接口
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date_str}"
        
        # 伪装成浏览器请求，防止被 FRED 拦截
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # 读取 CSV
            df = pd.read_csv(io.StringIO(response.text), index_col=0, parse_dates=True)
            
            # 确保索引是 DatetimeIndex
            df.index = pd.to_datetime(df.index)
            
            # 关键修复：强制去除时区信息 (Make TZ-naive)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
                
            return df
        else:
            st.warning(f"FRED 接口返回状态码 {response.status_code}: {series_id}")
            return pd.DataFrame()
    except Exception as e:
        st.warning(f"无法获取 FRED 数据 {series_id}: {e}")
        return pd.DataFrame()

# --- 核心数据逻辑 ---
@st.cache_data(ttl=3600)
def get_macro_data(start_str):
    # 1. 获取市场数据 (Yahoo)
    market_tickers = {
        "Nasdaq": "^IXIC",          
        "USD_JPY": "JPY=X",         
        "BTC": "BTC-USD",           
        "VIX": "^VIX"               
    }
    
    # 下载数据
    market_data = yf.download(list(market_tickers.values()), start=start_str, progress=False)['Close']
    
    # 清洗 Yahoo 数据格式 (处理 MultiIndex)
    if isinstance(market_data.columns, pd.MultiIndex):
        market_data.columns = market_data.columns.get_level_values(0)
    
    # 关键修复：强制去除 Yahoo 数据的时区信息
    # 这一步解决了 "Cannot compare dtypes" 错误
    if market_data.index.tz is not None:
        market_data.index = market_data.index.tz_localize(None)
    
    inv_map = {v: k for k, v in market_tickers.items()}
    market_data = market_data.rename(columns=inv_map)
    
    # 2. 获取美联储数据
    # WALCL: 总资产, WTREGEN: TGA, RRPONTSYD: 逆回购
    fred_ids = {'WALCL': 'WALCL', 'WTREGEN': 'WTREGEN', 'RRPONTSYD': 'RRPONTSYD'}
    fred_frames = {}
    
    for key, series_id in fred_ids.items():
        data = fetch_fred_series(series_id, start_str)
        # 如果获取到了数据，取第一列（通常是数值列）
        if not data.empty:
            fred_frames[key] = data.iloc[:, 0]
        else:
            # 如果失败，生成一个全 NaN 的 Series，防止代码崩溃
            fred_frames[key] = pd.Series(index=market_data.index, dtype=float)

    # 3. 数据对齐与合并
    # 创建一个新的 DataFrame 用于存放对齐后的 FRED 数据
    fred_aligned = pd.DataFrame(index=market_data.index)
    
    # 将 FRED 数据 (通常是周度/月度) 填充到 市场数据 (日度)
    # 使用 reindex + ffill (前值填充)
    for key, series in fred_frames.items():
        # 这里因为双方都已经去除了时区，reindex 不会再报错
        fred_aligned[key] = series.reindex(market_data.index, method='ffill')
    
    # 合并
    df = market_data.join(fred_aligned).ffill().dropna()
    
    # 4. 计算净流动性 (Net Liquidity)
    # 逻辑：有些 FRED 数据单位是 Million，有些是 Billion
    # WALCL (Millions) -> /1000 -> Billions
    # WTREGEN (Billions) -> 保持
    # RRPONTSYD (Billions) -> 保持
    
    # 容错处理：确保列存在且不是全空
    if 'WALCL' in df.columns and 'WTREGEN' in df.columns:
        df['Net_Liquidity'] = (df['WALCL']/1000 - df['WTREGEN'] - df['RRPONTSYD'])
    else:
        df['Net_Liquidity'] = 0  # 数据缺失时的默认值
    
    return df

# 执行获取
df = get_macro_data(start_date_str)

# --- 容错检查：如果数据全空 ---
if df.empty:
    st.error("数据下载完全失败，请检查网络或稍后重试。")
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
        
        # 只有在成功计算了流动性时才显示
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
            st.dataframe(target_corr.style.background_gradient(cmap='RdYlGn'))

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
                
                # 寻找最近交易日
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
                st.dataframe(res_df.style.format({'USD/JPY 10天跌幅': '{:.2%}', 'Nasdaq 20天后表现': '{:.2%}'})
                             .applymap(lambda x: 'color: red' if x < 0 else 'color: green', subset=['Nasdaq 20天后表现']))
            else:
                st.write("未触发警报。")

with tab3:
    st.dataframe(df.tail(50))