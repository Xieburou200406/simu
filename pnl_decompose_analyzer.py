#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pnl_decompose_analyzer.py
=========================
实现 orange_zone/ops/pnl-decompose.md §3 的「AI 侧」分析：拿到交易员从操作机
下载的 *.raw（Centralizer 日志行），出当日 PnL 归因结论。

设计铁律（来自文档 §1 末尾）：
  - 本脚本只做 §2（解析）+ §3（分析），**绝不**执行 §1 的 qsj/ssh/下载命令。
  - 输入就是交易员传过来的 *.raw 文件，不连任何服务器。
  - 只统计 09:30 及以后的行（09:30 之前是冷启动默认值）。

用法：
  python pnl_decompose_analyzer.py --raw hy02_gj_588000_20261009.raw \
                                   --acct hy02_gj_588000 \
                                   [--after 09:30] [--out report.txt]

输出：当日累计归因表 + rVegaPnl 闭环验证 + 10 分钟网格演进（亏损集中时段，可 --step 调粒度）
"""

import argparse
import re
import sys
from collections import defaultdict


# ---- 文档 §2：属性含义表（用于报告里的中文标注）-------------------------
ATTR_CN = {
    "rVegaPnl":        "Vega 敞口盈亏（vol 水平变动打的）",
    "rDeltaPnl":       "Delta 敞口盈亏（标的方向打的）",
    "rVegaSkewPnl":    "Smile/Skew 维度盈亏",
    "rVegaKtcPnl":     "Kurt Call 侧盈亏",
    "rVegaKtpPnl":     "Kurt Put 侧盈亏",
    "rBssPnl":         "基差（bss）盈亏",
    "rTradePnl":       "交易执行盈亏（做市成交赚的，成交才刷）",
    "rMtMPnlChg":      "MTM 口径当日总盈亏",
    "aPnlChg":         "引擎口径当日总盈亏（结果，不是原因）",
    # 敞口/市场（时序状态，用于闭环验证与网格）
    "aAccuVega":       "累计 Vega 敞口（负=空 vol）",
    "aAccuDelta":      "累计 Delta 敞口",
    "aAccuCashDelta":  "现金口径 Delta 敞口",
    "aAccuVegaKtC":    "Kurt Call 侧 Vega 敞口",
    "aAccuVegaKtP":    "Kurt Put 侧 Vega 敞口",
    "aAccuVegaSkw":    "Skew 侧 Vega 敞口",
    "cUsedVol":        "ATM vol（该账户定价用）",
    "cUsedFwd":        "合成远期（该账户定价用）",
}

# 需要算「首末差 = 当日累计」的属性
CUM_ATTRS = [
    "rVegaPnl", "rDeltaPnl", "rVegaSkewPnl", "rVegaKtcPnl",
    "rVegaKtpPnl", "rBssPnl", "rTradePnl", "rMtMPnlChg", "aPnlChg",
]


def bucket(t, step=5):
    """把 HH:MM 归到 step 分钟网格，如 step=5: 09:37 -> 09:35；step=10: 09:37 -> 09:30。"""
    hh, mm = t.split(":")
    return f"{hh}:{int(mm) // step * step:02d}"


def parse_raw(path, acct, after="09:30"):
    """
    返回:
      series: dict[attr] -> list[(time_str, value_float)]   （已按时间升序、已过滤账户与 09:30）
      vol_curve: dict[strike] -> list[(time_str, value_float)]  （O 级 cImpliedSmileVol）
    解析规则（文档 §2）：
      只看含 'publishing attr:' 的行；
      行: INFO <HH:MM:SS.ffffff> [pid]: publishing attr: <key> <19位时间戳> <值> (...)
      时间 = 第2字段前5位 HH:MM；值 = 倒数第1字段；key = 倒数第3字段（竖线分段）
      key 形如 E|<acct>|SHEX|588000.SH|...|-|<属性名>  或
               O|<acct>|SHEX|588000.SH|...|C|E|<行权价>|<数量><属性名>
    """
    series = defaultdict(list)
    vol_curve = defaultdict(list)
    # 仅收集 aAccuVega / cUsedVol 的完整时间戳事件流，供 §二 路径积分用（避免 HH:MM 削位丢精度）
    closure_events = []
    acct_pfx_e = f"E|{acct}|"
    acct_pfx_o = f"O|{acct}|"
    n_total = 0
    n_kept = 0

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "publishing attr:" not in line:
                continue
            n_total += 1
            parts = line.split()
            # 定位 attr:
            try:
                i = parts.index("attr:")
            except ValueError:
                continue
            if len(parts) < 6:
                continue
            key = parts[i + 1]
            # 值 = 倒数第 2 个字段；最后一个字段是来源定位 (CentralizerCore.cpp:92)
            # 文档 §2 写“倒数第1”，实际最后一个是括号来源，故取倒数第2。
            # 两种写法在 9 字段标准行上等价，但 O 级行有时多字段，倒数第2 更鲁棒。
            if parts[-1].startswith("("):
                value_str = parts[-2]
            else:
                value_str = parts[-1]
            time_str = parts[1][:5] if len(parts[1]) >= 5 else parts[1]
            # 时间过滤
            if time_str < after:
                continue
            # 账户过滤（字面匹配，竖线不是正则）
            if not (key.startswith(acct_pfx_e) or key.startswith(acct_pfx_o)):
                continue
            try:
                val = float(value_str)
            except ValueError:
                continue
            segs = key.split("|")
            n_kept += 1
            if segs[0] == "E":
                attr = segs[-1].lstrip("-")          # -rVegaPnl -> rVegaPnl
                series[attr].append((time_str, val))
                if attr in ("aAccuVega", "cUsedVol"):
                    # 保留完整时间戳（parts[1] = HH:MM:SS.ffffff），§二 按事件顺序积分
                    closure_events.append((parts[1], attr, val))
            elif segs[0] == "O":
                strike = segs[7]
                # cImpliedSmileVol 是隐含波动率，必须为正且 < 10（即 <1000%）；
                # 部分行格式异动会把别的字段误解析进来（如 -388 / 2947），直接丢弃
                if not (0.0 < val < 10.0):
                    continue
                vol_curve[strike].append((time_str, val))

    # 按时间升序（日志本就升序，保险起见排序）
    for k in series:
        series[k].sort(key=lambda x: x[0])
    for k in vol_curve:
        vol_curve[k].sort(key=lambda x: x[0])

    return series, vol_curve, n_total, n_kept, closure_events


def first_last(s):
    if not s:
        return None, None, None
    return s[0][1], s[-1][1], s[-1][1] - s[0][1]


def ascii_line_chart(vals, labels, height=12):
    """终端 ASCII 折线图：每列一个数据点，按其数值落在对应高度行画 #。"""
    if len(vals) < 2:
        return ["(数据点不足，跳过 ASCII 图)"]
    vmin, vmax = min(vals), max(vals)
    span = vmax - vmin
    if span < 1e-9:
        vmax += 1.0
        vmin -= 1.0
        span = vmax - vmin
    n = len(vals)
    colw = max(3, min(6, 72 // n))
    def row_of(v):
        return int(round((v - vmin) / span * (height - 1)))
    out = []
    for h in range(height - 1, -1, -1):
        yval = vmin + span * h / (height - 1)
        line = f"{yval:+9.1f} |"
        for v in vals:
            line += ("#" if row_of(v) == h else " ") + " " * (colw - 1)
        out.append(line)
    out.append(" " * 11 + "+" + "-" * (n * colw))
    step_lab = max(1, n // 12)
    xlab = " " * 12
    for i, l in enumerate(labels):
        xlab += (l if i % step_lab == 0 else "·") + " " * (colw - 1)
    out.append(xlab)
    return out


def ascii_bar_chart(deltas, labels, height=9):
    """终端 ASCII 柱状图：正向上、负向下，零轴在中间行。"""
    if len(deltas) < 2:
        return []
    mx = max(abs(min(deltas)), abs(max(deltas)), 1e-9)
    n = len(deltas)
    colw = max(3, min(5, 60 // n))
    mid = height // 2
    out = []
    for h in range(height - 1, -1, -1):
        line = ""
        for d in deltas:
            target = mid + int(round(d / mx * mid))
            line += ("#" if target == h else " ") + " " * (colw - 1)
        out.append(line)
    out.append(" " + "-" * (n * colw))
    step_lab = max(1, n // 12)
    xlab = " " * 2
    for i, l in enumerate(labels):
        xlab += (l if i % step_lab == 0 else "·") + " " * (colw - 1)
    out.append(xlab)
    out.append(f"(零轴第 {mid + 1} 行；# 向上=赚 向下=亏；峰值 {max(deltas):+.0f} / 谷值 {min(deltas):+.0f})")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="*.raw 文件路径")
    ap.add_argument("--acct", required=True, help="账户_标的，如 hy02_gj_588000")
    ap.add_argument("--after", default="09:30", help="只统计该时刻及之后的行，默认 09:30")
    ap.add_argument("--out", default=None, help="报告输出文件（默认打印到 stdout）")
    ap.add_argument("--step", type=int, default=10, help="网格粒度（分钟），默认 10")
    args = ap.parse_args()

    series, vol_curve, n_total, n_kept, closure_events = parse_raw(args.raw, args.acct, args.after)

    L = []
    p = L.append
    p("=" * 72)
    p(f"PnL 归因分析  |  账户 {args.acct}  |  统计起点 {args.after} 之后")
    p(f"原始行总数 {n_total}  |  命中本账户行 {n_kept}  |  涉及属性 {len(series)} 项")
    p("=" * 72)

    # ---- 1) 当日累计归因表（首末差）-----------------------------------
    p("\n【一、当日累计归因（各 r*Pnl 首末差）】")
    p(f"{'属性':<16}{'首值':>14}{'末值':>14}{'当日累计':>14}   说明")
    p("-" * 72)
    sum_dims = 0.0
    cum = {}
    apnl_f0 = apnl_f1 = None
    for attr in CUM_ATTRS:
        if attr not in series:
            continue
        f0, f1, diff = first_last(series[attr])
        cum[attr] = diff
        if attr not in ("rMtMPnlChg", "aPnlChg"):
            sum_dims += diff
        if attr == "aPnlChg":
            apnl_f0, apnl_f1 = f0, f1
        cn = ATTR_CN.get(attr, "")
        p(f"{attr:<16}{f0:>14.2f}{f1:>14.2f}{diff:>14.2f}   {cn}")

    # 六项归因合计 vs 总盈亏
    p("-" * 72)
    rmtm = cum.get("rMtMPnlChg", float("nan"))
    apnl = cum.get("aPnlChg", float("nan"))
    p(f"六项维度（不含 rMtM/aPnlChg）首末差之和 = {sum_dims:>12.2f}")
    p(f"rMtMPnlChg（MTM 总盈亏）        = {rmtm:>12.2f}")
    p(f"aPnlChg（引擎总盈亏）           = {apnl:>12.2f}")
    if not (lambda x: x != x)(rmtm):
        p(f"未列小项（rMtM − Σ六维）       = {rmtm - sum_dims:>12.2f}")
    # 防混淆：累计型账户的首/末/当日累计含义
    p("注：rMtMPnlChg / aPnlChg 是「累计型」账户（running PnL），首值≠0，含历史/隔夜基数。")
    p("    末值 = 收盘累计余额（即你屏幕看到的「总盈亏」）；当日累计 = 末−首 = 今日日内变动。")
    if apnl_f0 is not None:
        p(f"    例：aPnlChg 首 {apnl_f0:+.2f} → 今日 {cum.get('aPnlChg', 0):+.2f} → 末 {apnl_f1:+.2f}（末值即你屏幕看到的）。")
    # 主因判定
    p("\n主因（|当日累计| 最大的维度）：")
    ranked = sorted(
        [(a, cum[a]) for a in CUM_ATTRS if a in cum and a not in ("rMtMPnlChg", "aPnlChg")],
        key=lambda x: abs(x[1]), reverse=True,
    )
    for a, d in ranked[:3]:
        p(f"   {a:<16} {d:>12.2f}   {ATTR_CN.get(a,'')}")

    # ---- 2) rVegaPnl 闭环验证（路径积分法）-----------------------------
    p("\n【二、rVegaPnl 闭环验证：Σ aAccuVega×ΔcUsedVol（按事件顺序路径积分）】")
    if "aAccuVega" in series and "cUsedVol" in series and "rVegaPnl" in cum:
        # 路径积分：按原始事件顺序，每次 cUsedVol 更新时用当时最近的 aAccuVega 作 Vega_before
        evs = sorted(closure_events, key=lambda e: e[0])
        cur_vega = None
        prev_vol = None
        path_sum = 0.0
        n_steps = 0
        for _ts, kind, v in evs:
            if kind == "aAccuVega":
                cur_vega = v
            else:  # cUsedVol
                if cur_vega is not None and prev_vol is not None:
                    dvol = v - prev_vol
                    path_sum += cur_vega * dvol * 100.0   # ×100：decimal vol → 百分点；aAccuVega 单位=元/1%vol
                    n_steps += 1
                prev_vol = v
        rv = cum["rVegaPnl"]
        vg0 = series["aAccuVega"][0][1]
        vg1 = series["aAccuVega"][-1][1]
        vol0 = series["cUsedVol"][0][1]
        vol1 = series["cUsedVol"][-1][1]
        # 端点乘积法（对照：会把日内持仓变化混进比较，通常不闭环）
        prod_diff = (vg1 * vol1 - vg0 * vol0) * 100.0
        p(f"  aAccuVega 首 {vg0:+.2f} / 末 {vg1:+.2f}（日内由空转多时，端点乘积法失效）")
        p(f"  cUsedVol  首 {vol0*100:.2f}% / 末 {vol1*100:.2f}%（Δ = {(vol1-vol0)*100:+.2f} 百分点）")
        p(f"  路径积分 Σ Vega_before × Δvol×100 = {path_sum:.2f}  （共 {n_steps} 段 vol 变动）")
        p(f"  实际 rVegaPnl 首末差               = {rv:.2f}")
        p(f"  端点乘积法首末差（对照，不闭环）    = {prod_diff:+.2f}")
        if n_steps > 0:
            diff = path_sum - rv
            pct = diff / rv * 100 if rv != 0 else float("nan")
            p(f"  路径积分闭环偏差 = {diff:+.2f}（{pct:+.2f}%）")
            if abs(pct) <= 5:
                p("  ✓ 路径积分与 rVegaPnl 基本闭环（偏差 ≤ 5%）：vega 盈亏主要由 vol 路径上"
                  "『当时敞口 × vol 变动』解释；对照的端点乘积法偏差大，是因混入了日内持仓变化。")
            else:
                p("  ⚠ 路径积分与 rVegaPnl 偏差仍较大，可能仍有 vol 曲线非平行移动 / 非线性等未建模贡献。")
        p("  方法说明：端点乘积法（首末 aAccuVega×cUsedVol 之差）会把持仓变化也混进比较，故一般不闭环；")
        p("            正确做法是按事件顺序做路径积分（文档 §3 第2条『aAccuVega × cUsedVol 净变化』的严格实现）。")
    else:
        p("  缺少 aAccuVega / cUsedVol / rVegaPnl 序列，无法验证。")

    # ---- 3) 网格演进（可配粒度，默认 5 分钟）---------------------------
    p(f"\n【三、{args.step} 分钟网格演进（定位亏损集中时段）】")
    p("各因子列 = 该桶环比变动(Δ)；aPnlChg累计 = 每桶末真实累计余额（末行即收盘余额）。")
    grid_attrs = [a for a in ["rVegaPnl", "rDeltaPnl", "rBssPnl", "rTradePnl", "aPnlChg"]
                  if a in series]
    buckets = defaultdict(dict)  # bucket -> attr -> 该桶末值（累计值）
    for attr in grid_attrs:
        last_in_bucket = {}
        for t, v in series[attr]:
            b = bucket(t, args.step)
            last_in_bucket[b] = v
        for b, v in last_in_bucket.items():
            buckets[b][attr] = v
    # 显示列：各因子环比 + aPnlChg 累计余额
    disp = [(a, "delta") for a in grid_attrs]
    if "aPnlChg" in series:
        disp.append(("aPnlChg累计", "cum"))
    p(f"{'时段':<8}" + "".join(f"{lab:>14}" for lab, _ in disp))
    p("-" * (8 + 14 * len(disp)))
    prev = {a: None for a in grid_attrs}
    worst_bucket, worst_level = None, float("inf")
    worst_step_bucket, worst_step = None, 0.0
    for b in sorted(buckets):
        row = f"{b:<8}"
        cum_a = buckets[b].get("aPnlChg")
        for lab, kind in disp:
            if kind == "delta":
                a = lab
                v = buckets[b].get(a)
                if v is None or prev[a] is None:
                    row += f"{'':>14}"
                else:
                    d = v - prev[a]
                    row += f"{d:>+14.2f}"
                    if a == "aPnlChg":
                        if v < worst_level:
                            worst_bucket, worst_level = b, v
                        if prev[a] is not None and d < worst_step:
                            worst_step_bucket, worst_step = b, d
                if a in buckets[b]:
                    prev[a] = buckets[b][a]
            else:  # cum：直接显示该桶末累计值
                if cum_a is None:
                    row += f"{'':>14}"
                else:
                    row += f"{cum_a:>+14.2f}"
        p(row)
    if worst_bucket is not None:
        p(f"\n亏损最重时段（aPnlChg 累计最低 / 日内最大回撤）：{worst_bucket}  {worst_level:+.2f}")
    if worst_step_bucket is not None:
        p(f"单桶最大回落（aPnlChg 环比）：{worst_step_bucket}  {worst_step:+.2f}")
    if "aPnlChg" in series:
        p("说明：aPnlChg累计 列 = 每桶末真实累计盈亏（非环比）；末行 = §一「末值」"
          f"{apnl_f1:+.2f}（= 你屏幕看到的收盘余额）。首行(09:30 桶末)与 §一「首值」{apnl_f0:+.2f}"
          "（当日最早一帧）不同属正常——前者取该桶最后时刻读数，后者取当日第一帧。"
          "「累计最低」是该序列日内最低点，与末值之差即当日振幅。"
          f" 当日累计 {cum.get('aPnlChg', 0):+.2f} = 末值 − 首值 = 日内净变动，与累计序列首尾差一致。")

    # ---- 4) 累计盈亏 ASCII 走势 --------------------------------------
    if "aPnlChg" in series and len(buckets) >= 2:
        p("\n【四、累计盈亏 ASCII 走势（aPnlChg 运行余额，每点 = 一个网格桶）】")
        bl = sorted(buckets)
        cum_vals = [buckets[b]["aPnlChg"] for b in bl if "aPnlChg" in buckets[b]]
        if len(cum_vals) >= 2:
            p("· aPnlChg 累计余额折线（纵轴=盈亏，横轴=时间桶；末点=收盘余额）：")
            for ln in ascii_line_chart(cum_vals, bl):
                p(ln)
            deltas = [cum_vals[i] - cum_vals[i - 1] for i in range(1, len(cum_vals))]
            p("\n· 每桶 aPnlChg 环比柱（零轴在中间，上=赚 下=亏）：")
            for ln in ascii_bar_chart(deltas, bl[1:]):
                p(ln)

    # ---- 5) 逐行权价 vol 曲线（O 级，首末快照）------------------------
    if vol_curve:
        p("\n【五、逐行权价隐含 vol 曲线（O 级 cImpliedSmileVol，首/末快照）】")
        strikes = sorted(vol_curve.keys(), key=lambda x: float(x))
        p(f"{'行权价':<10}{'首值':>12}{'末值':>12}{'变动':>12}")
        p("-" * 46)
        for k in strikes:
            s = vol_curve[k]
            if not s:
                continue
            f0, f1, d = first_last(s)
            p(f"{k:<10}{f0:>12.4f}{f1:>12.4f}{d:>+12.4f}")

    p("\n" + "=" * 72)
    p("提示：以上数值单位与 eyeball 分钟表同量级，不同账户间可比。")
    p("=" * 72)

    report = "\n".join(L)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[已写出报告] {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
