import os, json, time, requests

OKX = "https://www.okx.com"
NL = chr(10)           # 줄바꿈
TOP_N = 100
LOW = 30
NEAR_MIN = 25
RSI_MAX = 40
LIVE_MIN_CHG = 0.5
RSI_N = 6
CHART_BARS = 80
MAX_ALERTS = 12
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
    t = ("🔴" if (pct or 0) >= 0 else "🔵") + "거래량 평균 ×" + format(x, ".1f")
    if pct is not None:
        t += " (직전 " + format(pct, "+.0f") + "%)"
    if x < VOL_WEAK:
        t += " ⚠️약함"
    elif x >= VOL_STRONG:
        t += " 🔥강함"
    elif x >= VOL_RISING and pct is not None and pct >= 0:
        t += " 📈늘어나는 중"
    return t


def make_chart(cs, closes, name, bar, kind, path):
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
                ax1.plot(xs, [e[i] for i in xs], color=colr, lw=1.2, label="EMA" + str(k))
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
        fig.suptitle(name + "  " + bar + "  -  " + title, color="#e8eaed", fontsize=12, y=0.93)
        fig.savefig(path, dpi=100, facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        return path
    except Exception:
        return None


def send_text(token, chat, text):
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat, "text": text,
                                     "parse_mode": "HTML"}, timeout=15)
        if r.status_code == 200:
            return
    except Exception:
        pass
    plain = text.replace("<b>", "").replace("</b>", "")
    requests.post(url, data={"chat_id": chat, "text": plain}, timeout=15)


def send_photo(token, chat, path, caption):
    url = "https://api.telegram.org/bot" + token + "/sendPhoto"
    try:
        with open(path, "rb") as f:
            r = requests.post(url, data={"chat_id": chat, "caption": caption[:1000],
                                         "parse_mode": "HTML"},
                              files={"photo": f}, timeout=30)
        if r.status_code == 200:
            return
    except Exception:
        pass
    send_text(token, chat, caption)


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    first = not os.path.exists(STATE)
    sent = {} if first else json.load(open(STATE))
    now = int(time.time() * 1000)

    rows = []
    for t in get("/api/v5/market/tickers", {"instType": "SWAP"}):
        if not t["instId"].endswith("-USDT-SWAP"):
            continue
        try:
            rows.append((float(t["volCcy24h"]) * float(t["last"]), t["instId"]))
        except ValueError:
            pass
    rows.sort(reverse=True)

    count = 0
    if first:
        send_text(token, chat, "✅ RSI차트알림이 켜졌어요. 🟡30임박·🟢30돌파 코인이 나오면 차트 사진으로 알려 드려요.")

    for vol, inst in rows[:TOP_N]:
        if count >= MAX_ALERTS:
            break
        name = inst.replace("-USDT-SWAP", "")
        for bar, label in BARS:
            if count >= MAX_ALERTS:
                break
            time.sleep(0.15)
            try:
                c = get("/api/v5/market/candles",
                        {"instId": inst, "bar": bar, "limit": "300"})
            except Exception:
                continue
            if not c or c[0][8] != "0":
                continue
            live = c[0]
            done = [x for x in c if x[8] == "1"][::-1]
            if len(done) < 30:
                continue
            cs = done + [live]
            closes = [float(x[4]) for x in cs]
            r = rsi(closes, RSI_N)
            if len(r) < 2:
                continue
            now_r, prev_r = r[-1], r[-2]
            o = float(live[1])
            chg = (closes[-1] / o - 1) * 100 if o else 0

            kind = None
            if prev_r <= LOW < now_r <= RSI_MAX and chg >= LIVE_MIN_CHG:
                kind = "cross"
            elif NEAR_MIN <= now_r <= LOW and now_r > prev_r:
                kind = "near"
            if not kind:
                continue

            key = inst + "|" + bar + "|" + kind
            if sent.get(key) == live[0]:
                continue

            vp, vx = vol_info(cs, bar, now)
            head = "🟡 RSI 30 임박 (아직 안 뚫음)" if kind == "near" else "🟢 RSI 30 돌파"
            cap = (head + NL + "<b>▶ " + name + "</b> · " + label + "·진행중" + NL
                   + "RSI6 " + format(prev_r, ".1f") + " → " + format(now_r, ".1f") + NL
                   + vol_text(vp, vx))
            png = make_chart(cs, closes, name, bar, kind, "/tmp/" + name + "_" + bar + "_" + kind + ".png")
            if png:
                send_photo(token, chat, png, cap)
            else:
                send_text(token, chat, cap)
            sent[key] = live[0]
            count += 1
            time.sleep(1)

    keep = {}
    for k, v in sent.items():
        try:
            if int(v) > now - 3 * 86400000:
                keep[k] = v
        except Exception:
            pass
    os.makedirs("state", exist_ok=True)
    json.dump(keep, open(STATE, "w"))


if __name__ == "__main__":
    main()
