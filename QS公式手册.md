# QS 公式手册（zcf × zarb 全链路，按定价链路编号）

> **使用说明**：公式按"时间 → 远期 → 曲线 → 价格 → 拟合 → 平滑 → 调价 → 下单 → 策略 → 账目"的数据流顺序编号（§1~§12），正好是 zcf 七步流水线 + zarb 三执行流的骨架。每个公式给三件套：**回答什么问题 → 公式 → 出处（文档:行号）**。符号全局统一见 §0。
> 出处简称：flow=zarb-zcf-flow.md，dh=delta-hedge.md，volarb=vol-arbitrage.md，pnl=check-risk-pnl-manual.md。

## 0. 符号总表

| 符号 | 含义 | 来源/单位 |
|------|------|----------|
| F / K | 远期价 / 行权价 | K 来自盘口，F 见 §2 |
| atm | Wing 曲线中心 | cAtm，见 §6（≈平滑远期） |
| tte | 剩余到期时间 | 年化，**工作日/252**（§1） |
| pct_day | 当日已过交易时长占比 | 0→1 日内插值用 |
| dsf / DF | 贴现因子 | **自然日/365**（§1） |
| vol, sml, ktc, ktp | Wing 四参数 | §3；OneKurt 时 ktp=ktc |
| z | 标准化对数行权价 | §3 |
| SSR, VCR, SCR | 曲线联动三系数 | vol/fwd、sml/fwd 联动强度 |
| mult | 拟合权重 | cCurveFittingMult |
| AccuΔ/Vega/Skw/KtC/KtP | 五维累计敞口 | zarb 逐周期重算 |
| offs, elas, unit, rstc | 弹性四件套 | Underlying 级参数 |
| driver | 到期月对冲基准合约 | 期货或现货 |

## 1. 日历与贴现——时间怎么算

**Q：剩余时间怎么年化？钱怎么折现？**

```
pct_day = 当日剩余交易时长 / 当日总交易时长          # 0→1，日内插值

tte = (full_days + pct_day) / 252                   # 工作日口径（剔除周末+节假日）
dsf = exp(−rate · (dsc_days + pct_day) / 365)       # 自然日口径
                                                    # DFOnTradeDay=1 时改按 252 交易日
```

theta 的两个锚点（SOD/EOD 各算一次 TV 再相减）：

```
tte_sod = (full_days + 1) / 252     # 开盘锚点：今天还剩一整个工作日
tte_eod =  full_days / 252          # 收盘锚点
dsf_sod = exp(−rate·(dsc_days+1)/365)     # 结构与 tte 平行：sod 多 1 天
dsf_eod = exp(−rate· dsc_days /365)       # eod 用原值，不再减 1
```

> **双口径铁律**：TTE 走工作日/252，DF 走自然日/365——qsquiz 截图题的考点，也是最容易混的地方。（flow:88-99，cfexpiry.cpp:408-475）
>
> **pct_day 的自洽性**：pct_day = 到收盘还剩的交易时长 ÷ 全天交易时长，开盘 ≈1、收盘 ≈0，日内从 1 滑到 0。代回公式：开盘 tte=(full+1)/252=tte_sod、收盘 tte=full/252=tte_eod——**日内插值就是在 sod/eod 两个锚点之间线性滑动**；dsf 的 (dsc_days+pct_day) 同理（开盘多贴 1 天）。252=一年交易日总数，365=一年自然日总数：分子是剩余天数、分母是全年天数，相除即年化比例。
>
> ⚠️ flow:91 原文写 `dsf_sod/eod=exp(−rate·(days±1)/365)`，"±1" 字面两边各动一格则 sod/eod 差两天，与 tte 锚点差一天不对称；上式按对称结构书写（eod 用原值不减 1），确切口径以源码 init_df_and_mat（cfexpiry.cpp:408-443）为准。

## 2. 合成远期与平价——远期从哪来

**Q：期权对里怎么挖出市场隐含的远期价？**

C−P 平价（一切的开始）：

```
C − P = dsf · (F − K)
```

逐 strike 折出远期的买卖区间：

```
stk_fwd_bid = (C_bid − P_ask)/dsf + K
stk_fwd_ask = (C_ask − P_bid)/dsf + K
```

区间中点投票（2N 个端点排序，扫相邻中点 mid，两个模型二选一 `cImpliedFwdModel`）：

```
MaxNumFit：最大化 in_middle_num（让最多 strike 区间包住 mid），平手取 error 小者
Balanced ：最小化 |below_bid_num − above_ask_num|，平手取 error 小者
error = |driver_px − mid|
```

基差（标的加权价 bary_px 对比合成远期）：

```
equity: cImpliedBss = bary_px − cImpliedFwd · opt_dsf
future: cImpliedBss = bary_px − cImpliedFwd          # 期货不乘贴现
```

zarb 侧动态校准的合成买卖价：

```
conv_bid = C_bid − P_ask + dsf·K                     # 与标的背离时把 aUsedFwd 夹向可成交合成侧
```

> 记忆钩子：**平价是透镜，远期是被期权对映出来的影子**；投票决定信谁的。（flow:103-129、flow:344）

## 3. Wing 曲线——四个参数怎么生成整条微笑

**Q：vol/sml/ktc/ktp 怎么变成每个 K 的 IV？**

```
z = ln(atm / K) / √tte

σ(K) = vol + sml·z + ½·kt·z²      # z<0 走 ktc、z≥0 走 ktp
       夹 [min_vol, vol·max_{cal|put}_mult]
```

> ⚠️ 两份文档对"z<0 是哪一侧"表述不一致（flow:197-201 vs volarb:292），分支命名以代码为准（flow:201 已自注更正）；公式结构不受影响。
>
> **ATM 免疫 Skew 的代数证明**：K=atm ⟹ z=0 ⟹ σ=vol，且 ∂σ/∂sml = z = 0——偏度怎么动 ATM 定价都不变，这就是五腿组合里 ATM 的 Sml 系数天生为零。

单点反推（隐含波动率）：30 次二分，价格差 < 1e-6 收敛。（flow:79-92）

## 4. 定价与希腊值——参数怎么变成价格和敏感度

**Q：TV 和六个希腊值怎么算出来？**

TV：tte>0 用 σ(K) 走 **BS**（欧式/call）；**美式 put 走 Bjerksund**；tte≤0 返回内在价值。（flow:204）BS 的数学骨架（Black-76 期货期权形式，供复习；实现细节以 zdist 为准）：

```
c = dsf·[F·N(d₁) − K·N(d₂)]        p = dsf·[K·N(−d₂) − F·N(−d₁)]
d₁ = [ln(F/K) + σ²·tte/2] / (σ·√tte)      d₂ = d₁ − σ·√tte
```

希腊值全部数值差分（±0.01 扰动）：

```
Delta    = [TV(F×1.01) − TV(F×0.99)] / (F × 0.02)
           # fwd 扰动时曲线联动（sticky-delta 编进 delta）：
           vol_u/d = vol ± SSR·VCR·fmp     sml_u/d = sml ± SSR·SCR·fmp
Vega     = [TV(vol+0.01) − TV(vol−0.01)] / 2
VegaSml  = [TV(sml+0.01) − TV(sml−0.01)] / 2      # 系统 AccuSml/Skew
VegaKtC/P= [TV(ktc/ktp+0.01) − TV(ktc/ktp−0.01)] / 2   # 只在对应翼侧非零
Gamma    = 数值差分（美式 put 对 calcTv 朴素差分）
theta    = TV(tte_eod) − TV(tte_sod)               # 用 §1 的两个锚点
```

> **theta 与剩余时间的反比直觉**：ATM 时间价值 ≈ 0.4·F·σ·√T（存量，越长越大），对 T 求导得 theta ∝ 1/(2√T)（流速，越短越快）——临到期 ATM 的 theta 发散。且 |theta| ≈ ½·σ²·F²·gamma/年化（gamma-theta 一体两面，数字验证：S=2600、σ=17.5%、剩 30 天 → gamma≈0.00254 → ½·0.175²·2600²·0.00254/252 ≈ 1.05 点/天），这就是五维限额不单列 theta 的原因：管住 gamma 即管住 theta。

两个形状恒等式（发布前强制）：

```
put delta = call delta − 1                        # 平价推论，恒成立
call delta 沿 strike 递增强制递减且 ≥0
```

> 记忆钩子：**六个希腊值 = 六次"动一下、看价格变多少"**；delta 的特别之处是动 F 时整条曲线跟着动。（flow:204-212、volarb:307-314）

## 5. Gauss-Newton 拟合——参数怎么从盘口反推

**Q：四个参数是怎么"解"出来的？**

目标：加权最小二乘，让理论价贴回市价。

```
参与期权：窗口 [atm_idx − PutNumForImply, atm_idx + CalNumForImply − 1]
          ∩ |delta| ∈ [cMinDeltaForImply, cMaxDeltaForImply]

每个期权：
  mp     = SizedWeightedPx(bid_sz, bid_px, ask_px, ask_sz)   # 量加权中间价
  px_dif = mp − |tv(θ)|                                      # θ=(vol,sml,ktc,ktp)
  g      = (vega, vega_skew, vega_kurt_c, vega_kurt_p)       # §4 的数值差分

正规方程累加（4×4 对称；OneKurt 时 3×3）：
  A   += mult² · g·gᵀ
  rhs += mult · g · px_dif

每轮：Δθ = A⁻¹ · rhs；  θ += Δθ；  夹到 [min,max]
固定 5 轮，初值 = 上一周期 cImplied*；求逆失败 → 全 NaN 退出
```

跳变留痕：5 轮结束后参数跳变超阈（vol>0.01 / 其他>0.05）打 "Curve fitting jumps" 并留存盘口快照。

> 记忆钩子：**不是逐参数打靶，是拿 vega 系敏感度当梯度、一口气解 4 维牛顿步**。（flow:133-165，cfexpiry.cpp:651-875）

## 6. 平滑与参数保护——拟合结果怎么变得可信

**Q：为什么不能直接用拟合输出？**

```
EMA 衰减系数：alpha = 0.01^( freq_ms · 0.001 / period_s )
             # period 秒后旧值权重衰减到 1%

朴素版（Fwd/Bss/KtC/KtP）： s = s·α + i·(1−α)

去趋势版（Vol/Sml）：      adj = SSR · VCR · (fwd − ref) / ref
                           对 (i − adj) 做 EMA，再加回 adj
             # "隐含 vol 的一部分变动只是贴着 fwd 走，不该进曲线"

ATM 前瞻：atm = SSR·smoothed_fwd + (1−SSR)·ref      # Manual 模式直接用 UsedFwd

跳变保护：|smoothed − implied| ≥ c*Jump（或 implied NaN）
          → 该参数切 Manual + 告警；任一跳变 → cPanic = 1
```

> 记忆钩子：**Vol/Sml 的 EMA 是"扣掉远期解释的部分再平均"**——和 §8 定价侧的远期联动是同一套 SSR/VCR 语义，一进一出。（flow:167-176，cfexpiry.h:314-360）

## 7. Mark 盯市

```
cMark* = 滑窗（cMarkPts，下限 100）滚动均值 of cImplied{Bss,Vol,Sml,KtC,KtP}
cMarkFwd = (bary·drv_dsf − MarkBss) / opt_dsf
```

> 用途：zarb 的 calc_marked_tv（估值/PnL），平滑于 cImplied\*、滞后于它。（flow:178-180）

## 8. zarb 弹性调价——敞口怎么反过来变成价格 ★

**Q：持仓敞口怎么影响报价，让系统"自己把自己对冲掉"？**

总公式（Underlying 级，每个维度一套参数；**pos 五维全进**：AccuDelta/Vega/Skew/KtC/KtP）：

```
adjusted = targ·alph + (1−alph)·smth + clamp( (offs − pos)·elas/unit, ±rstc )
           └── 平滑底盘 ──┘   └──── 敞口驱动力（软对冲）────┘
# 敞口越大，定价越往"促使平敞口"的方向压：做多 Vega → vol 调高 → 卖 Vega 有利
```

Delta 专用的 Fwd 通道（软对冲核心，ArbExpiry::calc_adjust_forward_tpl）：

```
final_fwd = used_fwd + (exp_fwd_offs − exp_accu_delta) · elastic / exp_fwd_unit
            夹 [used_fwd − FwdRstc, used_fwd + FwdRstc]

# Long Δ 且 offs≈0 → 右项为负 → final_fwd < used_fwd
# Long Δ → Fwd↓ → TV↓ → 卖 Delta 腿（卖 Call/买 Put）有利可图
# aFwdAdjust 方向必与 AccuDelta 相反 —— 排查第一判据
```

AccuDelta 的计量（统一折算成 driver 张数才能相加）：

```
tot_delta = 基础仓位（现货先 /dsf）+ Σ(每 strike 持仓 × ImpliedDelta)，最后 / drv_mult
```

Vol/Sml 的远期联动（定价侧）：

```
vol += SSR·VCR·(pricing_fwd − used_fwd) / ref
```

Strike 级远期位移（逐 strike 重定价）：

```
strike_fwd = fwd − (该 strike 期权持仓 Δ)·fwd_elastic / strike_delta_unit
# → aArbAdjTv，再叠加仓位 strike-shift → aArbSSTv（Market 模式引用）
```

> 记忆钩子：**弹性公式的第三项就是 §2.1 那句"始终趋向零敞口"的化身**；前两项是化妆（平滑），第三项是行动。（flow:270-279，dh:43-99）

## 9. 下单尺寸与风控公式——下多少、允不允许

**Q：每一单的量怎么定、被什么裁剪？**

利润缓冲与尺寸（买侧；卖侧对称）：

```
pnl_buf = tv − mkt_ask − MinIocBidPnl − fee          # 卖侧: mkt_bid − tv − MinIocAskPnl − fee
size    = pnl_buf · aggressivity / theo_shift        # 毛利越大下越多，自冲击越贵下越少
```

theo_shift（吃进自身单腿后各维度弹性回推的价格总位移）：

```
ts = strike_shift
   + mult·(δ²·fwd_el/drv_mult)·(1/fwd_unit + 1/drv_fwd_unit + 1/strike_delta_unit)
   + mult·( vega²·vol_el·100/vol_unit + skew²·sml_el·100/sml_unit
          + ktc²·ktc_el·100/ktc_unit + ktp²·ktp_el·100/ktp_unit ) / fx
# Unit 全在分母：放大 aVolUnit 等 → ts 变小 → 同等利润下单量更大
```

五维限额（篮子与挂单双重裁剪）：

```
(累计敞口 − Offs偏置) + 本单风险 ≤ IocMax*      # Δ/Vega/Skew/KtC/KtP 各自一条
逐维裁剪，任一维裁到 0 → 本单归零
```

MinPnl 门槛（**调参先动总系数**）：

```
min_pnl = MinFwdGain + MinVolGain + MinSmlGain + MinKtCGain + MinKtPGain
        + spd_min_gain + FixedGain
spd_min_gain = (spot_spread − DrvAvgSpd) × delta × SpdGainMult
min_ioc_pnl  = min_pnl × IocPnlMult              # ITM 再 × ItmPnlMult；合成仓位 × synth_pnl_mult
```

Market 模式报价（ss = 仓位自保护位移）：

```
ss       = clamp(StrikePos/SSUnit·SSElastic, ±|SSOnSpread|)·(ask−bid)，再夹 ±|SSOnTv·tv|
mid_theo = ArbSSTv + MidTvDif(50ms EMA) − ss
max_bid  = max(0, min(mkt_bid − ss, tv − MinQuotePnl, mid_theo − bid_edge))
min_ask  = max(0, max(mkt_ask − ss, tv + MinQuotePnl, mid_theo + ask_edge))
# 任一清空条件：盘口单边 0 / 交叉 / 宽度校验败 / 逾 tv±min_quote_pnl / 逾 mid_theo±edge / 触对手价
```

TV 模式报价：

```
bid_tv/ask_tv = calc_quote_side_tv(±size) + clamp(QuoteTvOffset, ±MaxQuoteTvOffset)
max_bid = bid_tv − MinLmtBidPnl        min_ask = ask_tv + MinLmtAskPnl
```

> 记忆钩子：**size 分子是利润、分母是自己的冲击**；限额管"能不能"、MinPnl 管"值不值"、theo_shift 管"划不划算"。（flow:285-336，dh:126-179）

## 10. 波动率套利组合——策略层公式 ★

**Q：五腿的权重怎么解出来？**

零约束方程组（5 未知 3 方程，欠定）：

```
Σᵢ wᵢ·Δᵢ = 0        Σᵢ wᵢ·Vᵢ = 0        Σᵢ wᵢ·Sᵢ = 0      (i=1..5)
```

锁死两张信号腿（高估卖 1 张、低估买 1 张）→ 剩 3 未知 3 方程，满秩唯一解。数值案例（F=2600，T=30 天，vol=17.5%，sml=−2%，ktc=ktp=0.5%）：

```
希腊表：
合约      z       σ_theo   σ_mkt    偏离      Δ      Vega   VegaSml  VegaKurt
C_2500  +0.137   17.23%   16.93%   −0.30%   0.792   2.12   0.290    0.020
C_2550  +0.068   17.37%   19.50%   +2.13%   0.659   2.72   0.184    0.006   ← 贵
C_2600   0.000   17.50%   17.50%    0.00%   0.509   2.97   0.000    0.000   ← ATM
C_2650  −0.066   17.63%   17.43%   −0.20%   0.362   2.79  −0.185    0.006
C_2700  −0.132   17.77%   16.20%   −1.57%   0.238   2.29  −0.302    0.020   ← 便宜

固定 w₂=−1（卖 C_2550）、w₄=+1（买 C_2700）后解：
  w₁×0.792 + w₃×0.509 + w₅×0.362  = 0.659 − 0.238        (Δ)
  w₁×2.12  + w₃×2.97  + w₅×2.79   = 2.72  − 2.29         (Vega)
  w₁×0.290 + w₃×0     + w₅×(−0.185) = 0.184 − (−0.302)    (Sml)
解：w₁=+0.177   w₃=+2.227   w₅=−2.350
```

信号触发与成本门槛：

```
dev = σ_mkt − σ_theo                       # 偏离信号
|dev| > spread + fee                        # 才值得动手；净利 = |dev| − (spread+fee)
```

> 记忆钩子：**C_2600 那行 Sml=0 是整个解法的枢纽**——大量 Vega 用 ATM 承载，不引入偏度敞口。（volarb:316-406）

## 11. PnL 归因六项——钱从哪来、亏到哪去

```
六项：rDeltaPnl / rVegaPnl / rVegaSkewPnl / rVegaKtcPnl / rBssPnl / rTradePnl
结果：aPnlChg（当日累计）

窗口损益 = 窗口末行值 − 窗口首行值        # ★ 累计快照差分铁律，禁止加总刷新值

量纲换算：aAccuCashDelta ≈ aAccuDelta × cUsedFwd × 乘数    # 元/1%变动敏感性

刷速：aPnlChg ~3s；r*Pnl ~6s；rTradePnl 成交才刷（一天几次属正常）
```

> 记忆钩子：**aPnlChg 是体温计，六项 r\*Pnl 是化验单**；差分定位主因，敞口阶跃找动作。（pnl:33-49）

## 12. 调参杠杆速查——改哪个参数、走哪条公式

| 想动什么 | 改哪个参数 | 走哪条公式 | 方向 |
|----------|-----------|-----------|------|
| 平 Δ 门槛整体松紧 | `aIocPnlMult`（IOC）/ `aLmtOpen/ClsePnlMult` | §9 MinPnl | 乘在整体上，**调参优先** |
| 平 Δ 更快 | `aFwdUnit` 调小 | §8 final_fwd | unit 小 → Fwd 位移大 |
| 同利润下量更大 | `aVolUnit/aSmlUnit/…` 放大 | §9 theo_shift | 分母大 → ts 小 |
| 拟合更信哪腿 | `cCurveFittingMult` | §5 A/rhs | 权重平方进 A |
| 曲线贴 fwd 强度 | `SSR/VCR/SCR` | §4 delta 联动 / §6 去趋势 / §8 vol 联动 | 三处同一套语义 |
| 拟合频率 | `cCurveFittingFreq` | 节流闸 | 越小越勤 |
| 单次调价极限 | `rstc` 族 / `FwdRstc` | §8 clamp | 防为配平乱报价 |

---

## 复习路径建议

1. **定价层**（§1→§4）：一条链——时间算对 → 远期挖对 → 曲线生成对 → 价格与希腊值算对；
2. **zcf 层**（§5→§7）：拟合（牛顿解 4 参数）→ 平滑（EMA+去趋势+跳变保护）→ Mark（滑窗盯市）；
3. **zarb 层**（§8→§9）：弹性调价（敞口→价格）→ 下单尺寸与五维限额；
4. **策略层**（§10）：五腿方程组与数值案例，回看 §3 的 ATM 性质和 §4 的希腊值定义怎么被用上；
5. **账目层**（§11）：六项归因 + 差分铁律；§12 是排查调参时的索引页。

配套知识点笔记见《QS知识体系知识点.md》（策略语义与机制解释）；本文只负责公式本身。
