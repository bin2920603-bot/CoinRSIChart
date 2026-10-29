import os, json, time, requests

OKX = "https://www.okx.com"
TOP_N = 100
LOOKBACK = 2
CHART_BARS = 80
MAX_ALERTS = 12
BARS = [("5m", "5분봉"), ("15m", "15분봉")]
STATE = "state/align.json"


def get(path, params=None):
    r = requests.get(OKX + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()["data"]


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


def full(values, n):
    e = ema(values, n)
    return [None] * (len(values) - len(e)) + e


def make_chart(cs, closes, name, label, kind, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        n = len(cs)
        idx = list(range(max(0, n - CHART_BARS), n))
        fig = plt.figure(figsize=(8, 6), facecolor="#0b0e11")
        gs = GridSpec(2, 1, height_ratios=[4, 1], hspace=0.08)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        for ax in (ax1, ax2):
            ax.set_facecolor("#0b0e11")
            ax.tick_params(colors="#9aa0a6", labelsize=8)
            for sp in ax.spines.values():
                sp.set_color("#2a2e35")
            ax.grid(color="#1e2229", lw=0.5)
        plt.setp(ax1.get_xticklabels(), visible=False)

        lo_all, hi_all = None, None
        for i in idx:
            o, h, l, c = (float(cs[i][1]), float(cs[i][2]),
                          float(cs[i][3]), float(cs[i][4]))
            col = "#26a69a" if c >= o else "#ef5350"
            ax1.plot([i, i], [l, h], color=col, lw=1)
            body = max(abs(c - o), (h - l) * 0.02, 1e-12)
            ax1.bar(i, body, bottom=min(o, c), width=0.7, color=col)
            ax2.bar(i, float(cs[i][7]), width=0.7, color=col)
            lo_all = l if lo_all is None else min(lo_all, l)
            hi_all = h if hi_all is None else max(hi_all, h)

        for k, colr in ((7, "#c792ea"), (20, "#ffd54f"), (50, "#66bb6a"), (200, "#ef5350")):
            e = full(closes, k)
            xs = [i for i in idx if e[i] is not None]
            if xs:
                ax1.plot(xs, [e[i] for i in xs], color=colr, lw=1.4, label="EMA" + str(k))
        ax1.legend(loc="upper left", fontsize=7, facecolor="#0b0e11",
                   edgecolor="#2a2e35", labelcolor="#cfd3d8", ncol=4)
        if lo_all is not None and hi_all > lo_all:
            m = (hi_all - lo_all) * 0.06
            ax1.set_ylim(lo_all - m, hi_all + m)

        title = "BULL ALIGNMENT" if kind == "bull" else "BEAR ALIGNMENT"
        fig.suptitle(name + "  " + label + "  -  " + title, color="#e8eaed", fontsize=12, y=0.95)
        fig.savefig(path, dpi=100, facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        return path
    except Exception:
        return None


def send_text(token, chat, text):
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    requests.post(url, data={"chat_id": chat, "text": text}, timeout=15)


def send_photo(token, chat, path, caption):
    url = "https://api.telegram.org/bot" + token + "/sendPhoto"
    try:
        with open(path, "rb") as f:
            r = requests.post(url, data={"chat_id": chat, "caption": caption},
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
        send_text(token, chat, "✅ 정배열/역배열 알림이 켜졌어요. 5분봉·15분봉에서 막 바뀐 코인을 차트로 알려 드려요.")

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
            cs = [x for x in c if x[8] == "1"][::-1]
            if len(cs) < 210:
                continue
            closes = [float(x[4]) for x in cs]
            e7 = full(closes, 7)
            e20 = full(closes, 20)
            e50 = full(closes, 50)
            e200 = full(closes, 200)
            n = len(cs)
            state = [0] * n
            for i in range(n):
                if e200[i] is None:
                    continue
                if e7[i] > e20[i] > e50[i] > e200[i]:
                    state[i] = 1
                elif e7[i] < e20[i] < e50[i] < e200[i]:
                    state[i] = -1

            hit = None
            for i in range(n - 1, n - 1 - LOOKBACK, -1):
                if i < 1 or e200[i - 1] is None:
                    continue
                if state[i] != 0 and state[i] != state[i - 1]:
                    hit = i
                    break
            if hit is None:
                continue

            kind = "bull" if state[hit] == 1 else "bear"
            key = inst + "|" + bar + "|" + kind
            if sent.get(key) == cs[hit][0]:
                continue

            head = "🟢 " + name + " · " + label + " · 정배열 시작" if kind == "bull" \
                else "🔴 " + name + " · " + label + " · 역배열 시작"
            png = make_chart(cs, closes, name, label, kind, "/tmp/" + name + "_" + bar + ".png")
            if png:
                send_photo(token, chat, png, head)
            else:
                send_text(token, chat, head)
            sent[key] = cs[hit][0]
            count += 1
            time.sleep(1)

    keep = {}
    for k, v in sent.items():
        try:
            if int(v) > now - 2 * 86400000:
                keep[k] = v
        except Exception:
            pass
    os.makedirs("state", exist_ok=True)
    json.dump(keep, open(STATE, "w"))


if __name__ == "__main__":
    main()
