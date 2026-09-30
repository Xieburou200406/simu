# QS 部署答疑（hy05_yh_etf 场景逐问详解）

> 依据：orange_zone/ops 与 execution 文档（product-mgmt / product-server-migration / maintenance / deploy-trading-client / copy-strategy-params / data-bridge-* / check-account-env）。

## 1. "products 表行第二段必须与 conf 同步"是什么意思

- products 表文件：`asaph:/opt/option/env/qsmgr/products`（消费机 pull 后各有一份副本）。行格式五段竖线分隔：`产品名|服务器|路径|端口|scope`。
- **第二段 = 服务器名**。conf（`data/type/qs_stk_g1/hy05_yh_etf`）里的 `server=alona` 决定 qs_update_product 把产物推给谁；products 行第二段决定 qsj_ssh/qs_ssh 登录寻址、check_account_env 连谁、调度巡检推导谁。
- 两处不一致 = 部署推到 A 机、登录/体检/巡检查 B 机。所以迁移/换机时两处都要改（migration SOP 步骤 1+2），且 commit 前 grep 相邻行防误改。

## 2. conf 的 dict= 展开去哪了（alona 的 local.cfg 里没有 dict）

- 你贴的 local.cfg 是**骨架**：`StrategyList=`（本产品策略）、`local.PortPrefix=288`（→服务端口 28801）、`local.user`、`local.env`。
- `dict=` 声明不在 local.cfg 里：它被 qs_update_product 展开进**链尾覆盖配置 postload.cfg / 相关 app 的 DictFile + TradeDate 段**（数据桥文档明确 postload.cfg 放 tunnel 地址 / TradeDate / DictFile / 每策略 URL+Expiries）。
- 更正我上一轮的说法："展开进 local.cfg"不精确——dict 走 postload（最后加载、覆盖一切）。
- 验证：在 alona 上 `grep -rn -i dict cfg/curr/ ext/postload.cfg`。

## 3. qs_jobs 在 asaph 吗？任务链有什么？"db server= 名单"例子

- **调度器不在 asaph**。asaph 只是 qs_jobs 的 git 中心仓库（eagle 开发支）。调度器实际跑在：
  - **paul**（A 机，单日）/ **timothy**（B 机，双日）——A/B 按单双日轮值执行当日任务，运行身份 tailer；
  - **jannie**（master 分支）——cron 类任务。
  - 三者都是 qs_jobs 工作副本，从 asaph pull。
- dict 任务链：每日 **08:15 / 08:40 / 08:43** 三个时刻（汇集当日字典 → 按 db 名单推送 → 校验/补推），次日 08:45 前在位。任务明细在 qs_jobs.md（未迁移）/ 面板可查。
- "db server= 名单"：qs_jobs 的 `db/<产品>` 里 `server=` 写哪台，dict 就推给哪台。例：`db/hy05_yh_etf` → server=alona → 推 alona 的 data/dict/；`db/dx01_gj_csi` → server=zoe。交易客户端不靠推送，主动 `get_dicts` 从 asaph 拉。

## 4. strategies= 与 strategy.<名>= 的机制（是不是"创建对象赋值"）

不是编程对象，是**声明式 key=value**：
- `strategies=a,b,c`：声明本产品有哪些策略（顺序即序号）；
- `strategy.<名>=<ETF现货>,<对冲腿>`：给每个策略声明标的映射（510500.SH + CSI500 股指对冲；hy05_yh_588000 只有现货一段 = 没有指数对冲腿）；
- `qs_gen_strategies_list_and_map` 收集**全池**所有 conf 的声明 → 生成 strategy.list（全部策略名）+ strategy.map（全部映射行）。
- 类比：conf 是"注册表单"，list/map 是"全池实例总表"。

## 5. strategy.list 为什么 45 行——不是追加，是整份重生成

- 每次生成都**整份重写**：池内所有注册产品的全部策略合成一份，且**排序输出**（你贴的清单按字母序，追加做不到这点）。
- 45 行 = qs_stk_g1 池当前 11 个在役产品（cx01/cx02/dx01/hy01/hy02/hy03/hy04/hy05/mx02/tl01/tl02）× 每产品 1-7 个策略。
- 新增 hy05 三行后清单变长——本质是"池"变大了。**上限 64 行**（C++ 硬限制），加产品前先算池并集。
- 为什么每个产品目录都放同一份：GUI 是全局单例，一次启动要认识全池所有策略才能连任意产品。

## 6. strategy.map 是什么

每行 `策略=现货,对冲腿`。arb/GUI 据此知道每个策略交易哪只 ETF、对冲哪个指数/期货。第二段的 988xxx/999915 是对冲腿代码（期货/现货）；只有一段的策略 = 无指数对冲腿。

## 7. multiplier.list 干什么

合约乘数（合约单位）清单，与 ul.list 标的顺序对应：**点数 × 乘数 = 名义金额 / PnL**。10000=ETF 期权，200/300=股指期权，1=现货。同样是全池并集、每目录一份（GUI 单例）。

## 8. arb 进程启动项是哪个文件

- 文件：产品目录 `/opt/option/env/prod/hy05_yh_etf/backend` 启动脚本（由 `data/base/backend.base` 模板替换 SCOPE 生成）+ `cfg/curr/` 下 arb_<name> 的 cfg（含 OidPrefix）+ arb_hosts.cfg。
- backend 脚本里的 `arb_<name>` 行（qs_link "xarb" "<name>" 生成）。启动：`./backend all` / `./backend arb_etf`；公共函数在 `scripts/qs_common`（start_one/kill_one/start_and_stop）。

## 9. daily/curr 软链：目录也能当指针？生命周期？SOD/EOD/backend 对它做什么

- 软链指向目录完全合法——它就是文件系统层的指针。
- 约定：每日一个 `daily/<YYYYMMDD>/`，`curr → 当日`。**所有进程读写 `daily/curr/...`（日志、Database/storage、pmap），换日只动 curr 一个链接，任何路径配置都不用改**。
- 生命周期：盘前 SOD 建/切当日目录 → 盘中进程写入 → EOD 落盘定格（account_eod/pmap）→ 次日 SOD 切新目录（旧目录原样保留 = 回滚底牌）。
- 部署新产品的"首日轮转"：`mv curr 20260921; ln -s 20260921 curr` = 把种子（拷来的昨日数据）挂成部署日的当日目录——次日 SOD 的 account_sod 对账才有依据。

## 10. "池"是什么——三个分支还是一个 etf

- 池 = **单分支内单个 type 目录的产品集合**，口径：`products 表 ∩ data/type/<exch>/`。
- 分支 ≠ 池：**qs_etf 分支下有 etf 和 qs_stk_g1 两个池**（strategy.list 各自独立）；qs_csi、qs_com 各一池；test_etf/test_csi 独立测试池。
- 你贴的 45 行属于 **qs_stk_g1 池**。

## 11. qs_update_product：推什么 / SCOPE / max+1 / 是不是 git pull

- 推的是**打包的 base（二进制 + cfg 模板）**，不是 conf——conf 只在 asaph 上被读，决定"推给谁、生成什么"。目标 = conf 的 server= 那**一台**机（跑 for 循环才遍历全池）。
- **SCOPE**：模板里的占位符（backend.base/frontend 里写 `SCOPE`），部署时 sed 成产品名（hy05_yh_etf）——同一份模板据此区分不同产品的进程名/日志/实例。
- **max+1**：products 行第 4 段端口 = PortPrefix×100+1。新产品行未注册时，自动取现有最大值 +1 追加注册——端口自动分配防手工挑号冲突（你的 PortPrefix=288 → 28801）。
- **不是跳到每台机 git pull**：产品机没有 git（现行口径交易机无任何 repo）。git pull 只发生在消费机。qs_update_product = asaph 读模板 → scp 物理推产物。

## 12. 客户端 qs_update_client 和 git pull 的关系

git pull 由 alias 链里**前面的步骤**完成（checkout + qs_update）；qs_update_client 用**已经 pull 下来的本地 qsmgr 副本**（data/base + products 表）生成客户端配置，自己不做任何 git 操作。

## 13. ext/ 下那么多文件为什么全手工

分工明确：`sys/cfg/curr/` = 函数生成（共性），**不可手改**；`ext/` = 每机每产品差异（柜台凭据/行情源/到期/组合开关），**手工编辑**，并通过 `inc=` 链覆盖生成配置。runbook 步骤 2 就是填 ext 差异。

## 14. "server= 才是调度开关"怎么按它

- 产品机 = `db/<产品>` 的 server= 指向的运行机（alona）。
- qs_jobs 调度器（paul/timothy，tailer 身份）每 60s 重读任务表、执行时现读 db：**SOD 启动、EOD 落盘、巡检（进程/隧道检查）、dict 推送**全部 ssh 到 server= 那台机执行。改 server= 即全链改向（热加载，无需 restart）。
- 坑：验证连通必须以 tailer 身份（abigail 通 ≠ tailer 通）。

## 15. auto_sod_eod=1 进队列后发生什么，怎么进去的

- 调度器扫描 db：`active=1` 且 `auto_sod_eod=1` 的产品在 tasks 时刻**自动执行**：08:52 fire → 产品机拉起整组引擎（centralizer/curvefitting/xparam/xdatabase/xrisk/xes/mdadapter/arbattr/arb_*），读 daily/curr 种子；15:05 EOD 自动落盘。=0 则只能手动/面板触发。
- "怎么进去"：把 db 文件放进调度器的 db/ 目录（jannie master；phoenix 侧惯例 auto_sod_eod=0），调度器 60s 内热加载发现。

## 16. git_sync 铺给"各消费机"是谁

pull qsmgr 的机器：**ben、jannie、paul、timothy、[面板机]**（eagle 本地支未推 origin）；个人机也 pull（origin=hope）。注意 git_sync 只 commit 不 push——消费机自己 pull。

## 17. "服务端全套 cfg + 四清单 + fxrate"具体哪些；check_account_env/面板读什么

- 服务端 cfg：local.cfg、arb_hosts.cfg、arb_<name> cfg + OidPrefix、arb 启动项、expiry.list.sample。
- 四清单：strategy.list / strategy.map / ul.list / multiplier.list；加 fxrate.cfg（汇率）。
- check_account_env 读 conf 做三要素核对（qsmgr conf / paul+timothy db 双机 md5 / 交易服务器）并 ssh 到 conf.server 只读体检；面板读 conf+products+servers 做寻址与 dryrun。

## 18. U/O/F、交易所缩写、ini 后行覆盖

- **U=Underlying 标的，O=Option 期权，F=Futures 期货**。CFFEX 中金所、SHEX 上交所、SZEX 深交所、SHFE 上期所。
- ini 后行覆盖前行：同名 key 出现多次时**最后一条生效**（XConfig 解析语义），查配置用 `tail -1`。gw_src 例子里 SHEX.O=yd 其余全 MockEs = **只有上交所期权实盘，其余全模拟**。

## 19. xes 是什么、在哪里；行情是谁

- xes = 交易/柜台执行侧应用（backend 应用组之一，进程在产品目录下），加载 gw_src.cfg 做交易所→网关路由与柜台连接（yd 四件套）。它的日志就是 es.log（09:05 看 front end connected）。
- 行情不是 xes——是 **mdadapter**（读 md_src.cfg）。

## 20. md_src.cfg 三个源分别是什么

`Dms.Srcs=GlxFutCtp,yhctp,yhopctp` 声明三个行情源实例：
- **yhopctp**（OptCtp）：银河期权柜台行情（期权链）；
- **yhctp**（StkCtp）：银河现货（ETF）行情；
- **GlxFutCtp**（FutCtp）：期货/股指行情（对冲腿 CSI300/500 用）。
URL/BrokerID/UserID/Password = CTP 前置连接四件套。mdadapter 从三路收行情 → 归一 → 喂 **centralizer** → 全产品进程订阅。

## 21. expiry.list 与 ${UsedExpiries}

- 你贴的第一行 "Us expiry.listedExpiries=..." 是粘贴断行，实际是变量定义：**`UsedExpiries=20261028,20261218`**——就定义在本文件第一行。
- `SelectedExpiries.<策略>.<标的>` 不是对象/实例，是**层级 key 命名约定**（策略 × 标的两维），值 = 逗号分隔到期列表；`${UsedExpiries}` 是变量引用——所有策略共用一组到期，改一行全改。
- 消费者（都在产品机 backend 组里）：**curvefitting** 进程（CFExpiry 按到期拟合 fwd/vol/greeks）、**arb_<name>**（只交易/订阅所选到期）、**GUI**（T 型报价只画所选到期，经 299 隧道订阅）。

## 22. postload.cfg 干什么

local.cfg 链尾 `inc=./ext/postload.cfg`——**最后加载、覆盖前面一切**：放每机覆盖项（tunnel 地址 / TradeDate / DictFile / 每策略 URL+Expiries / Combo.Enabled）。`Combo.Enabled=1` 开启组合策略。runbook 把它标成 expiry.list 是标题贴错。

## 23. "参数 merge，override 优先于 pmap"何意；怎么 override

- xdatabase 启动顺序：先读 pmap 存档（上次运行参数快照）→ 再逐行 merge `pdatabase.override.csv`，**同名参数 override 赢** → override 是"启动权威值"。
- pmap dump 是盘中运行态（含当日改动），拿它当 override 源会参数漂移（copy-strategy-params.md §2 的坑）。
- 操作：重建/改 override.csv → `./backend xdatabase`（qs_common start_one：停旧进程→拉起→启动时重读 OverrideCsv）→ 日志 grep "will be override" 验证条数。

## 24. 次日首跑盯盘全流程（详细版）

| 时刻 | 发生什么 | 在哪看 |
|------|----------|--------|
| 08:15/08:40/08:43 | dict 任务链：调度器（paul/timothy）从 asaph 汇集当日字典 → 推 db server= 名单机的 data/dict/ | qs_jobs 面板任务日志 |
| 08:45 | 检查 dict 在位（缺了 GUI 空树崩溃；客户端另有 get_dicts 兜底） | 产品机 `ls data/dict/` |
| 08:52 | A/B 当日轮值机 fire → 产品机自动拉起整组引擎（auto_sod_eod=1），读 daily/curr 种子 | 面板 fire 日志 |
| 09:05 | es.log 出现 `add ... connector` + `front end connected`（xes 连上柜台）；行情链 mdadapter→centralizer 通 | 产品机 daily/curr/…/es.log |
| 09:05+ | account_sod 与种子 EOD 对账——种子错 = 对账炸，这就是 daily/curr 种子的意义 | SOD 日志 |
| 盘中 | eyeball（michael:5000）实时 PnL/风控 | 浏览器 |
| 15:05 | EOD：落盘 account_eod / pmap 进当日 daily 目录，供次日 SOD 对账 | 面板/产品机 |
