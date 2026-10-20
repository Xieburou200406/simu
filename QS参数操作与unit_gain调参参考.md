# QS 期权做市系统：操作含义与 unit / gain 调参参考

> 整理自本地权威源：orange_zone（`strategy/delta-hedge.md`、`strategy/zarb-zcf-flow.md`）、`QS公式手册.md`（§8/§9）、`QS知识体系知识点.md`（§4.2–§4.6）。
> 飞书原文档（docx/Apjtdh3…、KIvSdZ8…）需登录、WebFetch 无法抓取；若需按原文措辞对齐，请把正文粘贴或导出本地文件。

## 一、对冲方向操作（"卖 Delta" / "买 Delta" 是什么意思）

系统不是直接"买/卖某类期权"，而是按**风险方向**下达动作（delta-hedge.md §4）：

- **卖 Delta** = 卖 Call **或** 买 Put（目的：削减正 Delta / 抑制新增正 Delta）
- **买 Delta** = 买 Call **或** 卖 Put（目的：削减负 Delta / 抑制新增负 Delta）

一阶价格 / 边际效果（持多 Delta 时）：

| 动作 | TV 变化 | 边际变化 | 作用 |
|---|---|---|---|
| 买 Call | Call TV ↓ | 买入边际 ↓ | 抑制新增正 Delta |
| 卖 Put | Put TV ↑ | 卖出边际 ↓ | 抑制新增正 Delta |

- `initialize_ioc_basket` 对 Call 用买/卖 Delta 许可，对 Put 交换这两个许可——体现的是**风险方向**，不是把 Call/Put 买卖方向混为一谈。
- Forward 反馈是**软性库存管理**：只有价格、流动性、收益门槛、风控同时允许才可能成交，**不保证立即归零**。Wing 联动、其他 Greeks 反馈、限幅或极端参数可能改变幅度，应以重定价结果核对。

## 二、弹性调价五维参数（每个 underlying 一套）

软对冲用"敞口 → 价格位移"的 PID 式控制，对 5 个风险维度（Δ/Fwd、Vega/Vol、Skew/Sml、KtC、KtP，外加 Strike 仓位 SS）各自带 4 个旋钮：

| 旋钮 | 含义 | 口径 / 备注 |
|---|---|---|
| **Offset（目标敞口）** | 希望保留多少该维敞口，通常设 0 | 与各 Accu 同口径 |
| **Unit（归一化分母）** | 每多少敞口算 1 个弹性单位 | 决定同等偏差换算成多大位移 |
| **Elastic（弹性系数 / 控制器增益）** | 每 1 单位敞口误差换多少价格位移 | 与 unit 一乘一除一对 |
| **Rscr / Restrict（调整上限）** | 位移幅度截断，防极端敞口推飞 | Fwd 维用 FwdRstc，其余各维各用 Rscr |

通用公式（公式手册 §8）：

```
adjusted = targ·alph + (1−alph)·smth + clamp((offs−pos)·elas/unit, ±rstc)
```

Fwd 维特例（走远期通道，不动单个期权 TV，而是移动公共 `used_fwd`）：

```
final_fwd = used_fwd + (exp_fwd_offs − exp_accu_delta)·elastic/exp_fwd_unit
           夹 [used_fwd − FwdRstc, used_fwd + FwdRstc]
# Long Δ 且 offs≈0 → 右项为负 → final_fwd < used_fwd，方向必与 AccuDelta 相反
```

Strike 级远期位移（逐 strike 重定价 → aArbAdjTv → aArbSSTv）：

```
strike_fwd = fwd − (该 strike 期权持仓 Δ)·fwd_elastic/strike_delta_unit
```

## 三、下单 / 风控操作链

- **QuoteMode 四选**：Tv / Market / Both / Neither。
- **五维限额裁剪**：`(累计敞口 − Offs偏置) + 本单风险 ≤ IocMax*`（Δ/Vega/Skew/KtC/KtP 各自一条），任一维裁到 0 → 本单归零。
- **卖出腿 10 道闸**（hedge §4）：strike 仓位上限 → Arb 仓位上限（PosOnDeltaRatio，delta 越虚允许仓位越大）→ 深 ITM / |delta| 越界只准平仓 → 市场深度 → 单量上下限 → OrderAction（先平后开，AllowSellOpen/Close）→ 五维累计限制 → MinPnl 门槛 → 撤单限流（MaxCxlCnt）→ 跨到期月篮子复核。
- **IOC 篮子搜索**：最多 8 轮；假设整篮成交后重定价，任一腿 `adj_tv − ioc_px < MinIocPnl` 则整体降尺寸（宁可单小、不能缺腿）；全通过且能加则加量重定价。8 轮上限是搜索收敛与机会流失的折中。

## 四、unit 如何调节

`unit` 在公式**分母**：`位移 = (offs−pos)·elas/unit`；theo_shift 里各维 unit 也全在分母。

- **放大 unit** → 同等敞口产生的位移更小 → 系统对敞口更"钝"、报价更贴盘口、单量更大、对冲更慢。
- **调小 unit** → 位移更大 → 更激进、对冲更快。
- 具体旋钮（调参建议表）：
  - 平 Δ 太慢 / 迟迟不对冲 → **调小 `aFwdUnit`**（unit 小 → Fwd 位移大 → 平 Δ 更快）。
  - 想同利润下量更大、更易平 Delta → **放大 `aVolUnit / aSmlUnit / …`**（分母大 → theo_shift 小 → 单量大）。
- 警告（delta-hedge.md §4.2）：**不得把"放大仓位上限 + 降 MinPnl + 放大 VolUnit"写成平 Delta 的默认修复**；参数改动先在冻结盘口/持仓上复算，报告成交后全部风险和边际，再走变更流程。

## 五、gain 如何调节（两种含义，都给你）

### 含义 1：Elastic（控制器增益，= elas/unit 里的 elas）

- 放大 Elastic → 同等敞口误差产生的位移更大 → 更激进对冲；与 unit 是"一乘一除"一对：想更激进，要么调小 unit，要么调大 elas；想更钝，反之。
- 位移最终被 `Rscr / FwdRstc` 截断封顶，所以增益再大也有上限保护。

### 含义 2：MinXxxGain（每笔交易最低收益门槛，min_pnl 的组成）

- 组成：`min_pnl = MinFwdGain + MinVolGain + MinSmlGain + MinKtCGain + MinKtPGain + spd_min_gain + FixedGain`
- 这些是"这笔交易至少赚多少才允许下"的各维度收益要求。
- 调节：**优先动总系数 `IocPnlMult / LmtOpenPnlMult / LmtClsePnlMult`**（乘在整体 min_pnl 上），比逐个调各 gain 源更直接。
- `spd_min_gain = (spot_spread − DrvAvgSpd) × delta × SpdGainMult`（价差门槛，SpdGainMult 为价差增益乘数）。
- 特殊修正：ITM 再 × `ItmPnlMult`；有合成仓位时卖 Call 的 `ask_pnl` 再上调；合成仓位 × `synth_pnl_mult`。
- 想降低门槛（更容易成交/平仓）→ 调小 `IocPnlMult` 或对应 gain；想提高门槛（更挑利润）→ 调大。

## 六、记忆钩子

- size 分子是利润、分母是自己的冲击；**限额管"能不能"、MinPnl 管"值不值"、theo_shift 管"划不划算"**。
- **unit 全在分母，是调参杠杆**：放大 → 钝 / 量大 / 慢；调小 → 激进 / 快。
- 软对冲 = "始终趋向零敞口"的化身：前两项（平滑）是化妆，第三项是行动。
