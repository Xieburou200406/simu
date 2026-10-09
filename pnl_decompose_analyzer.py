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

输出：当日累计归因表 + rVegaPnl 闭环验证 + 10 分钟网格演进（亏损集中时段）
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


def bucket10(t):
    """把 HH:MM 归到 10 分钟网格，如 09:37 -> 09:30，14:02 -> 14:00。"""
    hh, mm = t.split(":")
    return f"{hh}:{int(mm) // 10 * 10:02d}"


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
            if i + 3 >= len(parts):
                continue
            key = parts[i + 1]
            # attr: 之后依次是 key(第1)、19位时间戳(第2)、值(第3)，再之后是 (CentralizerCore.cpp:92)
            # 因此值 = parts[i+3]，不是 parts[-1]
            if i + 3 >= len(parts):
                continue
            value_str = parts[i + 3]
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
            elif segs[0] == "O":
                strike = segs[7]
                # 末段形如 10000cImpliedSmileVol，属性名统一记 cImpliedSmileVol
                vol_curve[strike].append((time_str, val))

    # 按时间升序（日志本就升序，保险起见排序）
    for k in series:
        series[k].sort(key=lambda x: x[0])
    for k in vol_curve:
        vol_curve[k].sort(key=lambda x: x[0])

    return series, vol_curve, n_total, n_kept


def first_last(s):
    if not s:
        return None, None, None
    return s[0][1], s[-1][1], s[-1][1] - s[0][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="*.raw 文件路径")
    ap.add_argument("--acct", required=True, help="账户_标的，如 hy02_gj_588000")
    ap.add_argument("--after", default="09:30", help="只统计该时刻及之后的行，默认 09:30")
    ap.add_argument("--out", default=None, help="报告输出文件（默认打印到 stdout）")
    args = ap.parse_args()

    series, vol_curve, n_total, n_kept = parse_raw(args.raw, args.acct, args.after)

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
    for attr in CUM_ATTRS:
        if attr not in series:
            continue
        f0, f1, diff = first_last(series[attr])
        cum[attr] = diff
        if attr not in ("rMtMPnlChg", "aPnlChg"):
            sum_dims += diff
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
    # 主因判定
    p("\n主因（|当日累计| 最大的维度）：")
    ranked = sorted(
        [(a, cum[a]) for a in CUM_ATTRS if a in cum and a not in ("rMtMPnlChg", "aPnlChg")],
        key=lambda x: abs(x[1]), reverse=True,
    )
    for a, d in ranked[:3]:
        p(f"   {a:<16} {d:>12.2f}   {ATTR_CN.get(a,'')}")

    # ---- 2) rVegaPnl 闭环验证 -----------------------------------------
    p("\n【二、rVegaPnl 闭环验证：aAccuVega × ΔcUsedVol 】")
    if "aAccuVega" in series and "cUsedVol" in series:
        _, vg1, _ = first_last(series["aAccuVega"])
        _, vol1, dvol = first_last(series["cUsedVol"])
        # 用日均敞口（首末均值）近似
        vg0, _, _ = first_last(series["aAccuVega"])
        vg_mean = (vg0 + vg1) / 2.0
        # aAccuVega 单位=元/波动点（1 波动点=1%=0.01）；vol 净变动换算成波动点数
        vol_pts = dvol / 0.01
        est = vg_mean * vol_pts
        rv = cum.get("rVegaPnl", float("nan"))
        p(f"  aAccuVega 首 {vg0:.2f} / 末 {vg1:.2f}（日均 {vg_mean:.2f}）")
        p(f"  cUsedVol  首 {series['cUsedVol'][0][1]:.4f} / 末 {vol1:.4f}  →  Δvol = {dvol:+.4f}（{vol_pts:+.1f} 波动点）")
        p(f"  估算 vega 盈亏 ≈ 日均敞口 × 波动点数 = {est:.2f}")
        p(f"  实际 rVegaPnl 首末差            = {rv:.2f}")
        if not (lambda x: x != x)(rv):
            p(f"  偏差 = {est - rv:.2f}  （量级一致即对上，文档实例 -150×9≈-1370 对 -1378）")
    else:
        p("  缺少 aAccuVega 或 cUsedVol 序列，无法验证。")

    # ---- 3) 10 分钟网格演进 -------------------------------------------
    p("\n【三、10 分钟网格演进（定位亏损集中时段）】")
    grid_attrs = ["rVegaPnl", "rDeltaPnl", "rBssPnl", "rTradePnl", "aPnlChg"]
    grid_attrs = [a for a in grid_attrs if a in series]
    buckets = defaultdict(dict)  # bucket -> attr -> 该桶末值
    for attr in grid_attrs:
        last_in_bucket = {}
        for t, v in series[attr]:
            b = bucket10(t)
            last_in_bucket[b] = v
        for b, v in last_in_bucket.items():
            buckets[b][attr] = v
    p(f"{'时段':<8}" + "".join(f"{a:>14}" for a in grid_attrs))
    p("-" * (8 + 14 * len(grid_attrs)))
    prev = {a: None for a in grid_attrs}
    worst_bucket, worst_bucket_drop = None, 0.0
    for b in sorted(buckets):
        row = f"{b:<8}"
        bucket_drop = 0.0
        for a in grid_attrs:
            v = buckets[b].get(a)
            if v is None or prev[a] is None:
                row += f"{'':>14}"
                continue
            d = v - prev[a]
            row += f"{d:>+14.2f}"
            if a == "aPnlChg":
                bucket_drop += d
        p(row)
        if bucket_drop < worst_bucket_drop:
            worst_bucket, worst_drop = b, bucket_drop
        prev = {a: buckets[b].get(a, (prev[a] if prev[a] is not None else None)) for a in grid_attrs}
        # 用当前桶末值推进 prev
        for a in grid_attrs:
            if a in buckets[b]:
                prev[a] = buckets[b][a]
    if worst_bucket is not None:
        p(f"\n亏损最重时段：{worst_bucket}（aPnlChg 环比 {worst_drop:+.2f}）")

    # ---- 4) 逐行权价 vol 曲线（O 级，首末快照）------------------------
    if vol_curve:
        p("\n【四、逐行权价隐含 vol 曲线（O 级 cImpliedSmileVol，首/末快照）】")
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
