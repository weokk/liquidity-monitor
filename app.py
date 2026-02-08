import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import pandas_datareader.data as web
from datetime import datetime, timedelta

# --- 配置 ---
st.set_page_config(page_title="宏观流动性回测系统 Pro", layout="wide")
st.title("🔬 宏观流动性 vs 崩盘归因分析系统 (Pro Ver.)")

# --- 侧边栏 ---
st.sidebar.header("回测参数")
years_back = st.sidebar.slider("回溯年份", 1, 5, 3)
start_date = datetime.now() - timedelta(days=years_back*365)
st.sidebar.markdown("---")
st.sidebar.info("数据源: Yahoo Finance (市场) + FRED (美联储)")

# --- 核心数据获取 (Yahoo + FRED) ---
@st.cache_data(ttl=3600)
def get_macro_data(start):
    # 1. 获取市场数据 (Yahoo)
    market_tickers = {
        "Nasdaq": "^IXIC",          # 科技股
        "USD_JPY": "JPY=X",         # 日元汇率 (流动性反向指标)
        "BTC": "BTC-USD",           # 流动性敏锐度
        "VIX": "^VIX"               # 恐慌
    }
    market_data = yf.download(list(market_tickers.values()), start=start, progress=False)['Close']
    # 修复 MultiIndex 问题
    if isinstance(market_data.columns, pd.MultiIndex):
        market_data.columns = market_data.columns.get_level_values(0)
    
    # 重命名
    inv_map = {v: k for k, v in market_tickers.items()}
    market_data = market_data.rename(columns=inv_map)
    
    # 2. 获取美联储数据 (FRED - St. Louis Fed)
    # WALCL: 美联储总资产
    # WTREGEN: 财政部账户 (TGA)
    # RRPONTSYD: 逆回购 (RRP)
    try:
        fred_tickers = ['WALCL', 'WTREGEN', 'RRPONTSYD']
        fred_data = web.DataReader(fred_tickers, 'fred', start, datetime.now())
        
        # 3. 数据合并与对齐
        # FRED数据是周/日频不一，需要填充对齐到市场交易日
        df = market_data.join(fred_data, how='outer').ffill().dropna()
        
        # 4. 计算"净流动性" (Net Liquidity)
        # 单位换算成十亿 (Billions)
        # 公式: Net Liquidity = Fed Balance Sheet - TGA - RRP
        df['Net_Liquidity'] = (df['WALCL'] - df['WTREGEN'] - df['RRPONTSYD']) / 1000
        
        return df
    except Exception as e:
        st.error(f"FRED 数据获取失败: {e}")
        return market_data

df = get_macro_data(start_date)

# --- 逻辑分析层 ---
# 计算相关性与归一化
normalized_df = (df - df.min()) / (df.max() - df.min()) # Min-Max 归一化用于绘图
corr_matrix = df.corr()

# --- 界面展示 ---

# Tab 1: 深度图表分析
tab1, tab2, tab3 = st.tabs(["📈 深度趋势对比", "⚠️ 预警信号回测", "🧮 原始数据"])

with tab1:
    st.subheader("流动性 vs 资产价格历史走势")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # 双轴图表：左轴是价格，右轴是流动性
        fig = go.Figure()
        
        # 资产端 (左轴)
        fig.add_trace(go.Scatter(x=df.index, y=df['Nasdaq'], name="Nasdaq Index", line=dict(color='cyan', width=2)))
        
        # 流动性端 (右轴) - 美联储净流动性
        fig.add_trace(go.Scatter(x=df.index, y=df['Net_Liquidity'], name="Fed Net Liquidity (B$)", 
                                 line=dict(color='orange', dash='dot'), yaxis='y2'))
        
        # 辅助线 - 日元 (右轴)
        fig.add_trace(go.Scatter(x=df.index, y=df['USD_JPY'], name="USD/JPY (汇率)", 
                                 line=dict(color='red', width=1), yaxis='y2', visible='legendonly'))

        fig.update_layout(
            title="美联储净流动性 vs 纳斯达克 (这就是'真钱'去向)",
            yaxis=dict(title="Nasdaq Index"),
            yaxis2=dict(title="Liquidity / JPY", overlaying='y', side='right'),
            hovermode="x unified",
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.write("#### 核心相关性矩阵")
        st.write("看 **Nasdaq** 与谁的关系最铁？")
        # 重点展示 Nasdaq 与各因子的相关性
        target_corr = corr_matrix['Nasdaq'].sort_values(ascending=False)
        st.dataframe(target_corr.style.background_gradient(cmap='RdYlGn'))
        st.info("💡 **解读**: 如果Net_Liquidity相关性高，说明是央行放水驱动；如果USD_JPY正相关性极高(>0.8)，说明是套利交易驱动。")

with tab2:
    st.subheader("🕵️‍♀️ 危机预警回测 (Backtesting Signals)")
    st.markdown("我们定义一个**'流动性冲击信号'**: 当 USD/JPY 在 10 天内快速升值（数值下跌）超过 3%，视为流动性抽离。")

    # --- 信号计算 ---
    # 计算 USD/JPY 10天变化率
    df['JPY_Chg_10d'] = df['USD_JPY'].pct_change(10)
    
    # 触发信号：USD/JPY 跌幅超过 3% (即日元升值3%)
    signals = df[df['JPY_Chg_10d'] < -0.03].index
    
    # 寻找信号后的纳斯达克表现
    results = []
    for date in signals:
        try:
            # 获取信号当天的价格
            price_at_signal = df.loc[date]['Nasdaq']
            # 获取信号后 20 天的价格（如果没有20天后的数据则跳过）
            target_date = date + timedelta(days=20)
            if target_date > df.index[-1]:
                continue
            idx_loc = df.index.get_indexer([target_date], method='nearest')[0]
            price_after_20d = df.iloc[idx_loc]['Nasdaq']
            
            drawdown = (price_after_20d - price_at_signal) / price_at_signal
            results.append({
                "信号日期": date.strftime('%Y-%m-%d'),
                "USD/JPY 10天跌幅": f"{df.loc[date]['JPY_Chg_10d']:.2%}",
                "Nasdaq 当前价格": f"{price_at_signal:.0f}",
                "20天后涨跌幅": drawdown
            })
        except:
            pass
            
    res_df = pd.DataFrame(results)
    
    col_a, col_b = st.columns([2, 1])
    
    with col_a:
        # 绘制信号点图
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
            # 格式化颜色
            def color_negative_red(val):
                color = 'red' if val < 0 else 'green'
                return f'color: {color}'
            
            st.dataframe(
                res_df.style.format({'20天后涨跌幅': '{:.2%}'})
                .applymap(lambda x: 'color: red' if isinstance(x, float) and x < 0 else 'color: green', subset=['20天后涨跌幅']),
                height=400
            )
        else:
            st.write("过去几年未触发极端流动性警报。")

with tab3:
    st.dataframe(df.tail(50))