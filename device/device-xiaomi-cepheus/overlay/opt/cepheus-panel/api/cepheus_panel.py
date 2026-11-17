#!/usr/bin/env python3
"""Cepheus panel: allowlisted local API + static SPA. Not a root shell."""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _PathBoot
_sys.path.insert(0, str(_PathBoot(__file__).resolve().parent))

import argparse
import json
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import zlib
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import share_ctl
import mount_ctl
import files_ctl

CEPHUS_INIT = "/usr/local/sbin/cepheus-init"
SCREEN_BIN = "/usr/local/sbin/cepheus-screen"
SCREEN_OFF_UNIT = "cepheus-screen-off.service"
KIOSK_UNIT = "cepheus-fb-kiosk.service"
KIOSK_SCRIPT = Path("/opt/cepheus-panel/api/fb_kiosk.py")
SCREEN_SETTINGS = Path("/etc/cepheus-panel/screen.json")
KIOSK_STATUS = Path("/run/cepheus-fb-kiosk.json")
DEFAULT_KIOSK_BRIGHTNESS = 320
BRIGHTNESS_MAX = 1023
DEFAULT_SCREEN_SETTINGS = {
    "burnin_protect": True,
    "orbit": True,
    "orbit_px": 12,
    "rest_enabled": True,
    "rest_interval_sec": 12 * 60,
    "rest_duration_sec": 45,
    "kiosk_brightness": DEFAULT_KIOSK_BRIGHTNESS,
}
FB_SYS = Path("/sys/class/graphics/fb0")
FB_DEV = Path("/dev/fb0")
SNAP_TTL = 1.0
SNAP_SCALE = 2
PORT_DEFAULT = 8088
MAX_SSID_LEN = 32
MAX_PASSWORD_LEN = 63
MAX_HOSTNAME_LEN = 63
DANGEROUS_DISABLE = {"ssh", "wireguard"}
SERVICE_FLAGS = {
    "ssh": "--ssh",
    "docker": "--docker",
    "node-exporter": "--node-exporter",
    "wireguard": "--wireguard",
    "screen-off": "--screen-off",
}

SSID_RE = re.compile(r"[\x00-\x1f\x7f]")
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
PROXY_RE = re.compile(r"^(https?://[^\s]+|none)$", re.I)


def run(cmd, timeout=60, input_text=None, env=None):
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
        env=env,
    )


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def first_line(cmd, timeout=10):
    r = run(cmd, timeout=timeout)
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip().splitlines()[0] if r.stdout.strip() else ""


def svc_active(name):
    return run(["systemctl", "is-active", "--quiet", name], timeout=8).returncode == 0


def svc_enabled(name):
    r = run(["systemctl", "is-enabled", name], timeout=8)
    val = (r.stdout or "").strip() or "disabled"
    return val


def unesc_split(s):
    out, cur, esc = [], [], False
    for ch in s:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


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
    return {"total": total, "used": used, "available": avail}


def disk_info(path="/"):
    st = os.statvfs(path)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    return {"total": total, "used": used, "available": free, "mount": path}


def load_info():
    raw = read_text("/proc/loadavg") or "0 0 0"
    parts = raw.split()
    return {"load1": parts[0], "load5": parts[1], "load15": parts[2]}


def uptime_info():
    raw = read_text("/proc/uptime") or "0"
    try:
        seconds = float(raw.split()[0])
    except ValueError:
        seconds = 0.0
    return {"seconds": int(seconds)}


def hostname():
    return read_text("/etc/hostname") or first_line(["hostname"]) or "unknown"


def current_wifi():
    r = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], timeout=10)
    ssid, dev = None, None
    for line in (r.stdout or "").splitlines():
        fields = unesc_split(line)
        if len(fields) >= 3 and fields[1] == "802-11-wireless":
            ssid, dev = fields[0], fields[2]
            break
    ip = None
    target = dev or "wlan0"
    r2 = run(["ip", "-4", "-o", "addr", "show", "dev", target], timeout=8)
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", r2.stdout or "")
    if m:
        ip = m.group(1)
    return {"ssid": ssid, "device": dev, "ipv4": ip, "connected": bool(ssid)}


def addr_on(dev):
    r = run(["ip", "-4", "-o", "addr", "show", "dev", dev], timeout=8)
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", r.stdout or "")
    return m.group(1) if m else None



def _clamp_int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def load_screen_settings():
    cfg = dict(DEFAULT_SCREEN_SETTINGS)
    try:
        raw = json.loads(SCREEN_SETTINGS.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if "burnin_protect" in raw:
                cfg["burnin_protect"] = bool(raw["burnin_protect"])
            if "orbit" in raw:
                cfg["orbit"] = bool(raw["orbit"])
            if "rest_enabled" in raw:
                cfg["rest_enabled"] = bool(raw["rest_enabled"])
            if "orbit_px" in raw:
                cfg["orbit_px"] = _clamp_int(raw["orbit_px"], 4, 24, 12)
            if "rest_interval_sec" in raw:
                cfg["rest_interval_sec"] = _clamp_int(raw["rest_interval_sec"], 120, 3600, 720)
            if "rest_duration_sec" in raw:
                cfg["rest_duration_sec"] = _clamp_int(raw["rest_duration_sec"], 15, 180, 45)
            if "kiosk_brightness" in raw:
                cfg["kiosk_brightness"] = _clamp_int(
                    raw["kiosk_brightness"], 40, BRIGHTNESS_MAX, DEFAULT_KIOSK_BRIGHTNESS
                )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return cfg


def save_screen_settings(cfg):
    SCREEN_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    payload = load_screen_settings()
    payload.update(cfg)
    tmp = SCREEN_SETTINGS.with_name(SCREEN_SETTINGS.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)
    tmp.replace(SCREEN_SETTINGS)
    return payload


def kiosk_resting():
    try:
        raw = json.loads(KIOSK_STATUS.read_text(encoding="utf-8"))
        return bool(raw.get("resting"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def screen_state():
    bl = Path("/sys/class/backlight/ae94000.dsi.0")
    power = read_text(bl / "bl_power")
    brightness = read_text(bl / "brightness")
    on = None
    if power is not None:
        try:
            on = int(power) == 0
        except ValueError:
            on = None
    if on is None and brightness is not None:
        try:
            on = int(brightness) > 0
        except ValueError:
            on = None
    kiosk_active = svc_active(KIOSK_UNIT)
    kiosk_boot = svc_enabled(KIOSK_UNIT)
    if on is False:
        mode = "off"
    elif kiosk_active:
        mode = "monitor"
    else:
        mode = "console"
    cfg = load_screen_settings()
    return {
        "on": on,
        "brightness": brightness,
        "bl_power": power,
        "screen_off_boot": svc_enabled(SCREEN_OFF_UNIT),
        "screen_off_active": svc_active(SCREEN_OFF_UNIT),
        "mode": mode,
        "kiosk_active": kiosk_active,
        "kiosk_boot": kiosk_boot,
        "burnin_protect": cfg["burnin_protect"],
        "orbit": cfg["orbit"],
        "orbit_px": cfg["orbit_px"],
        "rest_enabled": cfg["rest_enabled"],
        "rest_interval_sec": cfg["rest_interval_sec"],
        "rest_duration_sec": cfg["rest_duration_sec"],
        "kiosk_brightness": cfg["kiosk_brightness"],
        "kiosk_resting": kiosk_resting() if kiosk_active else False,
    }


def fb_geometry():
    vs = read_text(FB_SYS / "virtual_size") or "1080,2340"
    try:
        width, height = [int(x) for x in vs.split(",")[:2]]
    except ValueError:
        width, height = 1080, 2340
    try:
        stride = int(read_text(FB_SYS / "stride") or "4352")
    except ValueError:
        stride = 4352
    try:
        bpp = int(read_text(FB_SYS / "bits_per_pixel") or "32")
    except ValueError:
        bpp = 32
    return width, height, stride, bpp


def _png_bytes(rgb, width, height):
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def capture_fb_png(scale=SNAP_SCALE):
    """Read /dev/fb0 with its real stride and flatten BGRA (alpha is 0) to opaque RGB PNG."""
    width, height, stride, bpp = fb_geometry()
    if bpp != 32:
        raise RuntimeError("unsupported framebuffer depth")
    if stride < width * 4:
        raise RuntimeError("invalid framebuffer stride")
    scale = max(1, int(scale or 1))
    with open(FB_DEV, "rb") as fb:
        data = fb.read(stride * height)
    if len(data) < stride * height:
        raise RuntimeError("short framebuffer read")
    out_w = width // scale
    out_h = height // scale
    rgb = bytearray(out_w * out_h * 3)
    mv = memoryview(data)
    oi = 0
    for y in range(0, height, scale):
        row = mv[y * stride:(y + 1) * stride]
        for x in range(0, width, scale):
            i = x * 4
            # BGRA; keep color channels and drop the zero alpha.
            rgb[oi] = row[i + 2]
            rgb[oi + 1] = row[i + 1]
            rgb[oi + 2] = row[i]
            oi += 3
    return _png_bytes(bytes(rgb), out_w, out_h)


_snap_lock = threading.Lock()
_snap_cache = {"ts": 0.0, "png": b""}


def screen_snapshot():
    now = time.time()
    with _snap_lock:
        if _snap_cache["png"] and (now - _snap_cache["ts"]) < SNAP_TTL:
            return _snap_cache["png"]
    png = capture_fb_png()
    with _snap_lock:
        _snap_cache["ts"] = time.time()
        _snap_cache["png"] = png
    return png


def restore_console():
    script = KIOSK_SCRIPT if KIOSK_SCRIPT.is_file() else Path(__file__).resolve().parent / "fb_kiosk.py"
    if script.is_file():
        return run([sys.executable, str(script), "--restore"], timeout=15)
    return run(["chvt", "1"], timeout=5)


def stop_kiosk():
    r = run(["systemctl", "stop", KIOSK_UNIT], timeout=20)
    # ExecStopPost should restore the tty; call restore again if the unit was already inactive.
    if not svc_active(KIOSK_UNIT):
        restore_console()
    return r


def start_kiosk():
    return run(["systemctl", "start", KIOSK_UNIT], timeout=20)


def set_kiosk_boot(enabled):
    if enabled not in (True, False):
        return 400, {"ok": False, "error": "enabled 必须是 true 或 false", "screen": screen_state()}
    cmd = ["systemctl", "enable" if enabled else "disable", KIOSK_UNIT]
    r = run(cmd, timeout=15)
    ok = r.returncode == 0
    return (200 if ok else 500), {
        "ok": ok,
        "error": None if ok else ((r.stderr or r.stdout or "无法更改开机显示监控").strip()[:300]),
        "screen": screen_state(),
        "output": (r.stdout or r.stderr or "").strip()[:500],
    }


def hardware_state():
    dri = Path("/dev/dri")
    cards = []
    if dri.is_dir():
        cards = sorted(p.name for p in dri.iterdir() if p.name.startswith(("card", "render")))
    gpu_devfreq = Path("/sys/class/devfreq/2c00000.gpu")
    freq = read_text(gpu_devfreq / "cur_freq") if gpu_devfreq.exists() else None
    gov = read_text(gpu_devfreq / "governor") if gpu_devfreq.exists() else None
    avail = read_text(gpu_devfreq / "available_frequencies") if gpu_devfreq.exists() else None
    gpu_ok = bool(cards) or gpu_devfreq.exists() or Path("/sys/class/devfreq").exists() and any(
        "gpu" in p.name or "kgsl" in p.name for p in Path("/sys/class/devfreq").iterdir()
    )
    deferred = {
        "ready": False,
        "status": "尚未就绪，需要晚上重编刷机",
    }
    return {
        "gpu": {
            "ready": gpu_ok,
            "status": "工作中" if gpu_ok else "未检测到",
            "devices": cards,
            "frequency_hz": int(freq) if freq and freq.isdigit() else None,
            "governor": gov,
            "available_frequencies": [int(x) for x in avail.split()] if avail else [],
        },
        "camera": dict(deferred),
        "sensors": dict(deferred),
        "nfc": dict(deferred),
    }


def services_state():
    def pack(unit):
        return {"active": svc_active(unit), "enabled": svc_enabled(unit)}

    docker_installed = bool(shutil.which("dockerd"))
    wg_conf = Path("/etc/wireguard/wg0.conf").is_file()
    proxy_docker = ""
    p = Path("/etc/systemd/system/docker.service.d/http-proxy.conf")
    if p.is_file():
        m = re.search(r'HTTP_PROXY=([^"\n]+)', p.read_text(encoding="utf-8", errors="replace"))
        if m:
            proxy_docker = m.group(1)
    sys_proxy = ""
    sp = Path("/etc/profile.d/cepheus-proxy.sh")
    if sp.is_file():
        m = re.search(r"^export http_proxy=(.*)$", sp.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            sys_proxy = m.group(1)
    return {
        "ssh": pack("sshd"),
        "docker": {**pack("docker"), "installed": docker_installed},
        "node_exporter": pack("node_exporter"),
        "wireguard": {**pack("wg-quick@wg0"), "configured": wg_conf},
        "screen_off": {
            "active": svc_active(SCREEN_OFF_UNIT),
            "enabled": svc_enabled(SCREEN_OFF_UNIT),
        },
        "docker_proxy": proxy_docker or None,
        "sys_proxy": sys_proxy or None,
        "hostname": hostname(),
    }


def overview():
    wifi = current_wifi()
    svcs = services_state()
    return {
        "hostname": hostname(),
        "uptime": uptime_info(),
        "load": load_info(),
        "memory": mem_info(),
        "disk": disk_info("/"),
        "wifi": wifi,
        "wireguard_ipv4": addr_on("wg0"),
        "wlan_ipv4": addr_on("wlan0"),
        "usb_ipv4": addr_on("usb0"),
        "services": {
            "ssh": svcs["ssh"],
            "docker": svcs["docker"],
            "node_exporter": svcs["node_exporter"],
            "wireguard": svcs["wireguard"],
        },
        "screen": screen_state(),
    }


def wifi_scan():
    run(["nmcli", "radio", "wifi", "on"], timeout=10)
    run(["nmcli", "device", "wifi", "rescan"], timeout=20)
    time.sleep(2)
    r = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"], timeout=20)
    best = {}
    for line in (r.stdout or "").splitlines():
        fields = unesc_split(line)
        if len(fields) < 3:
            continue
        ssid, signal_s, sec = fields[0], fields[1], fields[2]
        in_use = fields[3] if len(fields) > 3 else ""
        if not ssid:
            continue
        try:
            signal = int(signal_s)
        except ValueError:
            signal = 0
        cur = best.get(ssid)
        if cur is None or signal > cur["signal"]:
            best[ssid] = {
                "ssid": ssid,
                "signal": signal,
                "security": sec or "开放",
                "in_use": in_use == "*",
            }
    networks = sorted(best.values(), key=lambda x: (-x["signal"], x["ssid"]))
    return {"networks": networks, "current": current_wifi()}


def validate_ssid(ssid):
    if not isinstance(ssid, str) or not ssid or len(ssid.encode("utf-8")) > MAX_SSID_LEN:
        return "SSID 无效或过长"
    if SSID_RE.search(ssid):
        return "SSID 含有非法字符"
    return None


def validate_password(password):
    if password is None:
        return None
    if not isinstance(password, str):
        return "密码格式无效"
    if len(password.encode("utf-8")) > MAX_PASSWORD_LEN:
        return "密码过长"
    if "\x00" in password or "\n" in password or "\r" in password:
        return "密码含有非法字符"
    return None


def wifi_connect(ssid, password, hidden):
    err = validate_ssid(ssid)
    if err:
        return 400, {"ok": False, "error": err}
    err = validate_password(password)
    if err:
        return 400, {"ok": False, "error": err}
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd.extend(["password", password])
    if hidden:
        cmd.extend(["hidden", "yes"])
    r = run(cmd, timeout=45)
    ok = r.returncode == 0
    # Never include the password in the response.
    msg = "连接成功" if ok else "连接失败，请检查名称和密码后重试。"
    detail = (r.stderr or r.stdout or "").strip()
    if not ok and detail:
        # strip any accidental password echo
        if password:
            detail = detail.replace(password, "******")
        msg = f"{msg} {detail[:300]}"
    return (200 if ok else 400), {"ok": ok, "error": None if ok else msg, "current": current_wifi()}


def set_screen(action, enabled=None, kiosk_brightness=None, rest_interval_sec=None,
               rest_duration_sec=None, orbit=None, rest_enabled=None):
    if action == "boot-monitor":
        return set_kiosk_boot(enabled)
    if action == "burnin":
        if enabled is None:
            return 400, {"ok": False, "error": "请指定是否开启防烧屏"}
        cfg = save_screen_settings({"burnin_protect": bool(enabled)})
        msg = "已开启防烧屏" if cfg["burnin_protect"] else "已关闭防烧屏"
        return 200, {"ok": True, "error": None, "screen": screen_state(), "output": msg}
    if action == "kiosk-settings":
        patch = {}
        if kiosk_brightness is not None:
            patch["kiosk_brightness"] = _clamp_int(
                kiosk_brightness, 40, BRIGHTNESS_MAX, DEFAULT_KIOSK_BRIGHTNESS
            )
        if rest_interval_sec is not None:
            patch["rest_interval_sec"] = _clamp_int(rest_interval_sec, 120, 3600, 720)
        if rest_duration_sec is not None:
            patch["rest_duration_sec"] = _clamp_int(rest_duration_sec, 15, 180, 45)
        if orbit is not None:
            patch["orbit"] = bool(orbit)
        if rest_enabled is not None:
            patch["rest_enabled"] = bool(rest_enabled)
        if not patch:
            return 400, {"ok": False, "error": "没有可更新的监控页设置"}
        save_screen_settings(patch)
        return 200, {"ok": True, "error": None, "screen": screen_state(), "output": "已更新监控页设置"}
    if action not in ("on", "off", "console", "monitor"):
        return 400, {"ok": False, "error": "action 只能是 on、off、console、monitor、boot-monitor、burnin 或 kiosk-settings"}

    notes = []
    if action == "on":
        r = run([SCREEN_BIN, "on"], timeout=20)
    elif action == "off":
        stop_kiosk()
        r = run([SCREEN_BIN, "off"], timeout=20)
    elif action == "console":
        stop_kiosk()
        r = run([SCREEN_BIN, "on"], timeout=20)
        notes.append("已切回控制台")
    else:  # monitor
        r_on = run([SCREEN_BIN, "on"], timeout=20)
        if r_on.returncode != 0:
            r = r_on
        else:
            r = start_kiosk()
            # Give the kiosk a moment to paint so a follow-up snapshot is useful.
            if r.returncode == 0:
                time.sleep(0.8)
                notes.append("已切换到监控页")
            else:
                notes.append((r.stderr or r.stdout or "").strip())

    ok = r.returncode == 0
    err = None if ok else (r.stderr or r.stdout or "屏幕操作失败").strip()[:300]
    out = " ".join(x for x in [((r.stdout or "").strip()), *notes] if x)
    return (200 if ok else 500), {
        "ok": ok,
        "error": err,
        "screen": screen_state(),
        "output": out[:500],
    }


def run_init(flag, value, confirm=None):
    if value not in ("yes", "no"):
        return 400, {"ok": False, "error": "只能是 yes 或 no"}
    if value == "no" and flag.lstrip("-") in ("ssh", "wireguard"):
        if confirm != "YES":
            return 400, {
                "ok": False,
                "error": "关闭 SSH 或 WireGuard 必须在确认框中输入 YES",
                "requires_yes": True,
            }
        ok, output = pty_init([flag, "no"], send_yes=True)
    else:
        ok, output = pty_init([flag, value], send_yes=False)
    return (200 if ok else 500), {
        "ok": ok,
        "error": None if ok else (output or "操作失败")[:500],
        "output": output[-2000:],
        "services": services_state(),
    }


def pty_init(args, send_yes=False, timeout=45):
    exe = CEPHUS_INIT if os.access(CEPHUS_INIT, os.X_OK) else shutil.which("cepheus-init")
    if not exe:
        return False, "找不到 cepheus-init"
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(exe, [exe, *args])
        os._exit(127)
    buf = b""
    sent = False
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.4)
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                if send_yes and (not sent) and ("YES" in buf.decode("utf-8", "replace") or "确认" in buf.decode("utf-8", "replace")):
                    os.write(fd, b"YES\n")
                    sent = True
            else:
                try:
                    waited, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    break
                if waited:
                    text = buf.decode("utf-8", "replace")
                    return os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, text
        try:
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited:
                text = buf.decode("utf-8", "replace")
                return os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, text
        except ChildProcessError:
            pass
        os.kill(pid, 15)
        time.sleep(0.2)
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        return False, buf.decode("utf-8", "replace") + "\n操作超时"
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def set_hostname(name):
    if not isinstance(name, str) or not HOSTNAME_RE.match(name):
        return 400, {"ok": False, "error": "主机名只能包含字母、数字和连字符"}
    ok, output = pty_init(["--hostname", name], send_yes=False)
    return (200 if ok else 500), {"ok": ok, "error": None if ok else output[-400:], "hostname": hostname(), "output": output[-2000:]}


def set_proxy(kind, url):
    if kind not in ("docker", "sys"):
        return 400, {"ok": False, "error": "kind 只能是 docker 或 sys"}
    if not isinstance(url, str) or not PROXY_RE.match(url.strip()):
        return 400, {"ok": False, "error": "代理必须是 http(s) URL，或 none"}
    flag = "--docker-proxy" if kind == "docker" else "--sys-proxy"
    ok, output = pty_init([flag, url.strip()], send_yes=False)
    return (200 if ok else 500), {"ok": ok, "error": None if ok else output[-400:], "services": services_state(), "output": output[-2000:]}


class Handler(SimpleHTTPRequestHandler):
    web_root = Path("/opt/cepheus-panel/web")

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _png(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or "0")
        if length > 1_000_000:
            return None, "请求过大"
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8")), None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "JSON 无效"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/overview":
                return self._json(200, overview())
            if path == "/api/screen":
                return self._json(200, screen_state())
            if path == "/api/screen/snapshot":
                try:
                    return self._png(screen_snapshot())
                except Exception:
                    return self._json(503, {"ok": False, "error": "无法读取帧缓冲"})
            if path == "/api/wifi":
                return self._json(200, {"current": current_wifi()})
            if path == "/api/wifi/scan":
                return self._json(200, wifi_scan())
            if path == "/api/services":
                return self._json(200, services_state())
            if path == "/api/hardware":
                return self._json(200, hardware_state())
            if path == "/api/share":
                return self._json(200, share_ctl.share_status())
            if path == "/api/mounts":
                return self._json(200, mount_ctl.status())
            if path == "/api/files":
                qs = urllib.parse.parse_qs(parsed.query)
                rel = (qs.get("path") or [""])[0]
                root = (qs.get("root") or [""])[0]
                code, payload = files_ctl.list_dir(rel, root=root or None)
                return self._json(code, payload)
            if path == "/api/files/download":
                qs = urllib.parse.parse_qs(parsed.query)
                rel = (qs.get("path") or [""])[0]
                root = (qs.get("root") or [""])[0]
                err = files_ctl.handle_download(self, rel, root=root or None)
                if err:
                    return self._json(400, {"ok": False, "error": err})
                return
            if path.startswith("/api/"):
                return self._json(404, {"ok": False, "error": "未知接口"})
        except subprocess.TimeoutExpired:
            return self._json(504, {"ok": False, "error": "命令超时"})
        except Exception as exc:
            return self._json(500, {"ok": False, "error": "服务器错误"})
        return self._serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/files/upload":
            try:
                code, payload = files_ctl.handle_upload(self)
                return self._json(code, payload)
            except subprocess.TimeoutExpired:
                return self._json(504, {"ok": False, "error": "命令超时"})
            except Exception:
                return self._json(500, {"ok": False, "error": "上传失败"})
        body, err = self._read_json()
        if err:
            return self._json(400, {"ok": False, "error": err})
        if not isinstance(body, dict):
            return self._json(400, {"ok": False, "error": "请求体必须是对象"})
        try:
            if path == "/api/screen":
                code, payload = set_screen(
                    str(body.get("action", "")),
                    enabled=body.get("enabled"),
                    kiosk_brightness=body.get("kiosk_brightness"),
                    rest_interval_sec=body.get("rest_interval_sec"),
                    rest_duration_sec=body.get("rest_duration_sec"),
                    orbit=body.get("orbit"),
                    rest_enabled=body.get("rest_enabled"),
                )
                return self._json(code, payload)
            if path == "/api/wifi/scan":
                return self._json(200, wifi_scan())
            if path == "/api/wifi/connect":
                code, payload = wifi_connect(
                    body.get("ssid"),
                    body.get("password") or "",
                    bool(body.get("hidden")),
                )
                return self._json(code, payload)
            if path == "/api/services":
                name = str(body.get("name") or "")
                enabled = body.get("enabled")
                if name not in SERVICE_FLAGS or enabled not in (True, False):
                    return self._json(400, {"ok": False, "error": "无效的服务或状态"})
                value = "yes" if enabled else "no"
                code, payload = run_init(SERVICE_FLAGS[name], value, confirm=body.get("confirm"))
                return self._json(code, payload)
            if path == "/api/hostname":
                code, payload = set_hostname(body.get("hostname"))
                return self._json(code, payload)
            if path == "/api/proxy":
                code, payload = set_proxy(str(body.get("kind") or ""), str(body.get("url") or ""))
                return self._json(code, payload)
            if path == "/api/share":
                code, payload = share_ctl.apply_settings(body)
                return self._json(code, payload)
            if path == "/api/share/samba":
                if "password" in body and body["password"]:
                    ok, msg = share_ctl.set_samba_password(
                        str(body.get("username") or share_ctl.load_state()["username"]),
                        str(body.get("password") or ""),
                    )
                    # never echo the password
                    if not ok:
                        return self._json(400, {"ok": False, "error": msg, "share": share_ctl.share_status()})
                if "enabled" in body:
                    if body["enabled"] not in (True, False):
                        return self._json(400, {"ok": False, "error": "enabled 无效"})
                    code, payload = share_ctl.set_samba_enabled(bool(body["enabled"]))
                    return self._json(code, payload)
                return self._json(200, {"ok": True, "error": None, "share": share_ctl.share_status()})
            if path == "/api/share/ftp":
                if "ftp_anonymous_read" in body or "path" in body or "read_only" in body:
                    code, payload = share_ctl.apply_settings({
                        k: body[k] for k in ("ftp_anonymous_read", "path", "read_only") if k in body
                    })
                    if code != 200:
                        return self._json(code, payload)
                if "enabled" in body:
                    if body["enabled"] not in (True, False):
                        return self._json(400, {"ok": False, "error": "enabled 无效"})
                    code, payload = share_ctl.set_ftp_enabled(bool(body["enabled"]))
                    return self._json(code, payload)
                return self._json(200, {"ok": True, "error": None, "share": share_ctl.share_status()})
            if path == "/api/mounts":
                code, payload = mount_ctl.dispatch(body)
                return self._json(code, payload)
            if path == "/api/files/mkdir":
                code, payload = files_ctl.mkdir(
                    body.get("path") or "",
                    str(body.get("name") or ""),
                    root=body.get("root"),
                )
                return self._json(code, payload)
            if path == "/api/files/rename":
                code, payload = files_ctl.rename(
                    body.get("path") or "",
                    str(body.get("src") or body.get("from") or ""),
                    str(body.get("dest") or body.get("to") or ""),
                    root=body.get("root"),
                )
                return self._json(code, payload)
            if path == "/api/files/delete":
                code, payload = files_ctl.delete(
                    body.get("path") or "",
                    str(body.get("name") or ""),
                    recursive=bool(body.get("recursive")),
                    confirm=body.get("confirm"),
                    root=body.get("root"),
                )
                return self._json(code, payload)
            return self._json(404, {"ok": False, "error": "未知接口"})
        except subprocess.TimeoutExpired:
            return self._json(504, {"ok": False, "error": "命令超时"})
        except Exception:
            return self._json(500, {"ok": False, "error": "服务器错误"})

    def _serve_static(self, path):
        root = self.web_root.resolve()
        if path == "/":
            rel = Path("index.html")
        else:
            rel = Path(urllib.parse.unquote(path.lstrip("/")))
        candidate = (root / rel).resolve()
        if not str(candidate).startswith(str(root)) or not candidate.is_file():
            # SPA fallback
            candidate = root / "index.html"
        if not candidate.is_file():
            self.send_error(404, "Not Found")
            return
        ctype = self.guess_type(str(candidate))
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if candidate.name == "index.html":
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        # For curl -I / health checks
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._json(200, {"ok": True})
            return
        return self._serve_static(parsed.path if parsed.path != "/" else "/")


def main():
    parser = argparse.ArgumentParser(description="Cepheus control panel")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    parser.add_argument("--web", default="/opt/cepheus-panel/web")
    args = parser.parse_args()
    Handler.web_root = Path(args.web)
    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"cepheus-panel listening on {args.bind}:{args.port} web={Handler.web_root}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
