L, H, W = 2.20, 2.40, 0.20
PMIN, PMAX = 2.00, 2.60
VMIN, VMAX = -0.20, 0.20

positions = [
    ("牛市认购 Bull Call", "bull_call", 0.04, 30,  70),
    ("牛市认沽 Bull Put",  "bull_put",  0.02, 360, 70),
    ("熊市认购 Bear Call", "bear_call", 0.04, 30,  305),
    ("熊市认沽 Bear Put",  "bear_put",  0.12, 360, 305),
]

def payoff(kind, S, net):
    if kind == "bull_call": return max(S-L,0)-max(S-H,0)-net
    if kind == "bull_put":  return net-(max(H-S,0)-max(L-S,0))
    if kind == "bear_call": return net-(max(S-L,0)-max(S-H,0))
    if kind == "bear_put":  return (max(H-S,0)-max(L-S,0))-net

def be(kind, net):
    return (L+net) if kind in ("bull_call","bear_call") else (H-net)

svg = []
svg.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 545" width="100%" font-family="-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif" role="img">')
svg.append('<title>垂直价差四大策略到期损益图</title>')
svg.append('<desc>四个子图分别展示牛市认购、牛市认沽、熊市认购、熊市认沽的到期损益曲线，横轴为到期标的价格，纵轴为损益，标注了最大盈利、最大亏损与盈亏平衡点。</desc>')
svg.append('<rect width="680" height="545" fill="#f5f7fa"/>')
svg.append('<text x="340" y="34" text-anchor="middle" font-size="18" font-weight="500" fill="#1f2933">垂直价差四大策略 · 到期损益图（统一取 低K=2.20, 高K=2.40, 翼宽=0.20）</text>')

padx, pady = 45, 35
plotw, ploth = 220, 140

for (title, kind, net, cx, cy) in positions:
    ox = cx + padx
    oy = cy + pady
    svg.append(f'<rect x="{cx}" y="{cy}" width="310" height="200" rx="10" fill="#ffffff" stroke="#d9e2ec"/>')
    svg.append(f'<text x="{cx+15}" y="{cy+22}" font-size="14" font-weight="500" fill="#102a43">{title}</text>')
    y0 = oy + ploth - (0-VMIN)/(VMAX-VMIN)*ploth
    svg.append(f'<line x1="{ox}" y1="{y0}" x2="{ox+plotw}" y2="{y0}" stroke="#9aa5b1" stroke-width="1"/>')
    xL = ox + (L-PMIN)/(PMAX-PMIN)*plotw
    xH = ox + (H-PMIN)/(PMAX-PMIN)*plotw
    for x, lab, val in ((xL,"低K",L),(xH,"高K",H)):
        svg.append(f'<line x1="{x:.1f}" y1="{oy}" x2="{x:.1f}" y2="{oy+ploth}" stroke="#cbd2d9" stroke-dasharray="3,3"/>')
        svg.append(f'<text x="{x:.1f}" y="{oy+ploth+14}" text-anchor="middle" font-size="10" fill="#627d98">{lab} {val:.2f}</text>')
    xs = [PMIN, L, be(kind,net), H, PMAX]
    pts = " ".join(f'{ox+(p-PMIN)/(PMAX-PMIN)*plotw:.1f},{oy+ploth-(payoff(kind,p,net)-VMIN)/(VMAX-VMIN)*ploth:.1f}' for p in xs)
    col = "#2563eb" if kind in ("bull_call","bear_put") else "#0e9f6e"
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5"/>')
    xb = ox+(be(kind,net)-PMIN)/(PMAX-PMIN)*plotw
    svg.append(f'<circle cx="{xb:.1f}" cy="{y0:.1f}" r="3.5" fill="#e8590c"/>')
    if kind in ("bull_call","bear_put"):
        ml, mp = net, W-net
    else:
        mp, ml = net, W-net
    ymp = oy+ploth-(mp-VMIN)/(VMAX-VMIN)*ploth
    yml = oy+ploth-(ml-VMIN)/(VMAX-VMIN)*ploth
    svg.append(f'<text x="{ox+plotw-4}" y="{ymp-4:.1f}" text-anchor="end" font-size="10" fill="#2f855a">最大盈利 {mp:.2f}</text>')
    svg.append(f'<text x="{ox+plotw-4}" y="{yml+12:.1f}" text-anchor="end" font-size="10" fill="#c53030">最大亏损 {ml:.2f}</text>')
    svg.append(f'<text x="{xb:.1f}" y="{y0-8:.1f}" text-anchor="middle" font-size="10" fill="#e8590c">BE {be(kind,net):.2f}</text>')
    netlab = f'{"借方" if kind in ("bull_call","bear_put") else "贷方"} {net:.2f}'
    svg.append(f'<text x="{cx+15}" y="{cy+38}" font-size="11" fill="#486581">净头寸：{netlab}　翼宽：{W:.2f}（=最大盈利+最大亏损）</text>')

svg.append('<text x="340" y="532" text-anchor="middle" font-size="11" fill="#627d98">注：为统一对比四图均取 低K=2.20 / 高K=2.40；表中牛市认沽的 2.32 对应另一组行权价(高K≈2.34)，公式「高K−贷方」不变。</text>')
svg.append('</svg>')
out = "\n".join(svg)
print(out)
with open("C:/Users/abigail/WorkBuddy/2026-09-23-13-55-59/spreads.svg","w") as f:
    f.write(out)
