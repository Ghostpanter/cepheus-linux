#!/usr/bin/env python3
"""Fullscreen framebuffer monitor dashboard for Cepheus (1080x2340)."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

# linux/kd.h, linux/vt.h
KDSETMODE = 0x4B3A
KD_TEXT = 0
KD_GRAPHICS = 1
VT_ACTIVATE = 0x5606
VT_WAITACTIVE = 0x5607

FB_SYS = Path("/sys/class/graphics/fb0")
FB_DEV = Path("/dev/fb0")
DEFAULT_W, DEFAULT_H, DEFAULT_STRIDE, DEFAULT_BPP = 1080, 2340, 4352, 32
INTERVAL = 3.0
SETTINGS_PATH = Path("/etc/cepheus-panel/screen.json")
STATUS_PATH = Path("/run/cepheus-fb-kiosk.json")
BL_BRIGHTNESS = Path("/sys/class/backlight/ae94000.dsi.0/brightness")
DEFAULT_KIOSK_BRIGHTNESS = 320
BRIGHTNESS_MAX = 1023
ORBIT_RADIUS = 12
ORBIT_STEPS = 16
REST_INTERVAL_DEFAULT = 12 * 60
REST_DURATION_DEFAULT = 45
REST_SLEEP = 0.8

DEFAULT_SETTINGS = {
    "burnin_protect": True,
    "orbit": True,
    "orbit_px": ORBIT_RADIUS,
    "rest_enabled": True,
    "rest_interval_sec": REST_INTERVAL_DEFAULT,
    "rest_duration_sec": REST_DURATION_DEFAULT,
    "kiosk_brightness": DEFAULT_KIOSK_BRIGHTNESS,
}

BG = (15, 31, 56)
CARD = (27, 51, 88)
ACCENT = (94, 114, 228)
TEXT = (255, 255, 255)
MUTED = (154, 168, 195)
OK = (45, 206, 137)
WARN = (251, 99, 64)
BAD = (245, 54, 92)
BAR_BG = (12, 24, 44)
DIM = (36, 64, 106)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/TTF/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc",
    "/usr/share/fonts/TTF/wqy-microhei.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttf",
    "/usr/share/fonts/droid-nonlatin/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/droid-nonlatin/DroidSansFallback.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def run(cmd, timeout=8):
    try:
        return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def fb_geometry():
    vs = read_text(FB_SYS / "virtual_size") or f"{DEFAULT_W},{DEFAULT_H}"
    try:
        w, h = [int(x) for x in vs.split(",")[:2]]
    except ValueError:
        w, h = DEFAULT_W, DEFAULT_H
    try:
        stride = int(read_text(FB_SYS / "stride") or DEFAULT_STRIDE)
    except ValueError:
        stride = DEFAULT_STRIDE
    try:
        bpp = int(read_text(FB_SYS / "bits_per_pixel") or DEFAULT_BPP)
    except ValueError:
        bpp = DEFAULT_BPP
    if w <= 0 or h <= 0 or stride < w:
        w, h, stride, bpp = DEFAULT_W, DEFAULT_H, DEFAULT_STRIDE, DEFAULT_BPP
    return w, h, stride, bpp


def _open_tty():
    for path in ("/dev/tty1", "/dev/tty0", "/dev/console"):
        try:
            return os.open(path, os.O_RDWR)
        except OSError:
            continue
    return None


def set_kd_mode(mode):
    fd = _open_tty()
    if fd is None:
        return False
    try:
        fcntl.ioctl(fd, KDSETMODE, mode)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _activate_vt(num):
    fd = _open_tty()
    if fd is None:
        return False
    try:
        fcntl.ioctl(fd, VT_ACTIVATE, num)
        try:
            fcntl.ioctl(fd, VT_WAITACTIVE, num)
        except OSError:
            pass
        return True
    except OSError:
        run(["chvt", str(num)], timeout=5)
        return False
    finally:
        os.close(fd)


def restore_console():
    """Return the panel to the tty1 text login prompt."""
    set_kd_mode(KD_TEXT)
    blank = Path("/sys/class/graphics/fb0/blank")
    if blank.exists():
        try:
            blank.write_text("1")
            time.sleep(0.05)
            blank.write_text("0")
        except OSError:
            pass
    _activate_vt(1)
    # Bounce the VT so fbcon redraws after we overwrote /dev/fb0.
    run(["chvt", "2"], timeout=5)
    time.sleep(0.25)
    run(["chvt", "1"], timeout=5)
    _activate_vt(1)
    for unit in ("getty@tty1.service", "agetty@tty1.service"):
        r = run(["systemctl", "try-restart", unit], timeout=10)
        if r is not None and r.returncode == 0:
            break
    return 0


def load_font(size, prefer_sc=True):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if not os.path.isfile(path):
            continue
        chosen = None
        for index in range(10):
            try:
                font = ImageFont.truetype(path, size=size, index=index)
            except OSError:
                if index == 0:
                    break
                continue
            name = ""
            try:
                name = " ".join(font.getname())
            except Exception:
                name = path
            if prefer_sc and ("SC" in name or "CN" in name or "Simplified" in name):
                return font
            if chosen is None:
                chosen = font
            if not path.lower().endswith((".ttc", ".otc")):
                break
        if chosen is not None:
            return chosen
    return ImageFont.load_default()


_font_cache = {}


def font(size):
    key = int(size)
    if key not in _font_cache:
        _font_cache[key] = load_font(key)
    return _font_cache[key]


def fmt_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    for i, unit in enumerate(units):
        if n < 1024 or i == len(units) - 1:
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return "—"


def fmt_uptime(seconds):
    seconds = int(seconds or 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d} 天 {h} 小时"
    if h:
        return f"{h} 小时 {m} 分钟"
    return f"{m} 分钟"


def read_cpu():
    raw = read_text("/proc/stat") or ""
    line = raw.splitlines()[0] if raw else ""
    parts = line.split()
    if len(parts) < 5:
        return None
    try:
        nums = [int(x) for x in parts[1:]]
    except ValueError:
        return None
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    total = sum(nums)
    return idle, total


def cpu_percent(prev, cur):
    if not prev or not cur:
        return None
    di = cur[0] - prev[0]
    dt = cur[1] - prev[1]
    if dt <= 0:
        return None
    used = max(0.0, min(100.0, 100.0 * (1.0 - (di / dt))))
    return used


def mem_info():
    info = {}
    raw = read_text("/proc/meminfo") or ""
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                info[parts[0][:-1]] = int(parts[1]) * 1024
            except ValueError:
                pass
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(total - avail, 0)
    return total, used, avail


def disk_info(path="/"):
    try:
        st = os.statvfs(path)
    except OSError:
        return 0, 0, 0
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    return total, used, free


def loadavg():
    raw = read_text("/proc/loadavg") or "0 0 0"
    parts = raw.split()
    return (parts + ["0", "0", "0"])[:3]


def hostname():
    return read_text("/etc/hostname") or "cepheus"


def uptime_seconds():
    raw = read_text("/proc/uptime") or "0"
    try:
        return float(raw.split()[0])
    except ValueError:
        return 0.0


def addr_on(dev):
    r = run(["ip", "-4", "-o", "addr", "show", "dev", dev], timeout=5)
    if not r or r.returncode != 0:
        return None
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", r.stdout or "")
    return m.group(1) if m else None


def wifi_ssid():
    r = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], timeout=5)
    if not r or not r.stdout:
        return None
    for line in r.stdout.splitlines():
        fields = line.split(":")
        if len(fields) >= 3 and fields[1] == "802-11-wireless":
            return fields[0] or None
    return None


def thermals():
    root = Path("/sys/class/thermal")
    items = []
    if not root.is_dir():
        return items
    for z in sorted(root.glob("thermal_zone*")):
        typ = read_text(z / "type") or z.name
        raw = read_text(z / "temp")
        if not raw:
            continue
        try:
            c = int(raw) / 1000.0
        except ValueError:
            continue
        if c <= 0 or c > 120:
            continue
        items.append((typ, c))
    return items


def pick_thermals(items, limit=4):
    if not items:
        return []
    prefer = []
    rest = []
    keys = ("cpu", "gpu", "soc", "tsens", "cluster", "aoss", "mdm")
    for typ, c in items:
        low = typ.lower()
        if any(k in low for k in keys):
            prefer.append((typ, c))
        else:
            rest.append((typ, c))
    # de-dup similar names, keep hotter
    chosen = prefer or rest
    chosen.sort(key=lambda x: -x[1])
    out = []
    seen = set()
    for typ, c in chosen:
        key = typ.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((typ, c))
        if len(out) >= limit:
            break
    return out


def svc_active(name):
    r = run(["systemctl", "is-active", "--quiet", name], timeout=5)
    return bool(r) and r.returncode == 0


def services():
    return [
        ("SSH", svc_active("sshd")),
        ("WireGuard", svc_active("wg-quick@wg0")),
        ("Docker", svc_active("docker")),
        ("面板", svc_active("cepheus-panel")),
        ("采集", svc_active("node_exporter")),
    ]


def containers(limit=5):
    if not shutil.which("docker"):
        return []
    r = run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], timeout=5)
    if not r or r.returncode != 0:
        return []
    rows = []
    for line in (r.stdout or "").splitlines():
        if not line.strip():
            continue
        if "\t" in line:
            name, status = line.split("\t", 1)
        else:
            name, status = line, ""
        rows.append((name.strip(), status.strip()))
        if len(rows) >= limit:
            break
    return rows


def collect(prev_cpu):
    cur_cpu = read_cpu()
    mem_total, mem_used, mem_avail = mem_info()
    disk_total, disk_used, disk_free = disk_info("/")
    nets = []
    ssid = wifi_ssid()
    wlan = addr_on("wlan0")
    if wlan:
        label = f"Wi-Fi  {ssid}" if ssid else "Wi-Fi"
        nets.append((label, "wlan0", wlan))
    wg = addr_on("wg0")
    if wg:
        nets.append(("WireGuard", "wg0", wg))
    usb = addr_on("usb0") or addr_on("eth0")
    if usb:
        dev = "usb0" if addr_on("usb0") else "eth0"
        nets.append(("USB", dev, usb))
    return {
        "hostname": hostname(),
        "uptime": uptime_seconds(),
        "cpu": cpu_percent(prev_cpu, cur_cpu),
        "cpu_raw": cur_cpu,
        "load": loadavg(),
        "mem": (mem_total, mem_used, mem_avail),
        "disk": (disk_total, disk_used, disk_free),
        "temps": pick_thermals(thermals()),
        "nets": nets,
        "services": services(),
        "containers": containers(),
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def text_size(draw, s, fnt):
    box = draw.textbbox((0, 0), s, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def draw_bar(draw, x, y, w, h, frac, fill=ACCENT):
    frac = 0.0 if frac is None else max(0.0, min(1.0, float(frac)))
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=BAR_BG)
    fw = int(w * frac)
    if fw >= h:
        draw.rounded_rectangle((x, y, x + fw, y + h), radius=h // 2, fill=fill)
    elif fw > 0:
        draw.ellipse((x, y, x + h, y + h), fill=fill)


def temp_color(c):
    if c is None:
        return MUTED
    if c >= 80:
        return BAD
    if c >= 65:
        return WARN
    return OK



def _clamp_int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def load_settings():
    cfg = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if "burnin_protect" in raw:
                cfg["burnin_protect"] = bool(raw["burnin_protect"])
            if "orbit" in raw:
                cfg["orbit"] = bool(raw["orbit"])
            if "rest_enabled" in raw:
                cfg["rest_enabled"] = bool(raw["rest_enabled"])
            if "orbit_px" in raw:
                cfg["orbit_px"] = _clamp_int(raw["orbit_px"], 4, 24, ORBIT_RADIUS)
            if "rest_interval_sec" in raw:
                cfg["rest_interval_sec"] = _clamp_int(raw["rest_interval_sec"], 120, 3600, REST_INTERVAL_DEFAULT)
            if "rest_duration_sec" in raw:
                cfg["rest_duration_sec"] = _clamp_int(raw["rest_duration_sec"], 15, 180, REST_DURATION_DEFAULT)
            if "kiosk_brightness" in raw:
                cfg["kiosk_brightness"] = _clamp_int(raw["kiosk_brightness"], 40, BRIGHTNESS_MAX, DEFAULT_KIOSK_BRIGHTNESS)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return cfg


def write_status(resting, settings=None):
    payload = {
        "resting": bool(resting),
        "updated": int(time.time()),
    }
    if settings:
        payload["kiosk_brightness"] = settings.get("kiosk_brightness")
        payload["burnin_protect"] = settings.get("burnin_protect")
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATUS_PATH.with_name(STATUS_PATH.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(STATUS_PATH)
    except OSError:
        pass


def set_brightness(value):
    try:
        v = _clamp_int(value, 1, BRIGHTNESS_MAX, DEFAULT_KIOSK_BRIGHTNESS)
        BL_BRIGHTNESS.write_text(str(v), encoding="utf-8")
        return v
    except OSError:
        return None


def orbit_offsets(radius=ORBIT_RADIUS, steps=ORBIT_STEPS):
    out = []
    for i in range(steps):
        ang = 2 * math.pi * i / steps
        dx = int(round(radius * math.cos(ang)))
        dy = int(round(radius * math.sin(ang)))
        if not out or (dx, dy) != out[-1]:
            out.append((dx, dy))
    return out or [(0, 0)]


def apply_orbit(img, dx, dy):
    from PIL import Image

    w, h = img.size
    out = Image.new("RGB", (w, h), (0, 0, 0))
    out.paste(img, (dx, dy))
    return out


def render_rest(metrics, size, t):
    from PIL import Image, ImageDraw

    w, h = size or (DEFAULT_W, DEFAULT_H)
    img = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    host = metrics.get("hostname") or ""
    clock = metrics.get("now") or ""
    f_clock = font(72)
    f_host = font(36)
    cw, ch = text_size(draw, clock, f_clock)
    hw, hh = text_size(draw, host, f_host)
    block_w = max(cw, hw)
    block_h = ch + 16 + hh
    margin_x = max(48, block_w // 2 + 24)
    margin_y = max(48, block_h // 2 + 24)
    rx = max(40, (w // 2) - margin_x)
    ry = max(80, (h // 2) - margin_y)
    cx = (w - block_w) // 2 + int(rx * math.sin(t * 2 * math.pi / 28.0))
    cy = (h - block_h) // 2 + int(ry * math.cos(t * 2 * math.pi / 37.0))
    dim = (52, 62, 80)
    draw.text((cx + (block_w - hw) // 2, cy), host, font=f_host, fill=dim)
    draw.text((cx + (block_w - cw) // 2, cy + hh + 16), clock, font=f_clock, fill=dim)
    return img


def render_frame(metrics, size=None):
    from PIL import Image, ImageDraw

    w, h = size or (DEFAULT_W, DEFAULT_H)
    # Draw on a taller canvas if needed, then scale to the panel.
    canvas = Image.new("RGB", (w, h + 800), BG)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, w, 10), fill=ACCENT)

    pad = 48
    x0 = pad
    y = 32
    inner = w - pad * 2

    host = metrics["hostname"]
    draw.text((x0, y), host, font=font(68), fill=TEXT)
    y += 84
    draw.text((x0, y), "监控页", font=font(34), fill=ACCENT)
    tw, _ = text_size(draw, "监控页", font(34))
    draw.text((x0 + tw + 24, y + 4), metrics["now"], font=font(30), fill=MUTED)
    y += 50
    draw.text((x0, y), f"已运行  {fmt_uptime(metrics['uptime'])}", font=font(30), fill=MUTED)
    y += 60

    def card(title, height):
        nonlocal y
        box = (x0, y, x0 + inner, y + height)
        draw.rounded_rectangle(box, radius=26, fill=CARD)
        draw.text((x0 + 36, y + 22), title, font=font(26), fill=MUTED)
        top = y
        y += height + 20
        return top, box

    top, _ = card("处理器", 230)
    cpu = metrics["cpu"]
    cpu_s = "—" if cpu is None else f"{cpu:.0f}%"
    color = BAD if (cpu or 0) >= 90 else (WARN if (cpu or 0) >= 70 else TEXT)
    draw.text((x0 + 36, top + 64), cpu_s, font=font(96), fill=color)
    load = metrics["load"]
    draw.text((x0 + 36, top + 172), f"负载  {load[0]}   {load[1]}   {load[2]}", font=font(28), fill=MUTED)
    if cpu is not None:
        draw_bar(draw, x0 + 390, top + 118, inner - 450, 20, cpu / 100.0)

    top, _ = card("内存", 230)
    mt, mu, ma = metrics["mem"]
    frac = (mu / mt) if mt else 0
    draw.text((x0 + 36, top + 64), f"{frac * 100:.0f}%", font=font(96), fill=TEXT)
    draw.text((x0 + 36, top + 172), f"{fmt_bytes(mu)}  /  {fmt_bytes(mt)}", font=font(28), fill=MUTED)
    draw_bar(draw, x0 + 390, top + 118, inner - 450, 20, frac)

    top, _ = card("存储", 230)
    dt, du, df = metrics["disk"]
    frac = (du / dt) if dt else 0
    dcolor = BAD if frac >= 0.9 else (WARN if frac >= 0.8 else TEXT)
    draw.text((x0 + 36, top + 64), f"{frac * 100:.0f}%", font=font(96), fill=dcolor)
    draw.text((x0 + 36, top + 172), f"{fmt_bytes(du)}  /  {fmt_bytes(dt)}    可用 {fmt_bytes(df)}", font=font(28), fill=MUTED)
    draw_bar(draw, x0 + 390, top + 118, inner - 450, 20, frac, fill=dcolor if dcolor != TEXT else ACCENT)

    temps = metrics["temps"]
    top, _ = card("温度", 160 if not temps else 220)
    if not temps:
        draw.text((x0 + 36, top + 86), "暂无温度读数", font=font(32), fill=MUTED)
    else:
        hottest = max(t[1] for t in temps)
        draw.text((x0 + 36, top + 70), f"{hottest:.0f}°", font=font(84), fill=temp_color(hottest))
        draw.text((x0 + 36, top + 168), "最高", font=font(26), fill=MUTED)
        ty = top + 70
        for typ, c in temps[:4]:
            label = typ if len(typ) <= 16 else typ[:15] + "…"
            draw.text((x0 + 360, ty), label, font=font(26), fill=MUTED)
            sw, _ = text_size(draw, f"{c:.1f} °C", font(26))
            draw.text((x0 + inner - 36 - sw, ty), f"{c:.1f} °C", font=font(26), fill=temp_color(c))
            ty += 36

    nets = metrics["nets"]
    top, _ = card("网络", 130 if not nets else 92 + len(nets) * 64)
    if not nets:
        draw.text((x0 + 36, top + 76), "暂无 IPv4 地址", font=font(32), fill=MUTED)
    else:
        ty = top + 70
        for label, dev, ip in nets:
            draw.ellipse((x0 + 40, ty + 10, x0 + 60, ty + 30), fill=OK)
            short = label if len(label) <= 18 else label[:17] + "…"
            draw.text((x0 + 80, ty), short, font=font(28), fill=MUTED)
            sw, _ = text_size(draw, ip, font(30))
            draw.text((x0 + inner - 36 - sw, ty), ip, font=font(30), fill=TEXT)
            ty += 64

    svcs = metrics["services"]
    rows_n = (len(svcs) + 1) // 2
    top, _ = card("服务", 96 + rows_n * 72)
    col_w = inner // 2
    for i, (name, active) in enumerate(svcs):
        cx = x0 + 36 + (i % 2) * col_w
        cy = top + 78 + (i // 2) * 72
        draw.ellipse((cx, cy + 12, cx + 24, cy + 36), fill=OK if active else DIM)
        draw.text((cx + 40, cy), name, font=font(32), fill=TEXT)
        draw.text((cx + 40, cy + 38), "运行中" if active else "未运行", font=font(22), fill=MUTED)

    rows = metrics["containers"]
    cheight = 130 if not rows else 88 + len(rows) * 56
    top, _ = card("容器", cheight)
    if not rows:
        draw.text((x0 + 36, top + 76), "没有正在运行的容器", font=font(32), fill=MUTED)
    else:
        ty = top + 74
        for name, status in rows:
            short = name if len(name) <= 22 else name[:21] + "…"
            st = status if len(status) <= 28 else status[:27] + "…"
            running = status.lower().startswith("up")
            draw.ellipse((x0 + 40, ty + 12, x0 + 60, ty + 32), fill=OK if running else WARN)
            draw.text((x0 + 80, ty), short, font=font(30), fill=TEXT)
            sw, _ = text_size(draw, st, font(26))
            draw.text((x0 + inner - 36 - sw, ty + 2), st, font=font(26), fill=MUTED)
            ty += 56

    y += 10
    footer = "Cepheus 监控"
    fw, fh = text_size(draw, footer, font(26))
    draw.text(((w - fw) // 2, y), footer, font=font(26), fill=MUTED)
    content_h = y + fh + 36

    if content_h <= h:
        return canvas.crop((0, 0, w, h))
    # Scale to fit the physical panel if content ran long.
    fitted = canvas.crop((0, 0, w, content_h)).resize((w, h), Image.Resampling.LANCZOS)
    return fitted



def blit(img):
    w, h, stride, bpp = fb_geometry()
    if bpp != 32:
        raise RuntimeError(f"unsupported fb bpp: {bpp}")
    if img.size != (w, h):
        img = img.resize((w, h))
    from PIL import Image

    rgba = img.convert("RGBA")
    r, g, b, _a = rgba.split()
    opaque = Image.new("L", rgba.size, 255)
    bgra = Image.merge("RGBA", (b, g, r, opaque))
    raw = bgra.tobytes()
    line = w * 4
    if stride == line:
        buf = raw
    else:
        buf = bytearray(stride * h)
        mv_src = memoryview(raw)
        mv_dst = memoryview(buf)
        pad_off = line
        for y in range(h):
            so = y * line
            do = y * stride
            mv_dst[do:do + line] = mv_src[so:so + line]
            # remaining padding already zero
        buf = bytes(buf)
    with open(FB_DEV, "r+b", buffering=0) as fb:
        fb.write(buf)
        fb.flush()


def loop(preview=None):
    prev = read_cpu()
    time.sleep(0.35)
    settings = load_settings()
    if preview:
        metrics = collect(prev)
        img = render_frame(metrics)
        img.save(preview)
        print(f"wrote preview {preview}", flush=True)
        return 0

    set_kd_mode(KD_GRAPHICS)
    running = True
    applied_brightness = set_brightness(settings["kiosk_brightness"])
    orbit_i = 0
    resting = False
    rest_until = 0.0
    last_rest_end = time.time()
    write_status(False, settings)

    def stop(_signum=None, _frame=None):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while running:
        try:
            settings = load_settings()
            target_b = settings["kiosk_brightness"]
            if resting:
                target_b = max(40, min(target_b, max(40, target_b // 4)))
            if applied_brightness != target_b:
                applied_brightness = set_brightness(target_b) or applied_brightness

            now = time.time()
            protect = bool(settings.get("burnin_protect"))
            if resting and now >= rest_until:
                resting = False
                last_rest_end = now
                applied_brightness = set_brightness(settings["kiosk_brightness"]) or applied_brightness
                write_status(False, settings)

            if (
                not resting
                and protect
                and settings.get("rest_enabled")
                and (now - last_rest_end) >= settings["rest_interval_sec"]
            ):
                resting = True
                rest_until = now + settings["rest_duration_sec"]
                applied_brightness = set_brightness(max(40, settings["kiosk_brightness"] // 4)) or applied_brightness
                write_status(True, settings)

            metrics = collect(prev)
            prev = metrics["cpu_raw"] or prev
            size = fb_geometry()[:2]
            if resting:
                img = render_rest(metrics, size, now)
            else:
                img = render_frame(metrics, size=size)
                if protect and settings.get("orbit"):
                    offs = orbit_offsets(settings.get("orbit_px") or ORBIT_RADIUS)
                    dx, dy = offs[orbit_i % len(offs)]
                    img = apply_orbit(img, dx, dy)
                    orbit_i += 1
            blit(img)
        except Exception:
            traceback.print_exc()
        interval = REST_SLEEP if resting else INTERVAL
        deadline = time.time() + interval
        while running and time.time() < deadline:
            time.sleep(0.1)
    try:
        STATUS_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    restore_console()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cepheus framebuffer monitor kiosk")
    parser.add_argument("--restore", action="store_true", help="restore tty1 text console and exit")
    parser.add_argument("--preview", metavar="PNG", help="render one frame to a PNG (for testing)")
    args = parser.parse_args(argv)
    if args.restore:
        return restore_console()
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        print("需要 py3-pillow（Pillow）才能绘制监控页", file=sys.stderr)
        return 1
    return loop(preview=args.preview)


if __name__ == "__main__":
    sys.exit(main())
