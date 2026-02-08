# liquidity-monitor


---

# 🔬 宏观流动性与硬资产观测系统 (Macro Liquidity & Asset Stress Monitor)

这是一个基于 Python Streamlit 构建的实时金融观测工具，旨在通过数据可视化与量化回测，验证宏观流动性变动对美股（纳斯达克）的影响。

### 🌟 核心灵感与致谢
本项目核心观测逻辑深度启发自 **XinGPT** 在 X (Twitter) 上的深度宏观分析。

特别感谢 **XinGPT ([@xingpt](https://x.com/xingpt))** 提供的精辟见解。其关于**“美股崩盘真凶是流动性（如日元套利平仓）而非 AI 叙事”**以及**“资产缩水压力测试”**的论述，为本项目构建“流动性冲击回测”模型提供了坚实的理论基础。

---

## 🚀 功能特性

- **多因子动态对比**：实时对比纳斯达克（Nasdaq）与日元汇率（USD/JPY）、美联储净流动性（Net Liquidity）、美债（TLT）、黄金（Gold）及能源/金属硬资产的走势。
- **危机信号回测系统**：支持对多种宏观因子进行历史回测。例如，当日元 10 天内升值超过 3% 时，自动统计随后 20 个交易日纳斯达克的下跌概率与表现。
- **内置宏观百科**：在交互界面中深度集成各项指标的“通俗解释”与“宏观逻辑”，帮助用户在观测数据的同时理解背后的金融机理。
- **实时数据驱动**：自动接入 Yahoo Finance 市场数据与圣路易斯联储（FRED）宏观经济数据。

---

## 🛠️ 技术架构

- **前端/应用框架**：[Streamlit](https://streamlit.io/)
- **数据源**：`yfinance` (市场行情), `FRED API via CSV` (美联储资产负债表数据)
- **数据处理**：`Pandas`, `NumPy`
- **可视化**：`Plotly` (交互式动态图表)
- **部署**：支持一键部署至 Streamlit Cloud

---

## 📦 快速上手

### 1. 克隆仓库
```bash
git clone https://github.com/您的用户名/liquidity-monitor.git
cd liquidity-monitor
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 本地运行
```bash
streamlit run app.py
```

---

## 📊 核心观测指标说明

1. **USD/JPY (日元汇率)**：观察日元套利交易平仓（Carry Trade Unwind）引发的流动性抽离。
2. **Net Liquidity (净流动性)**：美联储资产负债表 - TGA账户 - 逆回购（RRP），衡量市场真实的资金存量。
3. **XLE/XME (能源与金属)**：在“美元跌+美债跌”的极端场景下，观察硬资产的避险对冲效应。
4. **TLT (长债价格)**：反映利率压力，观测是否存在“股债双杀”的系统性风险。

---

## ⚠️ 免责声明
本系统仅供量化研究与宏观观测使用，不构成任何投资建议。市场有风险，投资需谨慎。

---

### 💡 参与贡献
欢迎通过 Issue 或 Pull Request 提交更多宏观因子的回测逻辑或 UI 改进建议。再次感谢 **XinGPT** 对宏观研究社区的贡献。