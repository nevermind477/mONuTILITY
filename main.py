import curses
import time
import threading
import platform
import os
import sys
import socket
from collections import deque
from datetime import datetime

try:
    import psutil
except ImportError:
    print("Требуется psutil: pip install psutil")
    sys.exit(1)

if platform.system() == "Windows":
    try:
        import curses
    except ImportError:
        print("На Windows дополнительно: pip install windows-curses")
        sys.exit(1)

APP_NAME    = "mONuTILITY v1.0"
REFRESH_S   = 0.8
HISTORY_LEN = 60

TABS = ["Обзор", "CPU", "Память", "Диски", "Сеть"]

C_TITLE   = 1
C_GOOD    = 2
C_WARN    = 3
C_CRIT    = 4
C_BORDER  = 5
C_HEAD    = 6
C_DIM     = 7
C_ACCENT  = 8
C_TAB_ACT = 9
C_TAB_IN  = 10
C_NET_UP  = 11
C_NET_DN  = 12
C_WHITE   = 13


class SystemData:

    def __init__(self):
        self.lock = threading.Lock()

        self.cpu_total   = 0.0
        self.cpu_cores   = []
        self.cpu_freq    = None
        self.cpu_count   = psutil.cpu_count(logical=True)
        self.cpu_phys    = psutil.cpu_count(logical=False) or 1
        self.cpu_history = deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN)

        self.ram        = None
        self.swap       = None
        self.disks      = []

        self.net_sent   = 0
        self.net_recv   = 0
        self.net_sent_s = 0.0
        self.net_recv_s = 0.0
        self._prev_net  = psutil.net_io_counters()
        self._prev_time = time.time()

        self.temps      = {}
        self.top_procs  = []
        self.battery    = None

        self.hostname   = socket.gethostname()
        self.os_name    = f"{platform.system()} {platform.release()}"
        self.uptime_s   = 0

        self._stop_evt  = threading.Event()
        self._thread    = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_evt.is_set():
            self._collect()
            self._stop_evt.wait(REFRESH_S)

    def _collect(self):
        now = time.time()

        cpu_t = psutil.cpu_percent(interval=None)
        cores = psutil.cpu_percent(interval=None, percpu=True)
        try:
            freq = psutil.cpu_freq()
        except Exception:
            freq = None

        ram  = psutil.virtual_memory()
        swap = psutil.swap_memory()

        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "dev":   part.device,
                    "mount": part.mountpoint,
                    "fs":    part.fstype,
                    "total": usage.total,
                    "used":  usage.used,
                    "free":  usage.free,
                    "pct":   usage.percent,
                })
            except (PermissionError, OSError):
                pass

        net = psutil.net_io_counters()
        dt  = now - self._prev_time if now != self._prev_time else 1
        sent_s = (net.bytes_sent - self._prev_net.bytes_sent) / dt
        recv_s = (net.bytes_recv - self._prev_net.bytes_recv) / dt
        self._prev_net  = net
        self._prev_time = now

        temps = {}
        try:
            raw = psutil.sensors_temperatures()
            if raw:
                for name, entries in raw.items():
                    for e in entries:
                        lbl = e.label or name
                        temps[lbl] = e.current
        except (AttributeError, Exception):
            pass

        top = []
        try:
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
                try:
                    procs.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            top = sorted(procs, key=lambda x: x.get('cpu_percent', 0) or 0, reverse=True)[:8]
        except Exception:
            pass

        battery = None
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, Exception):
            pass

        try:
            uptime_s = int(time.time() - psutil.boot_time())
        except Exception:
            uptime_s = 0

        with self.lock:
            self.cpu_total  = cpu_t
            self.cpu_cores  = cores
            self.cpu_freq   = freq
            self.cpu_history.append(cpu_t)
            self.ram        = ram
            self.swap       = swap
            self.disks      = disks
            self.net_sent   = net.bytes_sent
            self.net_recv   = net.bytes_recv
            self.net_sent_s = sent_s
            self.net_recv_s = recv_s
            self.temps      = temps
            self.top_procs  = top
            self.battery    = battery
            self.uptime_s   = uptime_s

    def snapshot(self):
        with self.lock:
            return {
                "cpu_total":  self.cpu_total,
                "cpu_cores":  list(self.cpu_cores),
                "cpu_freq":   self.cpu_freq,
                "cpu_count":  self.cpu_count,
                "cpu_phys":   self.cpu_phys,
                "cpu_history":list(self.cpu_history),
                "ram":        self.ram,
                "swap":       self.swap,
                "disks":      list(self.disks),
                "net_sent":   self.net_sent,
                "net_recv":   self.net_recv,
                "net_sent_s": self.net_sent_s,
                "net_recv_s": self.net_recv_s,
                "temps":      dict(self.temps),
                "top_procs":  list(self.top_procs),
                "battery":    self.battery,
                "hostname":   self.hostname,
                "os_name":    self.os_name,
                "uptime_s":   self.uptime_s,
            }

    def stop(self):
        self._stop_evt.set()


def setup_colors():
    curses.start_color()
    curses.use_default_colors()

    def p(n, fg, bg=-1):
        curses.init_pair(n, fg, bg)

    p(C_TITLE,   curses.COLOR_CYAN,    -1)
    p(C_GOOD,    curses.COLOR_GREEN,   -1)
    p(C_WARN,    curses.COLOR_YELLOW,  -1)
    p(C_CRIT,    curses.COLOR_RED,     -1)
    p(C_BORDER,  curses.COLOR_BLUE,    -1)
    p(C_HEAD,    curses.COLOR_MAGENTA, -1)
    p(C_DIM,     curses.COLOR_WHITE,   -1)
    p(C_ACCENT,  curses.COLOR_CYAN,    -1)
    p(C_TAB_ACT, curses.COLOR_BLACK,   curses.COLOR_CYAN)
    p(C_TAB_IN,  curses.COLOR_CYAN,    -1)
    p(C_NET_UP,  curses.COLOR_GREEN,   -1)
    p(C_NET_DN,  curses.COLOR_MAGENTA, -1)
    p(C_WHITE,   curses.COLOR_WHITE,   -1)


def color(pair):
    return curses.color_pair(pair)


def pct_color(pct):
    if pct >= 85:
        return color(C_CRIT) | curses.A_BOLD
    if pct >= 60:
        return color(C_WARN)
    return color(C_GOOD)


def bar(pct, width=20, filled='█', empty='░'):
    n = int(pct / 100 * width)
    n = max(0, min(n, width))
    return filled * n, empty * (width - n)


def fmt_bytes(b, speed=False):
    suffix = "/s" if speed else ""
    for unit in ("B", "K", "M", "G", "T"):
        if abs(b) < 1024:
            return f"{b:6.1f}{unit}{suffix}"
        b /= 1024
    return f"{b:6.1f}P{suffix}"


def fmt_uptime(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}ч {m:02d}м {sec:02d}с"
    return f"{m}м {sec:02d}с"


def safe_addstr(win, y, x, text, attr=0):
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        avail = w - x
        if avail <= 0:
            return
        win.addstr(y, x, text[:avail], attr)
    except curses.error:
        pass


def draw_box(win, y, x, h, w, title="", color_pair=C_BORDER):
    attr = color(color_pair)
    try:
        win.attron(attr)
        win.addch(y,     x,     curses.ACS_ULCORNER)
        win.addch(y,     x+w-1, curses.ACS_URCORNER)
        win.addch(y+h-1, x,     curses.ACS_LLCORNER)
        win.addch(y+h-1, x+w-1, curses.ACS_LRCORNER)
        for i in range(1, w-1):
            win.addch(y,     x+i, curses.ACS_HLINE)
            win.addch(y+h-1, x+i, curses.ACS_HLINE)
        for i in range(1, h-1):
            win.addch(y+i, x,     curses.ACS_VLINE)
            win.addch(y+i, x+w-1, curses.ACS_VLINE)
        win.attroff(attr)
    except curses.error:
        pass
    if title:
        t = f" {title} "
        safe_addstr(win, y, x+2, t, color(C_TITLE) | curses.A_BOLD)


def draw_bar_row(win, y, x, label, pct, width=22):
    filled_s, empty_s = bar(pct, width)
    attr_bar   = pct_color(pct)
    attr_label = color(C_DIM)
    attr_empty = color(C_BORDER)

    safe_addstr(win, y, x, f"{label:<12}", attr_label)
    safe_addstr(win, y, x+12, "[", color(C_BORDER))
    safe_addstr(win, y, x+13, filled_s, attr_bar)
    safe_addstr(win, y, x+13+width, empty_s, attr_empty)
    safe_addstr(win, y, x+13+width, "]", color(C_BORDER))
    pct_str = f" {pct:5.1f}%"
    safe_addstr(win, y, x+14+width, pct_str, attr_bar)


def draw_sparkline(win, y, x, data, width, max_val=100):
    BLOCKS = " ▁▂▃▄▅▆▇█"
    pts = list(data)[-width:]
    for i, v in enumerate(pts):
        ratio = v / max_val if max_val else 0
        idx   = int(ratio * (len(BLOCKS)-1))
        idx   = max(0, min(idx, len(BLOCKS)-1))
        ch    = BLOCKS[idx]
        attr  = pct_color(v)
        safe_addstr(win, y, x+i, ch, attr)


_anim_frame = 0


def draw_header(win, data, tick):
    global _anim_frame
    h, w = win.getmaxyx()

    pulse = [color(C_ACCENT) | curses.A_BOLD,
             color(C_TITLE)  | curses.A_BOLD]
    attr  = pulse[tick % 2]

    title = f"  ⚡ {APP_NAME}  "
    safe_addstr(win, 0, 0, title, attr)

    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    safe_addstr(win, 0, w - len(now) - 2, now, color(C_DIM))

    info = (f"  {data['hostname']}  │  {data['os_name']}  │  "
            f"Uptime: {fmt_uptime(data['uptime_s'])}")
    safe_addstr(win, 1, 0, info[:w-1], color(C_DIM))

    bat = data.get("battery")
    if bat:
        pct  = bat.percent
        plug = "⚡" if bat.power_plugged else "🔋"
        bs   = f"{plug} {pct:.0f}%"
        safe_addstr(win, 1, w - len(bs) - 2, bs, pct_color(100 - pct + 0.01))

    safe_addstr(win, 2, 0, "─" * (w-1), color(C_BORDER))


def draw_tabs(win, active):
    h, w = win.getmaxyx()
    x = 1
    for i, name in enumerate(TABS):
        label = f" {i+1}:{name} "
        if i == active:
            safe_addstr(win, 3, x, label, color(C_TAB_ACT) | curses.A_BOLD)
        else:
            safe_addstr(win, 3, x, label, color(C_TAB_IN))
        x += len(label) + 1
    safe_addstr(win, 4, 0, "─" * (w-1), color(C_BORDER))


def draw_overview(win, data, tick):
    h, w = win.getmaxyx()
    y0   = 5

    draw_box(win, y0, 0, 5, w//2, "CPU", C_BORDER)
    cpu = data['cpu_total']
    draw_bar_row(win, y0+1, 2, "Загрузка", cpu, width=min(30, w//2-20))
    freq = data['cpu_freq']
    if freq:
        fs = f"{freq.current/1000:.2f} ГГц"
        safe_addstr(win, y0+2, 2, f"Частота: {fs}", color(C_DIM))
    safe_addstr(win, y0+3, 2,
                f"Ядра: {data['cpu_phys']} физ / {data['cpu_count']} лог",
                color(C_DIM))

    ram = data['ram']
    if ram:
        draw_box(win, y0, w//2, 5, w - w//2, "Память", C_BORDER)
        draw_bar_row(win, y0+1, w//2+2, "RAM", ram.percent,
                     width=min(30, w - w//2 - 20))
        safe_addstr(win, y0+2, w//2+2,
                    f"{fmt_bytes(ram.used)} / {fmt_bytes(ram.total)}",
                    color(C_DIM))

    y1 = y0 + 5
    draw_box(win, y1, 0, 5, w, "История CPU (последние ~60 замеров)", C_BORDER)
    spark_w = w - 4
    draw_sparkline(win, y1+1, 2, data['cpu_history'], min(spark_w, HISTORY_LEN))
    safe_addstr(win, y1+1, w-6, " 100%", color(C_DIM))
    safe_addstr(win, y1+3, w-5, "  0%",  color(C_DIM))
    dash = "·" * (spark_w - 6)
    safe_addstr(win, y1+2, 2, dash, color(C_BORDER))
    safe_addstr(win, y1+2, w-6, "  50%", color(C_DIM))

    y2 = y1 + 5
    box_h = min(len(data['top_procs']) + 3, h - y2 - 1)
    if box_h < 3:
        return
    draw_box(win, y2, 0, box_h, w, "Топ процессы по CPU", C_BORDER)
    hdr = f"{'PID':>7}  {'Имя':<22}  {'CPU%':>6}  {'RAM%':>6}  Статус"
    safe_addstr(win, y2+1, 2, hdr[:w-4], color(C_HEAD) | curses.A_BOLD)
    for i, p in enumerate(data['top_procs']):
        if y2+2+i >= h - 1 or i >= box_h - 3:
            break
        cpu_p = p.get('cpu_percent') or 0
        mem_p = p.get('memory_percent') or 0
        name  = (p.get('name') or "?")[:22]
        pid   = p.get('pid', 0)
        stat  = p.get('status', '?')
        row   = f"{pid:>7}  {name:<22}  {cpu_p:>5.1f}%  {mem_p:>5.1f}%  {stat}"
        safe_addstr(win, y2+2+i, 2, row[:w-4], pct_color(cpu_p))


def draw_cpu(win, data, tick):
    h, w = win.getmaxyx()
    y0   = 5
    cores = data['cpu_cores']
    cols  = 2 if w > 80 else 1
    bar_w = (w - 6) // cols - 20

    draw_box(win, y0, 0, len(cores)+4, w, "Ядра CPU", C_BORDER)

    freq = data['cpu_freq']
    freq_s = f"  Частота: {freq.current/1000:.2f} / {freq.max/1000:.2f} ГГц" if freq else ""
    safe_addstr(win, y0+1, 2,
                f"Всего: {data['cpu_total']:5.1f}%   Физ. ядер: {data['cpu_phys']}   "
                f"Лог. ядер: {data['cpu_count']}{freq_s}",
                color(C_DIM))

    for i, pct in enumerate(cores):
        col = i % cols
        row = i // cols
        x   = 2 + col * ((w-4)//cols)
        yy  = y0 + 2 + row
        if yy >= h - 1:
            break
        draw_bar_row(win, yy, x, f"Ядро {i:>2}", pct, width=bar_w)

    y1 = y0 + len(cores) + 4
    if y1 + 5 < h:
        draw_box(win, y1, 0, 5, w, "История CPU", C_BORDER)
        draw_sparkline(win, y1+1, 2, data['cpu_history'], w-4)
        draw_sparkline(win, y1+2, 2, data['cpu_history'], w-4)
        draw_sparkline(win, y1+3, 2, data['cpu_history'], w-4)

    y2 = y1 + 5 if y1 + 5 < h else h
    temps = data.get('temps', {})
    if temps and y2 + 3 < h:
        draw_box(win, y2, 0, len(temps)+2, w//2, "Температуры", C_BORDER)
        for i, (lbl, val) in enumerate(list(temps.items())[:6]):
            if y2+1+i >= h - 1:
                break
            t_attr = pct_color(val) if val > 60 else color(C_GOOD)
            safe_addstr(win, y2+1+i, 2, f"{lbl:<20} {val:5.1f}°C", t_attr)


def draw_memory(win, data, tick):
    h, w = win.getmaxyx()
    y0   = 5
    ram  = data['ram']
    swap = data['swap']

    if ram:
        draw_box(win, y0, 0, 8, w//2, "Оперативная память (RAM)", C_BORDER)
        draw_bar_row(win, y0+1, 2, "Занято", ram.percent, width=min(30, w//2-20))

        rows = [
            ("Всего",    fmt_bytes(ram.total)),
            ("Занято",   fmt_bytes(ram.used)),
            ("Доступно", fmt_bytes(ram.available)),
            ("Буферы",   fmt_bytes(getattr(ram,'buffers',0))),
            ("Кэш",      fmt_bytes(getattr(ram,'cached',0))),
        ]
        for i, (lbl, val) in enumerate(rows):
            safe_addstr(win, y0+2+i, 2, f"{lbl:<12} {val}", color(C_DIM))

    if swap:
        draw_box(win, y0, w//2, 8, w-w//2, "SWAP", C_BORDER)
        draw_bar_row(win, y0+1, w//2+2, "Занято", swap.percent,
                     width=min(30, w-w//2-20))
        rows2 = [
            ("Всего",    fmt_bytes(swap.total)),
            ("Занято",   fmt_bytes(swap.used)),
            ("Свободно", fmt_bytes(swap.free)),
        ]
        for i, (lbl, val) in enumerate(rows2):
            safe_addstr(win, y0+2+i, w//2+2, f"{lbl:<12} {val}", color(C_DIM))

    y1 = y0 + 8
    if ram and y1 + 5 < h:
        draw_box(win, y1, 0, 5, w, "Визуализация RAM", C_BORDER)
        bw = w - 4
        used_chars = int(ram.percent / 100 * bw)
        line = "█" * used_chars + "░" * (bw - used_chars)
        safe_addstr(win, y1+1, 2, line[:bw], pct_color(ram.percent))
        safe_addstr(win, y1+2, 2, line[:bw], pct_color(ram.percent))
        safe_addstr(win, y1+3, 2, line[:bw], pct_color(ram.percent))

        label_l = "0"
        label_r = fmt_bytes(ram.total).strip()
        label_m = f"Занято: {fmt_bytes(ram.used).strip()} ({ram.percent:.1f}%)"
        safe_addstr(win, y1+4, 2, label_l, color(C_DIM))
        mx = max(2, (bw - len(label_m))//2)
        safe_addstr(win, y1+4, 2+mx, label_m, color(C_DIM) | curses.A_BOLD)
        safe_addstr(win, y1+4, bw - len(label_r) + 1, label_r, color(C_DIM))


def draw_disks(win, data, tick):
    h, w = win.getmaxyx()
    y0   = 5
    disks = data['disks']

    if not disks:
        safe_addstr(win, y0+1, 2, "Нет данных о дисках", color(C_WARN))
        return

    row_h = 4
    for i, d in enumerate(disks):
        yy = y0 + i * row_h
        if yy + row_h >= h:
            break
        box_w = w - 2
        draw_box(win, yy, 1, row_h, box_w,
                 f"{d['dev']}  [{d['fs']}]  → {d['mount']}", C_BORDER)
        draw_bar_row(win, yy+1, 3, "Занято", d['pct'],
                     width=min(40, box_w-24))
        info = (f"  Всего: {fmt_bytes(d['total'])}   "
                f"Занято: {fmt_bytes(d['used'])}   "
                f"Свободно: {fmt_bytes(d['free'])}")
        safe_addstr(win, yy+2, 3, info[:box_w-4], color(C_DIM))


def draw_network(win, data, tick):
    h, w = win.getmaxyx()
    y0   = 5

    draw_box(win, y0, 0, 7, w//2, "Трафик", C_BORDER)

    rows = [
        ("↑ Отправлено", data['net_sent'],   C_NET_UP),
        ("↓ Получено",   data['net_recv'],    C_NET_DN),
        ("↑ Скорость",   data['net_sent_s'],  C_NET_UP),
        ("↓ Скорость",   data['net_recv_s'],  C_NET_DN),
    ]
    is_speed = [False, False, True, True]
    for i, ((lbl, val, cpair), spd) in enumerate(zip(rows, is_speed)):
        vs = fmt_bytes(val, speed=spd)
        safe_addstr(win, y0+1+i, 2, f"{lbl:<16} {vs}", color(cpair))

    draw_box(win, y0, w//2, 7, w-w//2, "Скорость", C_BORDER)

    for i, (label, val, cpair) in enumerate([
        ("↑ TX", data['net_sent_s'], C_NET_UP),
        ("↓ RX", data['net_recv_s'], C_NET_DN),
    ]):
        bw = w - w//2 - 20
        max_s = max(data['net_sent_s'], data['net_recv_s'], 1024)
        pct   = min(val / max_s * 100, 100)
        draw_bar_row(win, y0+1+i*2, w//2+2, label, pct, width=bw)
        safe_addstr(win, y0+2+i*2, w//2+2,
                    f"  {fmt_bytes(val, speed=True)}", color(cpair) | curses.A_BOLD)

    y1 = y0 + 7
    try:
        ifaces = psutil.net_if_addrs()
        stats  = psutil.net_if_stats()
        draw_box(win, y1, 0, min(len(ifaces)+2, h-y1-1), w, "Интерфейсы", C_BORDER)
        row = 0
        for name, addrs in ifaces.items():
            if y1+1+row >= h-1:
                break
            st     = stats.get(name)
            up     = "▲ UP" if (st and st.isup) else "▼ DN"
            up_col = color(C_GOOD) if (st and st.isup) else color(C_CRIT)
            ipv4   = next((a.address for a in addrs
                           if a.family.name in ('AF_INET','2')), "—")
            line   = f"{name:<15} {up:<5}  IPv4: {ipv4}"
            safe_addstr(win, y1+1+row, 2, line[:w-4], up_col)
            row += 1
    except Exception:
        pass


def draw_statusbar(win, tick):
    h, w = win.getmaxyx()
    spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    sp = spinner[tick % len(spinner)]
    msg = f" {sp}  q/Esc — выход   Tab/1-5 — вкладки   Обновление: {REFRESH_S}с "
    safe_addstr(win, h-1, 0, msg[:w-1], color(C_BORDER))


def main(stdscr):
    setup_colors()
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)

    sd      = SystemData()
    tab     = 0
    tick    = 0
    running = True

    TAB_DRAWS = [draw_overview, draw_cpu, draw_memory, draw_disks, draw_network]

    try:
        while running:
            key = stdscr.getch()
            if key in (ord('q'), ord('Q'), 27):
                running = False
                break
            elif key == 9:
                tab = (tab + 1) % len(TABS)
            elif ord('1') <= key <= ord('5'):
                tab = key - ord('1')

            data = sd.snapshot()

            stdscr.erase()
            draw_header(stdscr, data, tick)
            draw_tabs(stdscr, tab)
            try:
                TAB_DRAWS[tab](stdscr, data, tick)
            except Exception:
                pass
            draw_statusbar(stdscr, tick)

            stdscr.refresh()
            tick += 1
            time.sleep(0.1)

    finally:
        sd.stop()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nОшибка: {e}")
        print("Убедитесь, что терминал достаточно большой (мин. 80×24).")
        sys.exit(1)