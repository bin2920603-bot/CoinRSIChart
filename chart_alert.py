import os, json, time, requests

OKX = "https://www.okx.com"
TOP_N = 100            # 거래대금 상위 몇 개를 볼지
LOW = 30               # RSI 30 기준선
NEAR_MIN = 25          # 🟡임박: RSI6이 이 값 이상 ~ 30 이하이고 올라오는 중
RSI_MAX = 40           # 🟢돌파: 뚫은 뒤 RSI6이 이 값 이하일 때만
LIVE_MIN_CHG = 0.5     # 🟢돌파: 이번 봉이 이 % 이상 올랐을 때만
RSI_N = 6              # RSI6
CHART_BARS = 80        # 사진에 그릴 봉 개수
MAX_ALERTS = 12        # 한 번 실행에 보낼 알림 최대 개수 (넘치면 다음 실행에 이어서)
VOL_AVG_BARS = 20
VOL_MIN_ELAPSED = 0.1
VOL_WEAK = 0.7
VOL_STRONG = 2.0
VOL_RISING = 1.5
BARS = [("1H", "1시간봉"), ("2H", "2시간봉"), ("4H", "4시간봉"), ("1D", "일봉")]
BAR_MS = {"1H": 3600000, "2H": 7200000, "4H": 14400000, "1D": 86400000}
STATE = "state/sent.json"


def get(path, params=None):
    r = requests.get(OKX + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()["data"]


def rsi(closes, n):
    if len(closes) < n + 2:
        return []
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    out = []
    for i in range(n, len(gains) + 1):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def ema(values, n):
    if len(values) < n + 1:
        return []
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    out = [e]
    for v in values[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def vol_info(cs, bar, now):
    """(직전 봉 대비 %, 최근 20봉 평균 대비 ×배). 진행중 봉은 봉 전체 길이로 환산."""
    try:
        cur = float(cs[-1][7])
        prev = float(cs[-2][7])
        dur = BAR_MS[bar]
        elapsed = now - int(cs[-1][0])
        if elapsed < dur * VOL_MIN_ELAPSED:
            return None, None
        cur = cur * dur / min(elapsed, dur)
        past = [float(x[7]) for x in cs[-1 - VOL_AVG_BARS:-1]]
        avg = sum(past) / len(past) if past else 0
        pct = (cur / prev - 1) * 100 if prev > 0 else None
        x = cur / avg if avg > 0 else None
        return pct, x
    except Exception:
        return None, None


def vol_text(pct, x):
    if x is None:
        return "거래량 - (봉이 막 시작해서 아직 계산 불가)"
    t = f"{'🔴' if (pct or 0) >= 0 else '🔵'}거래량 평균 ×{x:.1f}"
    if pct is not None:
        t += f" (직전 {pct:+.0f}%)"
    if x < VOL_WEAK:
        t += " ⚠️약함"
    elif x >= VOL_STRONG:
        t += " 🔥강함"
    elif x >= VOL_RISING and pct is not None and pct >= 0:
        t += " 📈늘어나는 중"
    return t


def make_chart(cs, closes, name, bar, kind, path):
    """캔들 + EMA7/20/50/200 + RSI6(30선) + 거래량 사진. 실패하면 None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        n = len(cs)
        idx = list(range(max(0, n - CHART_BARS), n))
        fig = plt.figure(figsize=(8, 7), facecolor="#0b0e11")
        gs = GridSpec(3, 1, height_ratios=[4, 1.4, 1.2], hspace=0.08)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        for ax in (ax1, ax2, ax3):
            ax.set_facecolor("#0b0e11")
            ax.tick_params(colors="#9aa0a6", labelsize=8)
            for sp in ax.spines.values():
                sp.set_color("#2a2e35")
            ax.grid(color="#1e2229", lw=0.5)
        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)

        lo_all, hi_all = None, None
        for i in idx:
            o, h, l, c = (float(cs[i][1]), float(cs[i][2]),
                          float(cs[i][3]), float(cs[i][4]))
            col = "#26a69a" if c >= o else "#ef5350"
            ax1.plot([i, i], [l, h], color=col, lw=1)
            body = max(abs(c - o), (h - l) * 0.02, 1e-12)
            ax1.bar(i, body, bottom=min(o, c), width=0.7, color=col)
            ax3.bar(i, float(cs[i][7]), width=0.7, color=col)
            lo_all = l if lo_all is None else min(lo_all, l)
            hi_all = h if hi_all is None else max(hi_all, h)

        for k, colr in ((7, "#c792ea"), (20, "#ffd54f"), (50, "#66bb6a"), (200, "#ef5350")):
            e = ema(closes, k)
            if not e:
                continue
            e = [None] * (n - len(e)) + e
            xs = [i for i in idx if e[i] is not None]
            if xs:
                ax1.plot(xs, [e[i] for i in xs], color=colr, lw=1.2, label=f"EMA{k}")
        ax1.legend(loc="upper left", fontsize=7, facecolor="#0b0e11",
                   edgecolor="#2a2e35", labelcolor="#cfd3d8", ncol=4)
        if lo_all is not None and hi_all > lo_all:
            m = (hi_all - lo_all) * 0.06
            ax1.set_ylim(lo_all - m, hi_all + m)

        r6 = rsi(closes, 6)
        r6 = [None] * (n - len(r6)) + r6
        xs = [i for i in idx if r6[i] is not None]
        ax2.plot(xs, [r6[i] for i in xs], color="#ffb74d", lw=1.3)
        ax2.axhline(30, color="#42a5f5", ls="--", lw=1)
        ax2.axhline(70, color="#42a5f5", ls="--", lw=0.8)
        ax2.set_ylim(0, 100)
        ax2.text(0.01, 0.82, "RSI6", transform=ax2.transAxes, color="#ffb74d", fontsize=8)
        ax3.text(0.01, 0.78, "Volume", transform=ax3.transAxes, color="#9aa0a6", fontsize=8)

        title = "RSI 30 NEAR" if kind == "near" else "RSI 30 CROSS"
        fig.suptitle(f"{name}  {bar}  -  {title}", color="#e8eaed", fontsize=12, y=0.93)
        fig.savefig(path, dpi=100, facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        return path
    except Exception:
        return None


def send_text(token, chat, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat, "text": text,
                                     "parse
