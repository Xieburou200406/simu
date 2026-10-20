# 《ETF期权交易操作评分标准（检查点清单）》解义

> 本文把清单里的 **33 个检查点** 逐条拆解，解释"每个操作到底是什么、为什么要这么做"，解释口径优先取自 **《期权做市系统一站通（含视频详解）》**（下文简称"一站通"）。清单本身只给参数名和 grep 命令，不解释原理；一站通负责讲原理。
>
> 清单总分 100 分，分 7 个阶段。优秀 ≥95、及格 ≥90、不及格 <90。

---

## 〇、先看"怎么读这份清单"（方法论）

### 1. 打分数据从哪来
- **日志位置**：服务器 `jannie`，目录 `/opt/option/env/simu/zhusz/510500/daily/yyyyMMdd/Centralizer/centralizer.log`。510300 和 510500 的日志**都在这一个文件**里，`yyyyMMdd` 是要打分的日期。
- **打分脚本**：用服务器 `paul` 上的 `/opt/qs/scripts/qs_trade_eval.sh`，**运行在 `jannie` 上**拉取日志与依据。脚本跑得慢，要等。
- **产出**：依据脚本结果给 510300 / 510500 打分，写入《ETF期权交易操作评分报告》，要细化到"每个操作时间段"的得分。

### 2. 层级代码（参数名前面那个字母）
| 代码 | 含义 | 范围 |
|---|---|---|
| **O** | OptMain | 期权合约级（单个合约） |
| **E** | ExpMain / ExpVol | 到期日级（某个月份） |
| **U** | UlMain | 标的级 |
| **S** | StgMain | 策略/账户级 |
| **F** | Fut | 期货合约级 |

⚠️ **最关键的一条**：同名参数在不同层级作用不同（例如 `aArbSentBidPx` 在 O 层级有意义、E 层级可忽略）。打分时**必须确认层级正确**。

### 3. grep 怎么抓（极易踩坑）
- **为什么抓 `publishing` 不抓 `value changed`**：交易员能改的参数，改后**两者都会出现**；但交易员不能改的参数、或前一天的值，启动时没有 `value changed`，**只要加载了就仍有 `publishing`**。所以检查/打分只用 `publishing`。
- **一次性抓**：别一个参数一个参数提，用 `grep -E '参数1|参数2'` 一次把要查的都抓到临时文件，一起分析。
- **两个例外**（没有 publishing）：`rMaxPnlReset`、`rClearRiskPnl` 要抓 `value changed on pipe`，命令：
  - `grep "value changed on pipe" | grep rClearRiskPnl`（CP12）
  - `grep "value changed on pipe" | grep rMaxPnlReset`（CP14）
- **交易所筛选**：Fut 层级加 `grep "CFFEX"`（期货合约都在中金所）；Stg 层级无交易所字段、不用加；O/E/U 加 `grep "SHEX"`（ETF 期权在上交所）。

### 4. 一个 grep 模板（清单 TABLE 3）
```
grep publishing centralizer.log | grep -E '参数名1|参数名2' > /tmp/ops.log
```

---

## 一、开盘前准备阶段（09:00–09:15）｜7 个检查点｜24 分

**本阶段目标**：把定价源（期货 vs 现货）、报价/套利基础开关、组合保证金、被动单阈值都设对，为开盘扫清配置。

### CP1  OptMain 的 ComboMode = Both（O.rComboMode = 3）｜4 分
- **操作**：把期权主模块的组合保证金模式设为 Both（标准值）。
- **含义**（清单 TABLE 13）：ComboMode 取值 0=Neither（不用组合保证金）/ 1=Comb（组合发送）/ 2=Split（拆分）/ 3=Both（标准值）。做市日常用 **Both = 标准组合保证金模式**。
- **验证**：`grep publishing | grep "SHEX" | grep rComboMode`，时间窗 09:00–09:15，且要看该时段**所有** rComboMode 记录（可能有多次赋值）。

### CP2  ExpMain 的 MaxLmtNum = 500（或 600）（E.aMaxLmtOrdNum = 500）｜4 分
- **操作**：设到期日级被动（限价）单的"发单阈值"为 500/600。
- **含义**（一站通 TABLE 3）：`MaxLmtNum` = **被动单发单阈值**（系统一个到期月内最多发出多少笔限价单）。设够大，保证盘中被动报价不会因额度耗尽而停摆。
- **验证**：`grep publishing | grep "SHEX" | grep aMaxLmtOrdNum`。

### CP3  UlMain 的 IocOn = Y（U.aEnableIoc = 1）｜4 分
- **操作**：标的级打开"对价单（IOC）"开关。
- **含义**（一站通 TABLE 3）：`IocOn 通过对价成交的方式开始套利对冲交易`——即让系统用 IOC（立即成交或撤销）订单执行套利/对冲。开盘前打开，盘中才能用 IOC 方式维持头寸趋零。
- **验证**：`grep publishing | grep "SHEX" | grep aEnableIoc`。

### CP4  UlMain 的 MinManTrdPnL = -20（U.aMinManualTradePnl = -20）｜2 分
- **操作**：标的级设"手动交易最小盈亏"为 -20。
- **含义**：这是手动交易的**盈亏下限/容忍阈值**（单位：元/点，按标的口径）。设为 -20 表示允许手动单在小幅亏损下仍可执行，避免在临界处被系统拦截。一站通未单列此参数，按清单口径理解即可。
- **验证**：`grep publishing | grep "SHEX" | grep aMinManualTradePnl`。

### CP5  期货定价合约 UlType 设置（Trade↔Simple 切换）（F.aUlpType = 0/1）｜4 分
- **操作**：在期货合约层把定价标的类型在"Trade（期货）"与"Simple（现货/合成）"之间切到期货侧。
- **含义**（一站通 §一.1.2）：510300、510500 等 ETF 期权，**必须用相关期货主力合约作定价合约**——因为期货行情更新频率远高于 ETF（ETF 一档行情约 3 秒一更，期货更密）。用现货定价会"慢"，所以 `aUlpType` 要切到期货定价。这是 ETF 做市定价准确性的根基。
- **验证**：`grep publishing | grep "CFFEX" | grep aUlpType`。
- 📌 清单特别提示：510300/510500 **要用期货定价，不能用现货定价**。

### CP6  定价合约 UlWeight = 100（F.cUlWeight = 100，U.cUlWeight = 0）｜3 分
- **操作**：期货合约层的定价权重设 100，标的层（现货）权重设 0。
- **含义**：`cUlWeight` 是"定价标的权重"。把期货权重拉满（100）、现货权重清零（0），等于**明确指定期货才是主定价源**——和 CP5 配套，确保定价完全由期货驱动。
- **验证**：两条 `grep publishing ... grep cUlWeight`（F 层加 CFFEX，U 层加 SHEX）。

### CP7  非定价合约 UlWeight = 0（F.cUlWeight = 0）｜3 分
- **操作**：非定价期货合约的权重设 0。
- **含义**：除被选中的那个定价期货外，其它期货合约不参与定价（权重 0），避免多合约混算把价格搞脏。
- **验证**：`grep publishing | grep "CFFEX" | grep cUlWeight`。

---

## 二、集合竞价处理与盘口校验（09:25–09:29）｜9 个检查点｜26 分

**本阶段目标**：把波动率曲线从"隔夜手动值"切到"系统自动拟合"，并清掉拟合带来的风险计数、设好风控阈值，准备开盘。

### CP8  BssMode = Smooth（E.cBssMode = 1）｜4 分
- **操作**：到期日级隐含基差模式设为 Smooth（自动拟合）。
- **含义**（一站通 §二.2）：`BssMode: 隐含基差模式，Manual 为手动设置，Smooth 为系统自动拟合`。Smooth 让系统用 EMA 等算法**自动算出稳定隐含基差**（一站通 §一.2 提到基差有均值回归特性，用 EMA 滤噪）。集合竞价前切 Smooth，避免用隔夜手动基差开盘。
- **验证**：`grep publishing | grep "SHEX" | grep cBssMode`。

### CP9  CFMode = FitPx（E.cCFMode = 1）｜4 分
- **操作**：波动率曲线拟合模式设为 FitPx（使用平滑后拟合曲线定价）。
- **含义**（一站通 §二.2）：`CFMode` 选 Manual 是把交易员手动曲线赋给 U 系；**选 FitPx 是把平滑后的拟合曲线赋给 U 系（U.Bss/U.Vol/U.Sml/U.KtC/U.KtP）**，即实际拿去给期权定价的就是它。开盘前用 FitPx，保证定价用"系统拟合+平滑"的曲线，而非手动曲线。
- **验证**：`grep publishing | grep "SHEX" | grep cCFMode`。

### CP10  执行 CFReset（E.cCFReset = 1）｜4 分
- **操作**：点击执行波动率曲线重拟合。
- **含义**（一站通 §二.2）：`CFReset: 点击后系统模型根据最新的市场行情拟合波动率曲线`。集合竞价前用最新盘口重算曲线，把隔夜跳空消化掉。
- **验证**：`grep publishing | grep "SHEX" | grep cCFReset`。

### CP11  CFPanic = N（E.cPanic = 0）｜2 分
- **操作**：拟合恐慌开关保持 N（关闭）。
- **含义**（一站通 §二.2）：`CFPanic` 在"两次拟合间某参数差值 > 设定 jump 值"时会**自动从 N 跳 Y**，同时 CFMode 跳 Manual；**且显示 Y 时无法打开交易开关**，所以常态必须保持 N。开盘前确认它没被触发。
- **验证**：`grep publishing | grep "SHEX" | grep cPanic`。

### CP12  拟合后执行 rclear（E.rClearRiskPnl = 1）｜4 分
- **操作**：拟合完成后清一次"风险 PnL"。
- **含义**：重拟合会把曲线整体挪动，若不清零，这部分曲线位移会被误计入当日盈亏（PnL）。`rClearRiskPnl` 把拟合造成的"账面 PnL 跳变"基线重置掉，让当日 PnL 只反映真实交易。**注意**：此参数**没有 publishing**，要抓 `grep "value changed on pipe" | grep rClearRiskPnl`。
- **验证**：`grep "value changed on pipe" | grep rClearRiskPnl`。

### CP13  参数未触极值（Min/Max）（E.cMinImpliedVol 等未越界）｜3 分
- **操作**：确认拟合出的隐含波/基差/偏度/峰度等没有顶到上限或下限。
- **含义**（一站通 §二.6）：拟合有上下限保护——`I.Vol.Min/Max`、`I.Sml.Min/Max`、`I.KtC/KtP` 的 Min/Max、`I.Fwd.Min/Max` 等。若某参数顶到边界，说明拟合被夹值、曲线失真，开盘定价不可信。所以检查"未越界"。
- **验证**：`grep publishing | grep "SHEX" | grep cMinImpliedVol`（及同类上限参数）。

### CP14  StgMain 执行 MaxPnlReset（S.rMaxPnlReset = 1）｜2 分
- **操作**：策略级重置"当日最大盈利"统计。
- **含义**（一站通 TABLE 17）：`MaxPnl` 显示当日最大 PnL；`rMaxPnlReset` 在开盘前把该统计归零，使当日最大盈利从 0 起算。**注意**：无 publishing，抓 `grep "value changed on pipe" | grep rMaxPnlReset`。
- **验证**：`grep "value changed on pipe" | grep rMaxPnlReset`。

### CP15  StgMain 设置 Panic = N（S.rPanic = 0）｜2 分
- **操作**：策略级总恐慌开关设 N（关闭）。
- **含义**：`rPanic` 是**账户/策略级熔断开关**。Y = 全策略停交易；开盘前必须 N，否则打不开交易。和 CP21（午盘设 Y）、CP26（下午设 N）、CP29（收盘前设 Y）形成"开/关交替"的节奏。
- **验证**：`grep publishing | grep rPanic`（Stg 层无交易所字段，不加 keyword）。

### CP16  StgMain 设置 MaxPnlChg = 2000（S.rMaxPnlLoss = 2000）｜1 分
- **操作**：策略级设"最大回撤阈值"为 2000。
- **含义**（一站通 TABLE 17）：`MaxPnlLoss: 设置最大回撤阈值`。超过该值系统触发停止发单等风控。开盘前按当日风险预算设好（此处 2000）。
- **验证**：`grep publishing | grep rMaxPnlLoss`。

---

## 三、正式开盘操作（09:30）｜4 个检查点｜12 分

### CP17  ExpVol 执行 CFReset（E.cCFReset = 1）｜3 分
- **操作**：09:30 一开，立刻再拟合一次波动率曲线。
- **含义**：同 CP10。开盘瞬间盘口从集合竞价切换为连续竞价，波动剧烈，用最新连续竞价行情再拟合一次，让定价曲线跟上真实市场。
- **验证**：`grep publishing | grep "SHEX" | grep cCFReset`，时间窗 09:30–09:30:10。

### CP18  ExpMain 设置 LmtOn = Y（E.aEnableLmt = 1）｜3 分
- **操作**：到期日级打开"限价单"套利对冲开关。
- **含义**（一站通 TABLE 3）：`LmtOn 通过限价单的方式开始套利对冲交易`。与 CP19 的 IOC 方式并列，开盘后两者都开，系统既发对价单也发限价单维持头寸。
- **验证**：`grep publishing | grep "SHEX" | grep aEnableLmt`，时间窗 09:30–09:31。

### CP19  ExpMain 设置 IocOn = Y（E.aEnableIoc = 1）｜2 分
- **操作**：到期日级打开"对价单"套利对冲开关。
- **含义**（一站通 TABLE 3）：`IocOn 通过对价成交的方式开始套利对冲交易`。注意 CP3 是在 **UlMain（标的级）** 开 IocOn，这里是 **ExpMain（到期日级）** 开，层级不同、作用不同——再次印证"同名参数看层级"。
- **验证**：`grep publishing | grep "SHEX" | grep aEnableIoc`，时间窗 09:30–09:31。

### CP20  检查 SentLmtNum < MaxLmtNum，必要时增加（E.aSentLmtOrdNum < E.aMaxLmtOrdNum）｜4 分
- **操作**：确认已发被动单数 < 阈值，不够就调大 MaxLmtNum。
- **含义**（一站通 TABLE 3）：`SentLmtNum` = 被动单已发数量，`MaxLmtNum` = 被动单发单阈值。开盘后若已发数逼近阈值，系统将无法继续报被动单，需提前把上限调高。
- **验证**：`grep publishing | grep "SHEX" | egrep "aSentLmtOrdNum|aMaxLmtOrdNum"`，时间窗 09:30–11:28（覆盖整个上午）。

---

## 四、午盘关闭（11:28）｜2 个检查点｜12 分

### CP21  StgMain 设置 Panic = Y（S.rPanic = 1）｜6 分
- **操作**：午休前把策略级熔断开关打到 Y。
- **含义**：和 CP15 相反——午休停盘期间不想再有单子挂着/发出，用 Panic=Y 让全策略停止交易。**（开盘用 N、午休用 Y、下午再用 N、收盘前再用 Y，这是全网开关的节奏。）**
- **验证**：`grep publishing | grep rPanic`，时间窗 11:28–11:28:30。

### CP22  确认 OptMain 中 SBP/SAP 挂单为 0（O.aArbSentBidPx=0, O.aArbSentAskPx=0）｜6 分
- **操作**：确认合约级没有在途买单/卖单。
- **含义**（一站通 §三.1.1）：`SBP = 在途买单价格，SAP = 在途卖单价格`。午休前要把挂单撤干净，**值为 0 表示无挂单**。
- ⚠️ 清单特别提示：`aArbSentBidPx/aArbSentAskPx` **只在 O 层级（OptMain）有意义**，E 层级可忽略。
- **验证**：`grep publishing | grep "SHEX" | grep aArbSentBidPx`，时间窗 11:28–11:30。

---

## 五、下午开盘（13:00）｜6 个检查点｜18 分

> 下午开盘是"上午开盘流程的精简重放"：再平滑基差、再拟合、再清 panic、再开套利开关。

### CP23  ExpVol 设置 BssMode = Smooth（E.cBssMode = 1）｜3 分
- 同 CP8。下午开盘前基差重新切回系统自动拟合。验证 `grep cBssMode`，窗 13:00–13:01。

### CP24  ExpVol 设置 CFMode = FitPx（E.cCFMode = 1）｜3 分
- 同 CP9。下午用拟合平滑曲线定价。验证 `grep cCFMode`，窗 13:00–13:01。

### CP25  ExpVol 执行 CFReset（E.cCFReset = 1）｜3 分
- 同 CP10/CP17。下午开盘用最新行情再拟合。验证 `grep cCFReset`，窗 13:00–13:01。

### CP26  StgMain 设置 Panic = N（S.rPanic = 0）｜3 分
- 同 CP15。午休的 Y 解除，恢复交易。验证 `grep rPanic`，窗 13:00–13:01。

### CP27  ExpMain 设置 IocOn=Y, LmtOn=Y（E.aEnableIoc=1, E.aEnableLmt=1）｜3 分
- 同 CP18/CP19。下午重新打开 IOC + 限价双套利通道。验证 `grep aEnableIoc`（LmtOn 同理），窗 13:00–13:01。

### CP28  检查 SentLmtNum 和 MaxLmtNum（E.aSentLmtOrdNum < E.aMaxLmtOrdNum）｜3 分
- 同 CP20。下午盘前再确认被动单额度充裕。验证 `egrep "aSentLmtOrdNum|aMaxLmtOrdNum"`，窗 13:01–14:45（覆盖下午前半段）。

---

## 六、收盘前风险确认（14:45–14:55）｜3 个检查点｜5 分

### CP29  StgMain 设置 Panic = Y（S.rPanic = 1）｜2 分
- 同 CP21。收盘前再次熔断，停止新单。验证 `grep rPanic`，窗 14:45–14:55。

### CP30  14:57 后不再报撤单（O.aArbSentBidPx=0, O.aArbSentAskPx=0）｜1 分
- 同 CP22。收盘集合竞价阶段要确保无在途单。验证 `grep aArbSentBidPx`，窗 14:45–15:05。
- ⚠️ 同样只在 O 层级看。

### CP31  ExpRisk 设置 SplitToNet = Y（E.rSplitToNet = 1）｜2 分
- **操作**：到期日级把持仓"拆分到净头寸"。
- **含义**：`rSplitToNet` 是把组合/组合保证金下的持仓**拆回为净额（net）头寸**用于盘后风险与结算报送。收盘前做这步，保证 EOD 风险统计按净头寸口径正确清算。一站通未单列，按清单+常规风控理解。
- **验证**：`grep publishing | grep "SHEX" | grep rSplitToNet`，窗 14:45–14:55。

---

## 七、收盘归因（15:00–15:10）｜2 个检查点｜3 分

### CP32  收到集合竞价后执行 CFReset 重拟合（S.cCFReset=1 或 E.cCFReset=1）｜1 分
- **操作**：收盘集合竞价数据到手后，再拟合一次曲线。
- **含义**：同 CP10。收盘竞价的成交价是最新的"收盘价锚"，用它重拟合，使当日最终曲线与收盘行情一致，便于盘后归因。可在策略级或到期日级触发。
- **验证**：`grep publishing | grep cCFReset`，窗 15:00–15:05。

### CP33  点击 Affirm 保存数据（E.aAffirm = 1 或 0，有值即可）｜2 分
- **操作**：点击"确认/保存"按钮，落盘当日数据。
- **含义**：`aAffirm` 是**确认保存**动作——把当日会话的曲线、仓位、参数等写入归档。`aAffirm` 取 1 或 0 都行，**有数值记录即可**，不要求特定值。这是收盘归因的最后一步。
- **验证**：`grep publishing | grep "SHEX" | grep aAffirm`，窗 15:00–15:10。

---

## 八、易错点速记（打分人必看）

1. **层级是命门**：同名参数 O/E/U/S/F 作用不同。`aEnableIoc` 在 U（标的级，CP3）和 E（到期日级，CP19/CP27）都出现；`aArbSentBidPx` 只认 O 层级。
2. **两个参数没有 publishing**：`rClearRiskPnl`(CP12)、`rMaxPnlReset`(CP14) 只能抓 `value changed on pipe`，其它一律抓 `publishing`。
3. **交易所 keyword**：F 加 `CFFEX`，O/E/U 加 `SHEX`，S 不加。
4. **Panic 开关节奏**：开盘 N（CP15）→ 午休 Y（CP21）→ 下午 N（CP26）→ 收盘前 Y（CP29）。`rPanic`/`cPanic` 要分清（策略级 vs 拟合级）。
5. **SBP/SAP 只看 O 层**：`aArbSentBidPx/aArbSentAskPx = 0` 才是"无挂单"，且只在 OptMain 有意义。
6. **期货定价铁律**：510300/510500 必须 `aUlpType` 走期货 + `cUlWeight` 期货=100/现货=0（CP5/CP6/CP7），否则定价慢且失真。
7. **BssMode/CFMode/CFReset 三件套**在开盘前、下午开盘前、收盘竞价后反复出现（Smooth + FitPx + Reset），是"让曲线跟上最新盘口"的核心动作。

---

## 九、与《一站通》章节对照表

| 检查点涉及的概念 | 一站通出处 |
|---|---|
| 定价合约（期货/现货/合成）、隐含远期/基差、波动率曲线 Wing 模型 | §一.系统介绍（1–3） |
| BssMode / CFMode / CFReset / CFPanic / 曲线数据类型（U./S./M./P. 系） | §二.波动率曲线拟合模块（2） |
| Min/Max 拟合上下限（I.Vol/ Sml/ KtC/ KtP/ Fwd 的 Min/Max） | §二.6 拟合的参数设置 |
| IocOn / LmtOn（套利对冲开关）、MaxLmtNum / SentLmtNum（被动单） | §三.套利交易模块（2.1–2.3、TABLE 3） |
| SBP / SAP（在途买卖价） | §三.1.1 OptMain 市场价/理论价/仓位 |
| MaxPnlLoss / MaxPnl / Panic（风控阈值） | §二.风控指标清单 TABLE 17 |
| 三层风控、熔断机制 | 二.风控指标清单（一） |
