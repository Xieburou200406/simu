# QS 知识体系知识点（zcf × zarb × 产品全景 × 排查工具链）

> **配套公式手册**：《QS公式手册.md》——全链路公式按定价链路编号 §1~§12（日历贴现→合成远期→Wing 曲线→定价希腊→GN 拟合→平滑→弹性调价→下单风控→五腿组合→PnL 归因→调参杠杆），每个公式含出处行号与记忆钩子。本笔记管"为什么"，手册管"怎么算"。

> **双轨出处**（每条结论可回查）：
> - **题库**：qsquiz「QS 知识」模块 124 题全量（2026-09-29 拉取），标 `qs-gt-NNNN`，原文见 quiz_qs_digest.txt；
> - **文档**：orange_zone 仓库（D:\实习\git\orange_zone），简称对照——**flow**=strategy/zarb-zcf-flow.md（引擎流程与算法，最核心）、**hedge**=strategy/delta-hedge.md、**volarb**=strategy/vol-arbitrage.md、**runbook**=execution/delta-loss-runbook.md、**pnl**=execution/check-risk-pnl-manual.md、**lat**=execution/arb-latency.md、**skill**=execution/qs-skills.md。
> 与《QS部署体系知识点.md》互补：那份讲**怎么部署**，这份讲**引擎怎么运转、钱怎么赚亏、出事怎么查**。

---

## 一、全景：QS 世界的地图

- **产品规模（2026-09 口径）**：47 注册 = 46 在役，dstl 二对一（dstl_yh_csi 对应 tl01/tl02 两份配置）。（qs-gt-0001/0025）
- **池分布**：etf 14 + qs_stk_g1 20 + csi 11 + com 1。（qs-gt-0004/0007）
  - ⚠️ 口径冲突：ops/server-products.md 写"35 份配置/33 个产品（ETF 25）"——与题库 2026-09 口径对不上（旧快照或统计范围不同）。引用数字先注明口径。
- **4 家合作公司**：大树 / 量魁 / 天行健 / 鑫鼎。（qs-gt-0016）
- **8 家券商编码**：gd=光大、gj=国泰君安、ht=海通、nh=南华、wk=五矿、yh=银河、zs=招商（gm 题库未单独考）。（qs-gt-0019/0093/0095/0097/0107/0109/0119/0121/0123）
- **6 类柜台接口**：yd / ctp / nhtd / femas / hts / rem_zsqh（盛立）。（qs-gt-0022；lat 工具正是按这六类分解析器）
- **产品名解码**：`<策略系列><编号>_<券商>_<池>`。hy05_gj_etf = hy 系列 05 号 × 国泰君安 × etf 池。题库 0092~0124 共 33 题全是这条规则的送分题。（qs-gt-0010/0093）
- **源码布局**（flow 头部）：
  - 引擎源码：`/opt/dev/z/zdorado/{zcf,zarb,zcalculus}`，分支 `csi300_prod_gx_n_spread_table`；
  - 定价实现：`/opt/dev/zdist/zvolador/XCalculus/XCalcOption.cpp`（**z 仓库只有头文件，实现在 zdist**）；
  - 文档对照：z 下 KB.md（zarb 侧准确）、zarb_analysis.md（**基于旧分支 ruizhi_3.0，Action 模板/XDataBridge 已不存在，与 flow 冲突处以 flow 为准**）、Delta_hedge.md（准确）；zcf 此前零文档，flow 补齐。

## 二、策略与双引擎骨架

### 2.1 引擎为什么存在：波动率套利三步走

- **核心思想**（volarb）：期权市价应服从一条平滑波动率曲线，个别合约会因流动性/大单冲击暂时偏离——**买便宜的、卖贵的、对冲掉方向性风险，赚价格回归的钱**。
- **三步**：① 拟合曲线得理论 IV → 理论价；② 偏离超阈值出信号（高估卖、低估买）；③ 构建希腊中性的对冲组合。
- **5 合约 3 约束 2 自由度**（volarb 全期权对冲）：5 个期权权重、3 个零约束（AccuDelta=AccuVega=AccuSml=0），剩余自由度用来捕捉偏离赚 Trade PnL——**合约数必须多于约束数**才有解空间。
- **ATM 合约的特殊价值**（volarb）：ATM 处 Sml=0，不受偏度变化影响，可以大量用来配 Vega 而不引入 Skew 敞口。
- **两条现实**（volarb 关键要点）：偏离必须大于买卖价差+手续费（成本决定阈值）；谁先算出来谁先下单（速度是关键）。
- **ArbTv 实时调价**（volarb）：系统按 AccuDelta/AccuVega/AccuSml 实时调整报价，使持仓始终趋向零敞口——这就是 zarb 弹性调价（§4.2）的策略语义。
- **KtC/KtP 为什么不进配平方程**（volarb:313-314 + flow:262/276/293）：KtC/KtP 是 Wing 峰度（曲率）的 Call/Put 两侧敏感度（VegaKurt），属二阶量——组合行权价集中中段（|z| 小），曲率只在两翼才显著；且每个约束吃掉一个自由度，5 腿解 5 方程则权重被定死、无 slack 优化成本。不进方程 ≠ 不管，是**三层风控**：① 建仓方程只归零 Δ/Vega/Sml；② 持仓后 5 维 Accu\*（含 AccuKtC/AccuKtP）全部进弹性调价，敞口越大报价越往回压（flow:276 pos 五维全进公式）；③ 5 维限额（IocMax\*/LimitMax\*）硬裁剪，任一维到 0 即停（delta-hedge 五维累计限制），且 MinPnl 内含 MinKtCGain/MinKtPGain 为曲率风险计价。
- **五腿的 PnL 角色**（volarb 收益来源+关键洞察）：alpha（偏离）集中在信号腿（卖 C_2550 / 买 C_2700）；对冲腿按理论价附近成交、收敛时 IV 变化小、通常净付成本（文档原话：C_2650 赔 1.31 是 Skew 中性的必要代价，被主收益腿完全覆盖）——利润是组合级兑现，记账主导项在信号腿。五腿是**一个篮子同时建仓**（跨月联合搜索 8 轮，任一腿不满足 MinIocPnl 整体降尺寸，§4.3），方向分布 3 买 2 卖，不是"1 买 1 卖 + 3 对冲"的先后两步。
- **偏离只能发生在不同行权价之间**：同一条到期曲线上每个 K 只有一个 IV（欧式同 K 的 call/put 共享 IV，C−P 平价保证），"同一合约一买一卖"在波动率维度上无从谈起；同一 K 的 call 贵 put 便宜是 C−P 平价套利（conversion/reversal，zcf implied_fwd 那套，§3.3），属另一类信号；不同到期日之间的偏离是期限结构（日历）信号，也不在本节场景内。

### 2.2 双引擎连接

- **分工**（qs-gt-0003/0006）：**zcf = 定价中枢**（拟合波动率曲线与远期，产出 cUsed\*/cImplied\*）、**zarb = 交易引擎**（消费曲线 + elasticity 调整 → 全月定价 TV/Greeks → 驱动 IOC/LMT/Quote 下单与风控）。
- **通信**（flow §1）：进程内是两条独立 so（都链 zbase/zcalculus）；部署上是两个进程，属性经 **XCeEvent pub/sub** 发布订阅（XAttribute.cpp:8-34），zarb 侧收进 **ParamSharedBuffer**（5000 槽；行情 MD 2000 槽）由算法线程消费。（qs-gt-0009/0059/0060）
- **zarb 内部合约层次**（zcf 侧同理分层，flow §2.1）：

```
CFStrategy（组合 ULP 加权）
  └─ CFUnderlying（标的行情、ULP 类型）
       └─ CFExpiry ★ 全部拟合算法在这一层（cfexpiry.cpp 1292 行）
            ├─ CFStrike
            │   ├─ CFOption（Call）
            │   └─ CFOption（Put）
            └─ CFFuture
```

- **c\* 属性消费表**（flow §4，精简）：cUsedBss→update_arb_fwd（基差→arb 远期）；cUsedVol/Skew/KtC/KtP→UsedCurveAttr（**Staled 即停交易**）；cUsedFwd 定价 / aUsedFwd zarb 自算（zarb 有自己的动态远期 §4.7）；cMark\*→calc_marked_tv 盯市；cSSR/cVCR/cSCR→曲线联动系数（定价/平滑双侧同用）；cPanic→曲线跳变联动；反向：aEnableIoc/aEnableLmt/aQuoteOn/aMarkOrderOn（zarb 状态）回给 zcf 做参数保护。

### 2.3 生命线

- **页面 Delta 是模型算的 Implied Delta**（来自 cUsed\* 曲线，不是交易所推送）——曲线跑偏 Delta 跟着跑偏，锚定检测要盯定价参数。（qs-gt-0008）
- **断流自保**：zcf 每次 processData 后把值标 Staled；zarb 侧 UsedCurveAttr::from_binary 发现 Staled 即 **auto_turn_off() 关交易**。（qs-gt-0012；flow §1）

## 三、zcf 深潜：波动率曲线是怎么炼成的

### 3.1 驱动与七步流水线

- **10ms QTimer** 驱动 + **cCurveFittingFreq 节流**（距上次触发不足该毫秒数直接返回）。（qs-gt-0015；flow §2.2）
- 七步固定顺序，代码函数名对应（flow §2.2）：

```
calc_df_and_mat      — 当日剩余时间 → TTE、贴现因子 DF
calc_implied_fwd     — C-P 平价反推瞬时合成远期 + 基差
update_smoothed_fwd  — driver(标的/期货) − basis → 平滑远期 → cUsedFwd
calc_implied_vol     — ★ 曲线拟合（Gauss-Newton）
smooth_vol_params    — EMA 平滑 + 跳变保护 + ATM
calc_mark_params     — Mark 参数（滑窗均值）
calc_tv              — 用 Used* 参数给全月期权定价并发布 Greeks
```

### 3.2 TTE / DF 的日历口径 ★（截图那题）

- **TTE 按工作日/252**（剔除周末+节假日）；**DF 按自然日/365**；日内都按 **pct_day = 已交易时长/当日交易时长** 插值：`tte=(full_days+pct_day)/252`，`dsf=exp(−rate·(dsc_days+pct_day)/365)`。（qs-gt-0055/0056；flow §2.3）
- **为什么两把尺子**：波动率是"有效交易时间"的年化（周末时间价值不磨损）→ 工作日/252；贴现是"资金占用时间"的计息（利息按日历日滚）→ 自然日/365。混为一谈的选项全错。
- **SOD/EOD 锚点**（flow §2.3，theta 用）：`tte_sod=(full+1)/252`、`tte_eod=full/252`；`dsf_sod/eod=exp(−rate·(days±1)/365)`。启动时由 CurveFittingCE 读 Holidays 配置预计算 `_tte_full_days/_dsc_full_days`。
- **DFOnTradeDay=1** 可把 DF 也切到 252 交易日口径（开关存在，默认自然日/365）。（flow §2.3）

### 3.3 合成远期（implied_fwd → smoothed_fwd）

- **理论根基 C−P 平价**：`stk_fwd = (C−P)/df + K`。（qs-gt-0021）
- **逐 strike 平价区间**（flow §2.4）：要求 ask 量>0 且不交叉，`stk_fwd_bid=(C_bid−P_ask)/df+K`、`stk_fwd_ask=(C_ask−P_bid)/df+K`；过滤 K∈[cMinStkForImF, cMaxStkForImF] 且区间两端都在 [cMinImpliedFwd, cMaxImpliedFwd] 内，通过者写期权上的 cBidImF/cAskImF。
- **区间中点投票**：全部 (bid,ask) 端点排序成 2N 个点，扫相邻点对中点 mid，统计 in_middle_num / 下方数 / 上方数 / error=|driver_px−mid|。**两种模型**（qs-gt-0024）：
  - **MaxNumFit**：最大化 in_middle_num（最多 strike 区间包住解），平手取 error 小者；
  - **Balanced**：最小化 |below_bid_num − above_ask_num|（买卖侧均衡），平手取 error 小者。
  - 结果写 cImpliedFwd；最优买卖合成远期 best_fwd_bid/ask 写 expiry 级 cBidImF/cAskImF。
- **基差**（flow §2.4）：`equity: cImpliedBss = bary_px − cImpliedFwd·opt_dsf`；`future: = bary_px − cImpliedFwd`。另有 cBidFwdEdge = strike 合成 bid − cImpliedFwd（每期权一份，供套利侧判边际）。

### 3.4 Wing 波动率曲线

- **公式**：`σ = vol + sml·z + 0.5·k·z²`，`z = ln(atm/strike)/√tte`（atm 来自 cAtm）。（qs-gt-0033~0036；flow §2.9）
- **两翼分侧**（flow §2.9，以代码为准）：z<0（低行权价侧）二次项取 **KtC**、夹 [min_vol, vol·max_put_mult]；z≥0 取 **KtP**、夹 [min_vol, vol·max_cal_mult]。⚠️ 代码里 zz<0 走的是 max_cal_vol_mult 分支——配置 cMaxVolMultForCall/Put 时以代码实际为准。
- 备选 calc_volatility_1（带 dc/dsm/uc/usm 翼部平滑裁剪）**未启用**；calc_volatility_2（符号翻转版）用于交叉验证。（flow §2.9）
- **OneKurt（1Krt）模式**：KtP≡KtC 合一、参数退化为 3 个——页面上 1Krt 下 KtP 列默认隐藏；切 2Krt 后两翼独立。（qs-gt-0023/0029）

### 3.5 拟合算法

- **Gauss-Newton 加权最小二乘，固定 5 轮**（qs-gt-0027/0028；flow §2.5）：
  - 状态向量 θ=(vol, sml, ktc, ktp)；**初值取上一周期 cImplied\***（无则 cInitImplied\*），每轮先夹 [min,max]；
  - 窗口内每期权：mp = 量加权中间价（SizedWeightedPx），px_dif = mp − |tv|，梯度 g = (vega, vega_skew, vega_kurt_c, vega_kurt_p)（数值差分，§3.8）；
  - 正规方程：`A += mult²·g·gᵀ`（4×4 对称阵），`RHS += mult·g·px_dif`；Δθ = A⁻¹·rhs；
  - OneKurt 模式合并成 3×3；**矩阵求逆失败 → resetImpliedParam() 全 NaN 退出**（宁缺毋错）；
  - 5 轮后夹范围写 cImpliedVol/Skew/KtC/KtP。
- **拟合窗口筛选**：先找 ATM strike（最后一个 price ≤ UsedFwd 的 strike），窗口 `[atm−PutNumForImply, atm+CalNumForImply−1]`，再用 |delta|∈[cMinDeltaForImply, cMaxDeltaForImply] 过滤，合格者 AISAttr=1。（qs-gt-0031/0032；flow §2.5）
- **跳变留证**：save_curve_fitting_data 若参数跳变超阈值（**vol>0.01 / 其他>0.05**）打 "Curve fitting jumps" 日志并**留存当时参与拟合的期权盘口快照**——为事后复盘留现场。（flow §2.5）
- **单点 IV**：**二分法最多 30 次、价差 <1e-6 收敛**——不是牛顿迭代（二分慢但稳，不怕导数爆掉）。（qs-gt-0039/0040）

### 3.6 平滑与参数保护

- **EMA**：`α = 0.01^(freq_ms·0.001/period_s)`——period 秒后旧值权重衰减到 1%。（qs-gt-0041/0042；flow §2.6）
- **朴素版 vs 去趋势版**（flow §2.6）：Fwd/Bss/KtC/KtP 用朴素 `s = s·α + i·(1−α)`；**Vol/Sml 用去趋势版**——先剔除远期变动能解释的部分 `adj = SSR·VCR·(fwd−ref)/ref`，对 (i−adj) 做 EMA（状态存 SsrVol/SsrSml）再加回 adj。语义：隐含 vol/sml 一部分变动只是贴着 fwd 走，不该进曲线。（qs-gt-0043/0044）
- **ATM 前瞻**：`atm = SSR·smoothed_fwd + (1−SSR)·ref`；Manual 模式直接用 UsedFwd。ATM 是 Wing 曲线的中心。（flow §2.6）
- **跳变保护**：非 Manual 模式下 `|smoothed−implied| ≥ c*Jump` 或 implied 为 NaN → 该参数**切 Manual + 告警**；任一跳变 → **cPanic=1**。（qs-gt-0045/0046）
- **cUsed\* 来源三态**（flow §2.6 set_vol_used_params）：cCFMode=Manual → 直接 cMan\*；Sabr_Px → clamp(smoothed+offset)；**cAutoMan=1 时同步回写 cMan\***（断流兜底，重启后不至于无参可用）。cBssMode 同理 Smooth/Manual。
- **交易开着不许改曲线**：aEnableIoc/aEnableLmt/aMarkOrderOn/aQuoteOn **任一开着**，改曲线模式/关键参数一律拒改并回滚。（qs-gt-0081/0082）
- **参数保护回调族**（flow §2.10）：CFFreqAttr/\*SmoothPeriodAttr（改频率/周期自动重算全部平滑 α）；CFResetAttr（清平滑状态：smoothed←implied、SsrVol/SsrSml 重置）；cVolPreview/cPrevApply（GUI 预览参数夹 min/max，确认后一键写入 cMan\*）；CFVolCutAttr（由 cMinImpliedVol/cMaxVolMult\*/cVolDc 等重建 VolCurveCut）。

### 3.7 Mark（盯市）

- `cMark* = cImplied* 的滑窗均值`（窗长 cMarkPts，**下限 100**），另有 `cMarkFwd = (bary·drv_dsf − MarkBss)/opt_dsf`；cMarkOn=0 或 implied 无效时退回手动 Mark 参数。供 zarb 的 calc_marked_tv 做估值/PnL——避免用瞬时参数估值造成 PnL 抖动。（qs-gt-0047/0048；flow §2.7）

### 3.8 TV 与 Greeks 发布

- **发布范围：全月全部期权**——拟合窗口只影响反推参数，定价发布不受限。（qs-gt-0049/0050）
- **定价模型**：欧式/call 用 **BS**，美式 put 用 **Bjerksund**；tte≤0 直接返回内在价值。（qs-gt-0037/0038）
- **Greeks 全族数值差分**（±0.01 扰动，flow §2.9）：vega/vega_skew/vega_kurt_c/vega_kurt_p 各 ±0.01 参数差分；**kurt vega 只在对应翼侧非零**（zz>0 只算 ktp）。
- **欧式 fwd 曲线联动（sticky-delta 类）**：扰动 fwd 时整条曲线联动 `vol_u/d = vol ± SSR·VCR·fmp`、`sml_u/d = sml ± SSR·SCR·fmp`——把 spot-vol 相关性编进 delta；**美式 put 退化为朴素差分**。（qs-gt-0086/0088）
- **theta = TV(tte_eod) − TV(tte_sod)**（SOD/EOD 锚点差分，非解析导数）。（qs-gt-0051/0052）

### 3.9 Delta 形状约束

- 沿 strike 递增强制 **call delta 递减且 ≥0**；**put delta = call delta − 1**（put-call 平价永远严格成立，不分开算——分开算反而被毛刺弄得对不上）。（qs-gt-0011/0014/0053/0054）
- 为什么要封顶：手工调参毛刺 → 裸求导放大成"高行权价 call delta 更大"的非法形状。zarb 侧 TvGen（arb_expiry_tvgen.cpp:80-95）同样逻辑，两端一致。（flow §2.8）

### 3.10 ULP 组合加权与遗留缺陷

- **ULP（标的/期货加权价）**：aUlpType 三选——Simple（量加权中间价→单边→最新价，乘 dsf）/ Trades / Manual；calc_comb_ulp 按 **cUlRatio** 加权 → cUlPrice（zcf 定价的"标的价"用组合价，不是单一合约）。（flow §2.10）
- ⚠️ **已知缺陷 M20**：期货腿 dsf 被二次应用。（flow §2.10）
- **trading_session 模块未启用**：cfexpiry 实际用 ExchangePolicy 的 pct_day 口径；trading_session 有已知 bug（C2 循环条件错 / C3 _accu 从未累加 / H9 迭代器失效），**启用前必须修**。（flow §2.11）

### 3.11 日切：EOD 对曲线做了什么

- **aAffirm（EOD）**：Used\* 存档为 **Used\*Eod**，**全部 expiry 切 Manual**——次日从手动值起步，人确认前不用昨天的旧曲线自动交易。与部署体系 auto_sod_eod=0 人工开日同一哲学。（qs-gt-0079/0080；flow §2.10）

## 四、zarb 深潜：订单是怎么下出去的

### 4.1 线程模型与主循环

- **三条执行流**：行情线程 RzArbMdConn → MDSharedBuffer(2000)；参数（XCeEvent 订阅）→ ParamSharedBuffer(5000)；算法线程 ArbAlgoCore 主循环；**定价线程 TvGen** 双向属性拷贝（Origin→TvGenInp→计算→TvGenOut→Origin，QMutex 互斥）与主循环异步换数。（qs-gt-0057/0058；flow §3.1）
- **arbitrage() 每周期动作**（flow §3.2）：与 TvGen 换数 → 逐 ul 风控 → 逐 expiry：动态远期校准 → 撤超时 IOC → 逐期权 strike_shift/theo_shift/min_pnl/max_ioc_size → auto_turn_off → **calc_accu_greeks（产出 aAccu\*）** → **期货 auto_hedge** → smooth_mid_tv_dif（50ms EMA）→ IOC 篮子搜索 → 到点挂 Stack LMT + Quote。

### 4.2 弹性调价与软性 Delta 对冲 ★

- **机制本质**（hedge §1——这是理解 zarb 的钥匙）：Delta 敞口**不靠直接下对冲单**，而是通过**定价反馈**软性对冲：

```
期权持仓 Δ → 到期月 AccuDelta
  → Fwd 弹性调整：Long Δ → Fwd 被调低 → TV 下降 → 卖 Delta 腿（卖 Call/买 Put）有利可图
  → IOC/Stack 自然倾向卖出敞口方向的腿 → 敞口被"价格引力"平掉
```

- **通用弹性公式**（qs-gt-0067/0068；flow §3.3）：`adjusted = targ·alph + (1−alph)·smth + clamp((offs−pos)·elas/unit, ±rstc)`——**敞口越大，定价越往促使平敞口的方向压**（多 Vega → vol 调高 → 卖波更有吸引力）。
- **Fwd 维度特例**（hedge §3.1）：`final_fwd = used_fwd + (exp_fwd_offs − exp_accu_delta)·elastic/exp_fwd_unit`，裁剪 ±FwdRstc。**Long Delta 且 offs≈0 → final_fwd < used_fwd，方向必与 AccuDelta 相反**（排查信号，§4.9）。
- **Strike 级远期位移**（flow §3.3）：`strike_fwd = fwd − 该strike期权持仓Δ·fwd_elastic/strike_delta_unit`，逐 strike 重定价 → aArbAdjTv；再叠加仓位 strike-shift → **aArbSSTv**（Market 报价引用的 TV）。
- **Vol/Sml 远期联动**：`vol += SSR·VCR·(pricing_fwd−used_fwd)/ref`——与 zcf 平滑去趋势同一套 SSR/VCR/SCR 语义，双侧一致。（flow §3.3）
- **期货 auto_hedge 与期权对期权并存**：hedge.md 写明对冲方式是"期权对期权（不做期货自动对冲）"；flow 的主循环里 driver 为期货的池有 auto_hedge。两通道细节以源码为准——etf 池（ETF 现货 driver）走期权对期权软对冲是主干。（hedge 头部；flow §3.2）

### 4.3 IOC 篮子

- **入选与尺寸**（flow §3.4）：`fee = 交易所费率（按打向侧盘口价）`；`pnl_buf = (tv − mkt_ask − MinIocBidPnl − fee)`（卖侧对称：买一价 − tv − MinIocAskPnl − fee）；`size = pnl_buf·aggressivity/theo_shift`——**毛利越大下越多；theo_shift（自冲击成本）越贵下越少**。（qs-gt-0061/0062）
- **跨月联合搜索 8 轮上限**（qs-gt-0063/0064；flow §3.4）：各 expiry 组篮子算合计 Greeks → 用"篮子成交后的敞口"**重算弹性调价**得每腿调整后 TV → 任一腿 `(adj_tv − ioc_px) < MinIocPnl` → **整体降尺寸重来**；全部通过存 valid_basket，还能加就继续。
- **收尾过闸**：valid_basket 按 pnl 降序，过 `aFreezeOrder=0 ∧ aEnableIoc=1 ∧ 未 PendingRiskBreached` + IOC 节流，逐腿 send_optimized_order。（flow §3.4）

### 4.4 theo_shift（自我冲击成本）

- 完整公式（flow §3.5；hedge §4.2）：吃进自身单腿后，各维度弹性回推的价格总位移——strike_shift + Delta 维（δ²·fwd_el/drv_mult×三个 unit 倒数和）+ 四个波动率维度（vega²·vol_el·100/vol_unit + skew²… + ktc²… + ktp²…）/fx。
- **Unit 全在分母**：放大 aVolUnit/aSmlUnit → theo_shift 变小 → 同等毛利下单量更大、更容易平 Delta——**调参杠杆**。（hedge §4.2）

### 4.5 MinPnl 组成与卖出腿条件链

- **min_pnl 分解**（hedge §4.1）：`MinFwdGain + MinVolGain + MinSmlGain + MinKtCGain + MinKtPGain + spd_min_gain + FixedGain`；`min_ioc_pnl = min_pnl × IocPnlMult`（PnlMult 是乘在整体上的总系数）；ITM 再 × ItmPnlMult；有合成仓位时卖 Call 的 ask_pnl 再上调。
- **卖出腿 10 道闸**（hedge §4，速览）：strike 仓位上限 → Arb 仓位上限（delta 越虚允许仓位越大，PosOnDeltaRatio）→ 深 ITM/|delta| 越界只准平仓 → 市场深度 → 单量上下限 → OrderAction（先平后开，AllowSellOpen/Close）→ 五维累计限制 → MinPnl 门槛 → 撤单限流（MaxCxlCnt）→ 跨到期月篮子复核。
- **调参建议**（hedge §4.1）：平 Delta 门槛太高时，**优先调 IocPnlMult / LmtOpenPnlMult / LmtClsePnlMult**（总系数），比逐个调各 gain 源更直接。

### 4.6 Quote 报价

- **QuoteMode 四选**：Tv / Market / Both / Neither。（qs-gt-0069/0070）
- **TV 模式**（flow §3.6）：按**报出尺寸后的敞口**重定价（报价前先想清楚成交后自己变成什么仓位）→ `max_bid = bid_tv − MinLmtBidPnl`、`min_ask = ask_tv + MinLmtAskPnl` → spread_table 宽度校验 → 不交叉 → |AccuDelta| ≤ QuoteDeltaLimit；已发报价满足 keep_edge（KeepEdgeRatio·edge）**复用不重发**；100ms 复查已发报价。
- **Market 模式**（qs-gt-0071/0072；flow §3.6）：`ss = clamp(StrikePos/SSUnit·SSElastic, ±|SSOnSpread|)·(ask−bid)` 再夹 ±|SSOnTv·tv|；`mid_theo = ArbSSTv + MidTvDif(50ms EMA) − ss`；`maxbid = max(0, min(mkt_bid−ss, tv−MinQuotePnl, mid_theo−bid_edge))`（minask 对称）；六个清空条件（盘口单边 0/交叉/宽度败/逾 tv±min_quote_pnl/逾 mid_theo±edge/触及对手价）任一即 0/0。
- **时序闸门全家桶**（flow §3.6）：QuoteHaltTime（成交后冷却）、QuoteOnNewTick、5 秒更新抑制窗、MaxQuoteRate 节流、MinMarketQtyForQuote（盘口对手量门槛 + MinMarketQtyNotUseInTime 时段豁免）、MaxPosForQuote/MaxStkPosForQuote 仓位闸。

### 4.7 Stack LMT 梯级单、动态远期与合成限次

- **Ladder 7 状态机**（flow §3.7）：NO_NEW_ORDER / IMP_MKTS_OURS_NOT_ON_BBO / IMP_OURS_ON_BBO / SEND_OURS_TO_IMP_MKTS_BBO / IMP_JOIN_BAND_ORDER / SEND_OURS_IN_JOIN_BAND 等——本质是"**何时允许改进 BBO、何时只 join 排队**"；全局按优先级排序，受 **MaxCxlRate（撤单率不等式）+ OrderThrottle 双重限频**。（qs-gt-0083/0084）
- **动态远期校准 calc_dynamic_fwd**（qs-gt-0073/0074；flow §3.7）：找全月最优合成远期买卖（`conv_bid = C_bid − P_ask + dsf·K`），与标的价做基差差分，**连续同向时把定价远期 aUsedFwd 夹在 [spot−smoothed_bss, converse_mid] 内**——合成市场与标的背离时，让定价远期贴向可成交的合成侧。
- **合成交易限次**：SyntCount/SyntLimit；box 走 ArbFlag::BoxOrder，限次防过度占用。（qs-gt-0090/0091）

### 4.8 下单链路与风控闸汇总

- **链路**（qs-gt-0077/0078；flow §3.9）：`ArbOption/ArbFuture → ArbAgent → ArbOrderMgr::send_order_if_ready/place_quote（IOC/Stack×2/Quote/Manual 四类，含 valid_order_price bias 校验）→ RzOmsExchConnector（OrderBase↔RzOrder 适配、撤单缓存重试）→ RzOms → CTP`。
- **闸门汇总**（flow §3.8）：

| 闸门 | 语义 |
|------|------|
| PendingRisk | LostCxlTime 超时未确认撤单计 lost，超阈 → PendingRiskBreached，quote/IOC 全停（qs-gt-0075/0076） |
| 曲线断供 | cUsed\* Staled → auto_turn_off |
| bias 价格偏离 | TV/last/mid/涨跌停 4 类偏差校验 |
| 5 维 Greeks 限额 | Δ/Vega/Skew/KtC/KtP，篮子与挂单双重裁剪（qs-gt-0065/0066） |
| 仓位 | MaxArbPos / MaxStrikePos / MaxPosForQuote |
| 止损分层 | rPanic→panic() 清单、StopAndCancel、TradeHalt、cPanic（曲线跳变） |

### 4.9 对冲不掉的排查（hedge §5）

- **三步**：① 查信号方向——**long delta 时 aFwdAdjust 必须低于 aUsedFwd**（方向与 AccuDelta 相反）；不反 → 查 aFwdElastic/aFwdUnit/aFwdRestrict。② 查挂单方向——OBP/OAP 应偏向卖 Delta 侧。③ 迟迟不对冲 → 四根因：
  - ① MaxArbPos/MaxStrikePos 打满 → 调大仓位上限；
  - ② 平 Delta 门槛太高 → 调小 IocPnlMult（IOC）/ LmtOpen/ClsePnlMult（Stack）；
  - ③ FwdUnit 不够小 → 调小 aFwdUnit（unit 越小 shift 越大）；
  - ④ theo_shift 太大 → 放大 aVolUnit/aSmlUnit 等（分母，unit 越大 shift 越小）。

## 五、希腊值与账目：风险怎么看

- **aAccuDelta**（qs-gt-0002；hedge §2.2）：该到期月期权仓位折成标的数量（正=看涨）。逐 strike：`Σ(Delta×持仓×期权乘数) ÷ 标的乘数`；另有**基础仓位**（合成期货/现货）计入，现货 ÷ 贴现系数；最终统一折成 **driver 合约张数**——期权 Delta 才能直接相加。
- **÷标的乘数 = 单位统一**（qs-gt-0005）：股指/商品除对冲期货乘数 → 单位=**期货张数**（正好是对冲要下的手数）；ETF 除 1 → 单位=**现货份数**。多数期货期权品种期权乘数恰好=期货乘数，公式看似 ×乘数÷乘数 抵消——除法的意义在统一口径（份数 ÷（份/张）=张数），乘数规格不等或 ETF 对现货（÷1）时才显出必要。
- **aAccuVega**（qs-gt-0017）：波动率每动一个点持仓值多少钱（元/波动点；正=多波）。`Σ(Vega×持仓×合约乘数)÷汇率`——**标的对波动率不敏感，无需折算对冲单位；除汇率只为统一本币口径。Delta 折对冲单位、Vega 折本币，两个口径别混**。（qs-gt-0020）
- **CshΔ**（qs-gt-0026）：`= Δ×标的乘数×标的价格` = 敞口名义本金（元），"元/1% 标的变动"口径。恒等式 `aAccuCashDelta ≈ aAccuDelta × cUsedFwd × 乘数`，实测 L1 验证误差 0.05%。（qs-gt-0085）
- **页面 Greeks 的风险五维**：Delta/Vega/Skew/KtC/KtP——没有 Gamma/Theta。因为 Wing 曲线下偏度和峰度才是独立风险源（Theta 用锚点差分单算，不进限额）。（qs-gt-0066）

### 引擎归因六项 r\*Pnl（pnl §4）

| 属性 | 刷速 | 语义 |
|------|------|------|
| rDeltaPnl / rVegaPnl / rVegaSkewPnl / rVegaKtcPnl / rBssPnl | ~6s | 各因子累计贡献，可被 rClear 清零 |
| rTradePnl | **成交才刷** | 一天可能只刷几次；"刷得少"≠"没赚" |
| aPnlChg | ~3s | 当日累计 PnL（结果，不是原因） |

- **两条铁律**（pnl §3）：① 所有值都是**累计快照**——窗口损益=末行−首行，**千万别把窗口内刷新值加总**；② 归因看 6 项 r\* 的**差分**。
- **日志粒度**（pnl §2）：归因看 `E|`（到期粒度）行，`U|` 是含对冲腿的聚合口径**不要用**；key = 账户|交易所|标的|到期月。

## 六、排查工具链与文档五册

### 6.1 文档五册与入口

- 模块描述列主题：希腊值 / 交易 / Delta 排查 / PnL 归因（qsquiz meta）；**第五册「PnL 归因」= web_console `/bridge/docs/pnl` 教学视图**（2026-09-07 上线，手工路线+案例精简版）。（check-risk-pnl.md）
- delta 损失排查手册：execution/delta-loss-runbook.md（qs-gt-0013）。

### 6.2 delta 亏损排查（runbook）

- **最致命的认知错误——conv ≠ cUsedFwd**（runbook 防坑 #1）：

| | conv / spot_tv | cUsedFwd |
|---|---|---|
| 频率 | 50ms 原始未滤波 | 3s 滤波 |
| 谁用 | **live 报价（中招点）** | 记账/对冲/PnL |
| 崩点表现 | 会崩 | 通常不崩 |

- **conv 公式**（C−P 平价的盘口实现）：`conv_bid_i = call_bid_i − put_ask_i + K_i·dsf`；`conv = mid( max_i(conv_bid_i), min_i(conv_ask_i) )`；`fwd = conv/dsf`。**极值会被单个 strike 拉偏**——这就是元凶入口。
- **排查十步**（速览）：锁轮廓（enable 时间/亏损额）→ 拆 PnL 证"是 delta"（delta PnL≈Σ aAccuDelta×ΔcUsedFwd 占大头）→ 定位爆发秒 → 关联下单（**I→T 2.5–4ms 秒成=主动吃单**；被动成交另案）→ 查 forward（**conv 崩而 cUsedFwd 不崩 = live 报价采信失真原始值**）→ 追盘口找元凶 → 证伪外部因素（现货/期货/dsf 三者都没动才算纯盘面错位）→ **数学闭合结案**（用元凶盘口按公式算回日志 conv 值，±1 tick 才算结案）→ 延迟核查 → 修复建议（极值剔除降权/带宽 sanity check/加滤波/深实值宽盘口不参与拟合）。
- **元凶特征**：深实/深虚、平时盘口宽不流动、爆发时价差异常收紧（案例 0.40→0.002）、last 陈旧（单笔挂单顶住，非真成交）。
- **实战案例**（2026-08-05 cx01_yh_etf 510500）：−4022 中 delta 占 −1685（42%）；09:31:09 20 笔成交 18 笔 I→T 2.5–4.2ms 主动吃单；元凶 10012277（C 6.25 深实值）ask 被低位卖单压住 500ms，conv 7.6138→7.4235，live 报价中招；现货 7.512 / IC2609 7560 / dsf 0.99885 全程没动；公式闭合 ✓。
- **操作铁律**：GB 级日志在交易服务器上——远端 grep 过滤 → 管道拉回本机 awk，不 scp 全文件；合约信息（行权价/C-P）从 dict 查不从 log 抠。

### 6.3 PnL 归因手工排查（pnl）

- **人工三招**：① 采样差分（窗口头尾两行相减）；② **敞口阶跃**（aAccuCashDelta 一行间大跳 = 有人平/加仓，交易动作铁证）；③ 停刷检测（引擎属性停刷而 aPnlChg 还刷 = 持仓没了；全停 = 数据断流）。
- **四步流程**：定窗口（aPnlChg 差分找亏损段）→ 六项归因（r\* 差分，|Δ| 最大的就是主因）→ 按因子追（cUsed\* 跳变时点 × aAccu\* 变化）→ 定性收尾（敞口没变参数动了 = 被动重定价挨打；敞口阶跃 = 主动交易）。
- **分因子速查**：delta→cUsedFwd×aAccuCashDelta（两侧验证：跌时该赚涨时该亏）；vega→cUsedVol 跳 ±0.01+；skew→大跌后虚值 put 需求；ktc→翼部曲率（onekurt 下 Ktp 恒 0）；bss→与 delta 合并看；trade→敞口阶跃时点。
- **坑**：rClear 清零点后的差分窗口丢弃；平仓后 aPnlChg/cUsed\* 仍刷到收盘——**先跑停刷检测，把窗口显式截到引擎属性最后一刷**（与 qs-gt-0089 实录呼应：误取 09:36 +37 点，正确 09:33:54 +48 点）。

### 6.4 延迟分析工具（lat）

- `analyze_one_log`：日期+产品+日志目录 → SSH 远端解析 → scp CSV 回本机 → 统计+入库 SQLite。按 db 的 api 字段自动选六柜台解析器。
- **CSV 事件编码**：I 报单发 / R 报单回报 / C 撤单发 / X 撤单确认 / T 成交回报；R 行 sysid=−1 是**柜台确认**、有值是**交易所确认**；gw_ack 只有 CTP 有。输出延迟分布 P50/P75/P95/P99 + 撤单成功率。

### 6.5 日志取数基本功（skill）

- **数字段法**：`grep 'xxx' log | tr ',' ' ' | tr '=' ' ' | awk '{print $N,…}'`——不写正则不逐字段 kv 解析。为什么：负号/连字符合约代码（MO2609-C-8100）不会被 split 吃掉，字段号纯数字不易错位。
- 附带：远端 grep 加 `-a`（非 UTF-8 字节会被当二进制抑制输出）；qsj_grep 的 pattern 不能含单引号。

## 七、复习自测

### 速记 20 条

1. 47 注册 = 46 在役，dstl 二对一；池：etf14 + g1 20 + csi 11 + com 1。
2. 4 公司（大树/量魁/天行健/鑫鼎）；8 券商 gd光大 gj国泰君安 ht海通 nh南华 wk五矿 yh银河 zs招商；柜台 6 类 yd/ctp/nhtd/femas/hts/rem_zsqh。
3. 产品名 = 系列+编号_券商_池，后缀即池。
4. 源码在 /opt/dev/z/zdorado（分支 csi300_prod_gx_n_spread_table），定价实现在 zdist 的 XCalcOption.cpp。
5. 策略本质：拟合曲线 → 找偏离 → 希腊中性组合赚回归；5 合约 3 约束 2 自由度。
6. zcf=定价中枢出 cUsed\*，zarb=交易引擎消费；XCeEvent pub/sub + ParamSharedBuffer（MD 2000/参数 5000 槽）。
7. 七步：TTE/DF → 隐含远期 → 平滑远期 → 隐含 vol → 平滑 → Mark → TV。
8. TTE 工作日/252 + pct_day 日内插值；DF 自然日/365；theta 锚点 tte_sod=(full+1)/252。
9. 远期投票：MaxNumFit 最多区间包住 / Balanced 买卖侧均衡，平手都取 error 小。
10. Wing：σ=vol+sml·z+½k·z²，z=ln(atm/strike)/√tte，两翼 KtC/KtP，1Krt 合一。
11. 拟合=GN 加权最小二乘 5 轮一次解 4 参数，vega 系梯度，求逆失败全 NaN 退出；单点 IV 二分 30 次。
12. EMA α=0.01^(freq_ms/1000/period_s)；Vol/Sml 先去远期趋势；跳变切 Manual+cPanic=1。
13. Mark=cImplied\* 滑窗均值≥100 点；发布全月全部期权。
14. put delta = call delta − 1 永远成立；call delta 沿 strike 强制递减 ≥0。
15. EOD：Used\*Eod 存档、全 expiry 切 Manual——次日人工起步。
16. **Delta 软对冲**：Long Δ → Fwd 调低 → TV 降 → 卖 Delta 腿有利可图；aFwdAdjust 方向必与 AccuDelta 相反。
17. IOC size = pnl_buf·aggressivity/theo_shift；篮子 8 轮、任一腿不满足 MinIocPnl 整体降尺寸。
18. theo_shift 的 Unit 全在分母——放大 Unit 平仓更容易。
19. 下单链 ArbOrderMgr → RzOmsExchConnector → RzOms → CTP；PendingRisk 超 lost 全停。
20. **conv（50ms live 报价）≠ cUsedFwd（3s 记账）**——排查 forward 崩必须分开看；结案必须数学闭合。

### 自测 16 问

1. TTE 和 DF 为什么用不同日历？（§3.2）
2. MaxNumFit 与 Balanced 的优化目标各是什么？（§3.3）
3. 写出 Wing 公式与 z 定义；两翼系数与夹值范围？（§3.4）
4. GN 每轮的正规方程长什么样？初值从哪来？求逆失败会怎样？（§3.5）
5. Vol/Sml 平滑前为什么去趋势？SSR/VCR 是什么角色？（§3.6）
6. cUsed\* 在 Manual / Sabr_Px / cAutoMan 三态下分别怎么取值？（§3.6）
7. theta 为什么用锚点差分而不是解析导数？（§3.8）
8. 为什么页面 Delta 跑偏要先怀疑曲线？（§2.3）
9. Long Delta 时 aFwdAdjust 与 aUsedFwd 的方向关系？不反查哪三个参数？（§4.2/4.9）
10. IOC 尺寸公式里 theo_shift 是什么？它变大会怎样？（§4.3）
11. 为什么 QS 风险五维没有 Gamma/Theta？（§4.3/五）
12. MinIocPnl 的组成源有哪些？调门槛为什么优先调 PnlMult？（§4.5）
13. Quote TV 模式与 Market 模式的本质区别？（§4.6）
14. PendingRiskBreached 的触发链与设计逻辑？（§4.8）
15. aAccuDelta 在股指池和 ETF 池的单位为什么不同？（五）
16. 某天亏损，conv 崩了而 cUsedFwd 没崩，说明什么？下一步查什么？（§6.2）

### 术语表

| 术语 | 含义 |
|------|------|
| zcf / zarb | Curve Fitting 定价中枢 / 套利交易引擎 |
| cUsed\* / cImplied\* / cMan\* | 生效参数 / 本周期隐含参数 / 手动参数 |
| cMark\* / Used\*Eod | 滑窗均值盯市参数 / EOD 存档 |
| TTE / DF / pct_day | 到期时间（工作日/252）/ 贴现因子（自然日/365）/ 日内已交易时长占比 |
| Wing / KtC / KtP / OneKurt | 曲线形态 σ=vol+sml·z+½k·z² / 两翼峰度 / 单峰度模式 |
| MaxNumFit / Balanced | 远期投票两模型 |
| converse_mid / cBidFwdEdge | 合成盘中间价 / strike 合成 bid 对远期的边际 |
| SSR / VCR / SCR | spot-vol 曲线联动系数族（平滑与定价双侧同用） |
| ULP / cUlRatio | 标的/期货组合加权价 / 权重比 |
| theo_shift | 吃进自身头寸后的价格总位移（自冲击成本） |
| MinIocPnl / pnl_buf / aggressivity | 篮子每腿最小毛利 / 毛利缓冲 / 进取度 |
| IocPnlMult / LmtOpen/ClsePnlMult | IOC/Stack 开平门槛总系数 |
| MaxArbPos / MaxStrikePos / QuoteDeltaLimit | 仓位/单 strike 仓位/报价 Delta 闸 |
| SyntCount / SyntLimit | 合成交易（box）限次 |
| MaxCxlRate / OrderThrottle | 撤单率 / 下单节流双重限频 |
| PendingRisk / lost | 超时未确认撤单计数；超阈全停 |
| Ladder 7 状态 | Stack LMT 的 BBO 改进/排队决策机 |
| Bjerksund | 美式 put 近似解析定价 |
| XCeEvent / ParamSharedBuffer | 进程间参数 pub/sub / zarb 参数共享缓冲（5000 槽） |
| aFwdAdjust / aArbAdjTv / aArbSSTv | 弹性调整后远期 / strike 重定价 TV / 仓位位移后 TV |
| conv | arb 侧 50ms 原始隐含远期（=dsf·fwd），live 报价用 |
| r\*Pnl 六项 | 引擎因子归因：Delta/Vega/VegaSkew/VegaKtc/Bss/Trade |
| aPnlChg / aAccuCashDelta | 当日累计 PnL / 含对冲腿现金 Delta 敞口 |

---

> 口径备注：数字与公式以题库解析 + orange_zone 文档为准（出处可回查）。冲突处已标注：产品总数 33(ops 文档) vs 46(题库 2026-09)；Wing 夹值分支 cal/put 命名以代码为准（flow §2.9）；期货 auto_hedge 与期权对期权对冲两通道以源码为准。
