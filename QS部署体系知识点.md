# QS 部署体系知识点（qsmgr × qs_jobs × 配置链）

> 知识点式整理，依据 orange_zone/ops 与 execution 文档。所有结论都标了出处文档可回查。

## 一、仓库形态决定信任边界

- git 仓库两种形态：**裸仓库**只有版本库本体（objects/refs），无工作区，专为安全接收 push 而生；**非裸仓库**有工作区，能编辑文件、能跑程序，但 git 禁止向其当前 checkout 分支 push（`refusing to update checked out branch`），否则远端工作区与 HEAD 脱节。
- 本体系三个层次的仓库形态：
  - **hope:/opt/dev/qsmgr = 裸仓库**，[个人机] 的 origin，push 全分支无拒绝——它存在的意义就是承接开发侧的 push；
  - **asaph:/opt/option/env/qsmgr = 非裸工作库**（checkout 通常在 qs_csi），一库两用：既是人直接切支改 conf、跑 qs_update_product 的**操作台**，又是消费机的 **origin**（pull 非裸库合法，只读对象库）；
  - **ben / jannie / paul / timothy / [面板机] = 只读消费机**，只有 pull 权；**交易机连 repo 都没有**（2026-09-11 起现行口径），部署产物由 qs_update_product / 面板 scp 推送。
- 个人机要写 asaph 的路径被物理隔断：push hope → 在 asaph 手动 pull（qs_csi 直接 pull；qs_etf/qs_com 要 `git fetch origin +refs/heads/<b>:refs/heads/<b>`）。
- **qs_update 只 pull 不 commit 的四层机制**：
  1. 单一真源原则——只有 hope（开发）与 asaph（运营）允许人工 commit，消费机 commit 会让每台机器长出本地分叉，真源被污染；
  2. 工作树混着生成物——local.cfg、client_port.list、expiry.list、四清单都是函数每次现算的产物，各机天然不同，进库等于把运行时快照当配置存；
  3. push 通路被仓库形态物理封死（见非裸规则），pull-only 不只是纪律；
  4. 人工 commit = 审计闸门，每次真源变更带作者与说明，高危检查（products 相邻行 grep、strategy ≤64）都卡在人工环节。
- `git_sync`（仅 asaph）：把共享注册表 products/servers 铺到另两个池分支并 commit——保证 qs_etf/qs_csi/qs_com 三支看到同一份端口/机器表。只 commit 不 push，消费机自己 pull。
- 坑：products 相邻行笔误会被 git_sync 铺到三分支——commit 前 grep 相关行人工过一遍（9/22 实录）。

## 二、qsmgr 的三层结构

- **qs_* 全是 bash 函数，不是脚本**（`type qs_update_product` 可验证）。`source qnet` 按链加载：`qcommon`（颜色/校验）→ `qdssh`（ssh/scp 封装，读 servers 注册表自动 ProxyJump）→ `qprdsrv`（servers/products 查询）→ `qopt` → `qsinstall`（部署核心：qs_gen_strategies_list_and_map ~L70 / qs_initialize_product ~L193 / qs_update_product ~L249）。
- 它们操作三类数据：
  - **注册表（受管，进 git）**：`products` 行五段 `产品名|服务器|路径|端口|scope`；`servers` 堡垒机 4 字段 `name|ip|port|user`、业务机 7 字段 `name|localhost|port|user|jumphost|realip|realport`；
  - **模板（受管，进 git）**：`data/base/` 的 backend.base、frontend、cfg 模板（内含 SCOPE 占位符）、bin 版本（`bin/curr`、`cfg/curr` 软链，必须指向同一版本否则 qs_update_product 拒绝执行）；
  - **生成物（不进 git）**：local.cfg、client_port.list、easy_manager.cfg、expiry.list、四清单——每次运行函数现算。
- **conf 是声明式 key=value，不是对象赋值**：`strategies=a,b,c` 声明本产品策略（顺序即序号）；`strategy.<名>=<ETF现货>,<对冲腿>` 声明标的映射（只有一段 = 无指数对冲腿）；`multipliers=` 乘数；`arbs=`/`arb.*=` 实例分配；`dict=` 字典路径（仅 etf/qs_stk_g1 有，含 `${TradeDate}` 运行时占位符）。
- **第二段同步规则**：conf 的 `server=` 决定 qs_update_product 推给谁；products 行第二段决定 qsj_ssh/qs_ssh 登录寻址、check_account_env 连谁、巡检推导谁。两处不一致 = 部署在 A 机、运维查 B 机——换机时两处同改。

## 三、池与四清单

- **池 = 单分支内单个 type 目录的产品集合**，口径 `products 表 ∩ data/type/<exch>/`（目录有文件但未注册的产品不进并集）。分支 ≠ 池：qs_etf 分支下有 **etf 和 qs_stk_g1 两个池**；qs_csi、qs_com 各一池；test_etf/test_csi 是独立测试池。
- **四清单 + fxrate.cfg**（strategy.list / strategy.map / ul.list / multiplier.list / fxrate.cfg）按**全池并集**生成，写进池内**每个**产品目录——因为 GUI 是全局单例，一次启动要认识全池所有策略才能连任意产品，目录内容是子集就连不上。
- 生成是**整份重写且排序输出**（字母序可证），不是追加。上限 **64 行**（C++ 硬限制，部署面板强制校验并显示 N/64）——新增大策略量产品前先算池并集。
- **端口体系**：products 行端口 = PortPrefix×100+1（如 288 → 28801）；客户端 centralizer 端口 = 299 + products 行号（`127.0.0.1:299XX`）。新行未注册时 qs_update_product 取现有最大值 +1 自动追加——端口自动分配防手工挑号冲突。
- **全量更新存在的根本原因**：新增/下线产品改变池，池内所有产品的四清单都要重生成——面板的"全量更新"按钮就是运维 for loop 的面板化。

## 四、部署动作的两条线

**服务端线**（asaph / 面板机 job → 产品机）：
`qs_update_product <type> <product>` = 读 conf → 查产品未运行 → 读目标机 uniq.cfg（证书身份）→ 校验本地 cfg/bin curr 一致 → **tar 打包 data/base → qdssh scp 推到 server= 那一台机** → sed 替换 SCOPE 占位符（同一份模板据此区分产品的进程名/日志/实例）→ 端口分配 → 生成服务端 local.cfg / arb_hosts.cfg / arb_<name> cfg + OidPrefix / arb 启动项 / expiry.list.sample → 收尾自动调 `qs_update_strategies`。推的是**打包 base**，不是 conf——conf 只在 asaph 上被读。

**客户端线**（交易机 / ben 本地）：
alias（qs_update_etf / etf_g1 / csi / com）= checkout 池分支 → `qs_update`（仅 git pull）→ `qs_update_client <type>` = 同步 base cfg/bin 软链 → 池并集写四清单 → 写 local.cfg → 依次调三个子函数：
- `qs_update_client_centralier_local_ports`——只重生成 client_port.list（端口表单点修复）；
- `qs_update_client_easy_manager`——只重生成 easy_manager.cfg；
- `qs_update_client_expiries`——ssh 到各产品服务器收集 expiry.list 写回（到期日变更的最小同步命令；依赖本机到产品机 SSH 免密）。
客户端侧不做任何 git 操作——用的是已 pull 下来的本地 qsmgr 副本。

**目录分工**：`sys/cfg/curr/` = 函数生成（共性），不可手改；`ext/` = 每机每产品差异（柜台凭据/行情源/到期/组合开关），手工编辑，经 inc= 链覆盖生成配置。

## 五、配置加载模型

- **XConfig ini 语义：后行覆盖前行**——同名 key 多次出现时最后一条生效，查配置用 `tail -1`（check-account-env 明确，dstl 的 CFFEX.O 前后两值案例）。
- **inc= 是 include 链**，链尾 `inc=./ext/postload.cfg` **最后加载、覆盖前面一切**——放每机覆盖项：tunnel 地址 / TradeDate / DictFile / 每策略 URL+Expiries / Combo.Enabled（=1 开组合策略）。
- **dict 声明的去向**：conf 的 `dict=...${TradeDate}_A.dic` 不在 local.cfg（local.cfg 只是骨架：StrategyList / local.PortPrefix / local.user / local.env）——展开进 postload.cfg 的 DictFile + TradeDate 段。
- **gw_src.cfg（柜台路由，xes 侧加载）**：`Exch.<所>.<U/O/F>.Name` 把各交易所的 U=Underlying 标的 / O=Option 期权 / F=Futures 期货 路由到网关；CFFEX 中金所、SHEX 上交所、SZEX 深交所、SHFE 上期所。`MockEs`（Type=MockOms）= 模拟柜台，`yd`（Type=YdEtf）= 真实 Yd 柜台；`SHEX.O=yd 其余 MockEs` = 只有上交所期权实盘。`Yd.yd.UserID/Password/AppID/AuthCode` 四件套 = 柜台凭据（api=yd 时 ydAPI.cfg 还要有 TradingServerIP）。
- **md_src.cfg（行情，mdadapter 加载）**：`Dms.Srcs=GlxFutCtp,yhctp,yhopctp` 声明三个源实例——yhopctp（OptCtp 期权链行情）、yhctp（StkCtp ETF 现货行情）、GlxFutCtp（FutCtp 期货/股指行情，对冲腿用）；URL/BrokerID/UserID/Password = CTP 前置四件套。mdadapter 收三路 → 归一 → 喂 **centralizer** → 全产品进程订阅。
- **expiry.list（curvefitting / arb / GUI 消费）**：`UsedExpiries=20261028,20261218` 定义在本文件第一行（变量）；`SelectedExpiries.<策略>.<标的>` 是**层级 key 命名约定**（策略×标的两维），`${UsedExpiries}` 是变量引用——所有策略共用一组到期，改一行全改。curvefitting 的 CFExpiry 按到期拟合 fwd/vol/greeks；arb 只交易/订阅所选到期；GUI T 型报价只画所选到期。

## 六、进程拓扑与参数体系

- 每个产品目录由 backend 脚本拉起九件套进程：centralizer、curvefitting、xparam、xdatabase、xrisk、xes、mdadapter、arbattr、arb_<name>。`./backend all|arb_etf|none`；公共函数 scripts/qs_common（start_one/kill_one/start_and_stop）。
- **xes = 柜台执行侧**（加载 gw_src.cfg，其日志 es.log 是 09:05 看 `front end connected` 的地方）；**行情是 mdadapter**，不是 xes。
- **xdatabase 参数三层优先级**：pmap 存档（上次运行快照）< **override.csv（启动权威值）** < 盘中运行态。启动时先读 pmap、再逐行 merge `OverrideCsv=pdatabase.override.csv`（见 cfg/curr/xdatabase_sh.cfg），同名参数 override 赢；**只在启动时读**——改完要 `./backend xdatabase` 重启单进程，日志 grep "will be override" 验证条数。
- **复制参数的正确姿势**（copy-strategy-params.md）：源必须选**老 override.csv**，不能选 pmap dump（含当日盘中改动，复制即参数漂移）；替换维度用 `|老stg|` 竖线锁定策略名段；重建用 head 截老段 + append 新段防重复叠加；改前 `cp override.csv override.csv.bak$(date +%m%d)`。runbook 里"复制更大的 csv"+`%s/hy06/hy05/g` 全局替换，与文档告诫有偏差。

## 七、daily/curr 时间轮转模型

- 软链指向目录完全合法——`curr` 是文件系统层的**日期指针**。
- 约定：每日一个 `daily/<YYYYMMDD>/`；**所有进程读写 `daily/curr/...`**（日志、Database/storage、pmap），换日只动 curr 一个链接，任何路径配置零改动。
- 生命周期：盘前 SOD 建/切当日目录 → 盘中进程写入 → EOD 落盘定格（account_eod / pmap）→ 次日 SOD 切新目录；**旧目录原样保留 = 回滚底牌**。
- 新产品**首日轮转**：`cd daily && mv curr 20260921 && ln -s 20260921 curr`——把种子（拷来的昨日数据）挂成部署日目录，让"今天"有合法的当日目录，次日 SOD 的 account_sod 对账（当日 SOD 账户 vs 种子 EOD）才有依据；这就是"数据种子"的意义（pmap 字节可不同属预期，**account_eod 必须 md5 一致**）。

## 八、调度体系（qs_jobs）

- **调度器不在 asaph**——asaph 只是 qs_jobs 的 git 中心仓库。调度器跑在：paul（A 机，单日）/ timothy（B 机，双日）A/B 轮值执行当日任务（运行身份 **tailer**）；jannie（master）跑 cron。
- **双开关模型**：qsmgr 的 conf/products 只影响部署与检查工具的寻址；**qs_jobs 的 `db/<产品>` 的 `server=` 才是调度开关**——SOD 启动、EOD 落盘、巡检（进程/隧道）、dict 推送全部 ssh 到 server= 那台机执行。调度器每 60s 热加载重读 tasks、执行时现读 db，改 server= 全链改向无需 restart。
- **auto_sod_eod**：=1 进自动盘前/盘后队列（08:52 fire 自动拉起整组引擎、15:05 自动 EOD）；=0 只能手动/面板触发。**phoenix（paul/timothy）惯例 = 0，master（jannie）多为 1——两边是刻意差异，严禁 merge**，从 jannie 拷 db 到 phoenix 记得改 0。
- **dict 任务链**：每日 08:15 / 08:40 / 08:43 三个时刻（汇集当日字典 → 按 db server= 名单推送 → 校验/补推），08:45 前在位；名单 = db 里 server= 写的机器。交易客户端不靠推送，主动 `get_dicts` 从 asaph 拉（dict 按交易日命名，缺当日 → GUI 空树 Qt 断言崩溃）。
- **新机接线四件**（方向别搞反）：servers 注册（qsmgr）；隧道 qs_jumpto（发起方 tailer 的本地端口→跳板→新机）；host key 进发起方 known_hosts（`[localhost]:<port>` 键名）；tailer 公钥进新机 authorized_keys。**验证免密必须以 tailer 身份**——abigail 通 ≠ tailer 通（9/23 实录）。

## 九、首跑盯盘时间线（次日语）

| 时刻 | 发生什么 | 在哪看 |
|------|----------|--------|
| 08:15/08:40/08:43 | dict 任务链推送当日字典到 db 名单机 | qs_jobs 面板任务日志 |
| 08:45 | dict 在位检查 | 产品机 `ls data/dict/` |
| 08:52 | A/B 当日轮值机 fire，产品机自动拉起整组引擎（读 daily/curr 种子） | 面板 fire 日志 |
| 09:05 | es.log `add ... connector` + `front end connected`；行情链 mdadapter→centralizer 通 | 产品机 es.log |
| 09:05+ | account_sod 与种子 EOD 对账（种子错 = 对账炸） | SOD 日志 |
| 盘中 | eyeball（michael:5000）实时 PnL/风控 | 浏览器 |
| 15:05 | EOD 落盘 account_eod/pmap 进当日目录，供次日对账 | 面板/产品机 |

## 十、红线与坑速查

- 禁止在个人机直接部署：必须 git push → asaph → 部署机 pull（qs_jobs 侧同构）。
- qs_jobs 只用 phoenix（A/B）/ master（jannie），严禁互相 merge；严禁切 qs_jobs master；严禁删 /opt/option/ 下文件、手改 monitor.db。
- cfg/curr 与 bin/curr 必须同版本；qs_update_product/qs_update_strategies 是函数非脚本；expiry 收集、部署 scp 都依赖 SSH 免密链。
- strategy.list ≤64 是硬上限；products 相邻行 commit 前 grep；override 源选 dump = 参数漂移；多产品同日变更 = 多个首跑叠加，逐个盯。
- 部署后体检：`check_account_env <产品>`（只读）核三要素 + conf.server 机器面；账号核对看 paul:5001 / timothy:5000 面板 /api/products。
