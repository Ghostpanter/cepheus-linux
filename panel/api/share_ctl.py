"""Allowlisted Samba / FTP helpers for the Cepheus panel. No password logging."""
from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

STATE_FILE = Path("/etc/cepheus-panel/share.json")
SMB_CONF = Path("/etc/samba/smb.conf")
VSFTPD_CONF = Path("/etc/vsftpd/vsftpd.conf")
VSFTPD_USERLIST = Path("/etc/vsftpd/user_list")
SMB_NFT = Path("/etc/nftables.d/53_samba.nft")
FTP_NFT = Path("/etc/nftables.d/54_ftp.nft")
DEFAULT_PATH = "/home/user/share"
DEFAULT_SHARE_NAME = "share"
DEFAULT_WORKGROUP = "WORKGROUP"
DEFAULT_USER = "user"
ALLOWED_ROOTS = ("/home/user", "/srv/samba", "/srv/ftp")
SHARE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
WORKGROUP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,15}$")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,31}$")
MAX_PASSWORD_LEN = 63
SMB_UNITS = ("smbd.service", "nmbd.service")
FTP_UNIT = "vsftpd.service"
PASV_MIN = 50000
PASV_MAX = 50010

SMB_NFT_TEXT = """#!/usr/sbin/nft -f

table inet filter {
	chain input {
		tcp dport { 139, 445 } accept comment "accept cepheus-samba"
		udp dport { 137, 138 } accept comment "accept cepheus-samba"
	}
}
"""

FTP_NFT_TEXT = """#!/usr/sbin/nft -f

table inet filter {
	chain input {
		tcp dport 21 accept comment "accept cepheus-ftp"
		tcp dport 50000-50010 accept comment "accept cepheus-ftp"
	}
}
"""


def run(cmd, timeout=30, input_text=None):
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )


def svc_active(name):
    return run(["systemctl", "is-active", "--quiet", name], timeout=8).returncode == 0


def svc_enabled(name):
    r = run(["systemctl", "is-enabled", name], timeout=8)
    return (r.stdout or "").strip() or "disabled"


def _default_state():
    return {
        "path": DEFAULT_PATH,
        "share_name": DEFAULT_SHARE_NAME,
        "workgroup": DEFAULT_WORKGROUP,
        "username": DEFAULT_USER,
        "read_only": False,
        "ftp_anonymous_read": False,
    }


def load_state():
    data = _default_state()
    if STATE_FILE.is_file():
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update({k: raw[k] for k in data if k in raw})
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(STATE_FILE, 0o600)


def validate_path(path):
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path or "\n" in path:
        return None, "共享路径无效"
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError):
        return None, "共享路径无效"
    text = str(resolved)
    for root in ALLOWED_ROOTS:
        if text == root or text.startswith(root + "/"):
            return text, None
    return None, "路径必须位于 /home/user、/srv/samba 或 /srv/ftp 下"


def validate_share_name(name):
    if not isinstance(name, str) or not SHARE_NAME_RE.match(name):
        return "共享名称只能使用字母、数字、点、下划线和连字符"
    return None


def validate_workgroup(name):
    if not isinstance(name, str) or not WORKGROUP_RE.match(name):
        return "工作组名称无效"
    return None


def validate_username(name):
    if not isinstance(name, str) or not USER_RE.match(name):
        return "用户名无效"
    try:
        pwd.getpwnam(name)
    except KeyError:
        return f"系统中没有用户 {name}"
    return None


def validate_password(password):
    if not isinstance(password, str) or not password:
        return "密码不能为空"
    if len(password.encode("utf-8")) > MAX_PASSWORD_LEN or len(password) < 4:
        return "密码长度需在 4 到 63 个字符之间"
    if "\x00" in password or "\n" in password or "\r" in password:
        return "密码含有非法字符"
    return None


def ensure_share_dir(path, username):
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        info = pwd.getpwnam(username)
        os.chown(p, info.pw_uid, info.pw_gid)
    except KeyError:
        pass
    os.chmod(p, 0o750)
    return str(p)


def write_smb_conf(state):
    path = state["path"]
    name = state["share_name"]
    ro = "yes" if state.get("read_only") else "no"
    user = state["username"]
    workgroup = state["workgroup"]
    text = f"""# Managed by cepheus-panel. Do not edit by hand.
[global]
   workgroup = {workgroup}
   server string = Cepheus
   security = user
   map to guest = never
   guest ok = no
   disable netbios = no
   smb ports = 445 139
   logging = syslog@1
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
   server min protocol = SMB2

[{name}]
   path = {path}
   valid users = {user}
   read only = {ro}
   browsable = yes
   guest ok = no
   create mask = 0644
   directory mask = 0755
   force user = {user}
   force group = {user}
"""
    SMB_CONF.parent.mkdir(parents=True, exist_ok=True)
    SMB_CONF.write_text(text, encoding="utf-8")
    r = run(["testparm", "-s", str(SMB_CONF)], timeout=15)
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()


def write_vsftpd_conf(state):
    path = state["path"]
    user = state["username"]
    anon = bool(state.get("ftp_anonymous_read"))
    write_enable = "NO" if state.get("read_only") else "YES"
    # background=NO: stay in foreground for systemd
    text = f"""# Managed by cepheus-panel. Do not edit by hand.
listen=YES
listen_ipv6=NO
background=NO
anonymous_enable={'YES' if anon else 'NO'}
anon_world_readable_only=YES
anon_upload_enable=NO
anon_mkdir_write_enable=NO
local_enable=YES
write_enable={write_enable}
local_umask=022
chroot_local_user=YES
allow_writeable_chroot=YES
user_sub_token=$USER
local_root={path}
userlist_enable=YES
userlist_file={VSFTPD_USERLIST}
userlist_deny=NO
secure_chroot_dir=/var/empty
pam_service_name=vsftpd
pasv_enable=YES
pasv_min_port={PASV_MIN}
pasv_max_port={PASV_MAX}
port_enable=YES
xferlog_enable=NO
log_ftp_protocol=NO
"""
    VSFTPD_CONF.parent.mkdir(parents=True, exist_ok=True)
    VSFTPD_CONF.write_text(text, encoding="utf-8")
    VSFTPD_USERLIST.write_text(user + "\n", encoding="utf-8")
    os.chmod(VSFTPD_USERLIST, 0o644)
    # vsftpd has no dry-run; config is simple text
    return True, ""


def samba_password_set(username):
    if not shutil.which("pdbedit"):
        return False
    r = run(["pdbedit", "-L", "-u", username], timeout=10)
    if r.returncode != 0:
        return False
    return bool((r.stdout or "").strip())


def set_samba_password(username, password):
    err = validate_username(username)
    if err:
        return False, err
    err = validate_password(password)
    if err:
        return False, err
    # -s reads "new\nconfirm\n" from stdin; -a adds if missing
    payload = f"{password}\n{password}\n"
    r = run(["smbpasswd", "-s", "-a", username], timeout=15, input_text=payload)
    # never include the password in returned text
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "设置 Samba 密码失败").strip()
        if password in msg:
            msg = "设置 Samba 密码失败"
        return False, msg[:300]
    return True, "Samba 密码已更新"


def nft_delete_by_comment(comment):
    r = run(["nft", "-a", "list", "chain", "inet", "filter", "input"], timeout=10)
    handles = []
    for line in (r.stdout or "").splitlines():
        if comment not in line:
            continue
        m = re.search(r"\bhandle\s+(\d+)\s*$", line)
        if m:
            handles.append(m.group(1))
    # delete high handles first
    for h in reversed(handles):
        run(["nft", "delete", "rule", "inet", "filter", "input", "handle", h], timeout=10)


def nft_apply(path: Path, text: str, comment: str):
    nft_delete_by_comment(comment)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o644)
    r = run(["nft", "-f", str(path)], timeout=10)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "nft -f 失败").strip()[:300]
    return True, ""


def nft_remove(path: Path, comment: str):
    nft_delete_by_comment(comment)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def addr_on(dev):
    r = run(["ip", "-4", "-o", "addr", "show", "dev", dev], timeout=8)
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", r.stdout or "")
    return m.group(1) if m else None


def connect_urls(state):
    share = state["share_name"]
    wg = addr_on("wg0") or "10.10.10.9"
    wlan = addr_on("wlan0")
    urls = {
        "samba_wg": f"\\\\{wg}\\{share}",
        "samba_wg_uri": f"smb://{wg}/{share}",
        "ftp_wg": f"ftp://{wg}/",
        "samba_wifi": f"\\\\{wlan}\\{share}" if wlan else None,
        "samba_wifi_uri": f"smb://{wlan}/{share}" if wlan else None,
        "ftp_wifi": f"ftp://{wlan}/" if wlan else None,
        "wg_ipv4": wg,
        "wlan_ipv4": wlan,
    }
    return urls


def share_status():
    state = load_state()
    smb_installed = bool(shutil.which("smbd"))
    ftp_installed = bool(shutil.which("vsftpd"))
    return {
        "path": state["path"],
        "share_name": state["share_name"],
        "workgroup": state["workgroup"],
        "username": state["username"],
        "read_only": bool(state.get("read_only")),
        "ftp_anonymous_read": bool(state.get("ftp_anonymous_read")),
        "samba": {
            "installed": smb_installed,
            "active": svc_active("smbd.service"),
            "enabled": svc_enabled("smbd.service"),
            "nmbd_active": svc_active("nmbd.service"),
            "nmbd_enabled": svc_enabled("nmbd.service"),
            "password_set": samba_password_set(state["username"]) if smb_installed else False,
            "ports": {"tcp": [139, 445], "udp": [137, 138]},
        },
        "ftp": {
            "installed": ftp_installed,
            "active": svc_active(FTP_UNIT),
            "enabled": svc_enabled(FTP_UNIT),
            "anonymous_read": bool(state.get("ftp_anonymous_read")),
            "ports": {"tcp": [21], "pasv": [PASV_MIN, PASV_MAX]},
        },
        "connect": connect_urls(state),
    }


def apply_settings(body):
    state = load_state()
    if "path" in body and body["path"] is not None:
        path, err = validate_path(str(body["path"]))
        if err:
            return 400, {"ok": False, "error": err}
        state["path"] = path
    if "share_name" in body and body["share_name"] is not None:
        err = validate_share_name(str(body["share_name"]))
        if err:
            return 400, {"ok": False, "error": err}
        state["share_name"] = str(body["share_name"])
    if "workgroup" in body and body["workgroup"] is not None:
        err = validate_workgroup(str(body["workgroup"]))
        if err:
            return 400, {"ok": False, "error": err}
        state["workgroup"] = str(body["workgroup"])
    if "username" in body and body["username"] is not None:
        err = validate_username(str(body["username"]))
        if err:
            return 400, {"ok": False, "error": err}
        state["username"] = str(body["username"])
    if "read_only" in body:
        state["read_only"] = bool(body["read_only"])
    if "ftp_anonymous_read" in body:
        state["ftp_anonymous_read"] = bool(body["ftp_anonymous_read"])
    try:
        ensure_share_dir(state["path"], state["username"])
    except OSError as exc:
        return 500, {"ok": False, "error": "无法创建共享目录"}
    ok, msg = write_smb_conf(state)
    if not ok:
        clean = msg[:300] if msg else "smb.conf 校验失败"
        return 500, {"ok": False, "error": f"Samba 配置无效: {clean}"}
    write_vsftpd_conf(state)
    save_state(state)
    # reload running daemons if active (config only)
    if svc_active("smbd.service"):
        run(["systemctl", "reload-or-restart", "smbd.service"], timeout=15)
        run(["systemctl", "reload-or-restart", "nmbd.service"], timeout=15)
    if svc_active(FTP_UNIT):
        run(["systemctl", "restart", FTP_UNIT], timeout=15)
    return 200, {"ok": True, "error": None, "share": share_status()}


def set_samba_enabled(enabled):
    state = load_state()
    if enabled:
        if not shutil.which("smbd"):
            return 500, {"ok": False, "error": "未安装 Samba（需要 samba-server）"}
        if not samba_password_set(state["username"]):
            return 400, {"ok": False, "error": "请先为用户设置 Samba 密码再开启共享"}
        try:
            ensure_share_dir(state["path"], state["username"])
        except OSError:
            return 500, {"ok": False, "error": "无法创建共享目录"}
        ok, msg = write_smb_conf(state)
        if not ok:
            return 500, {"ok": False, "error": f"Samba 配置无效: {(msg or '')[:300]}"}
        ok, err = nft_apply(SMB_NFT, SMB_NFT_TEXT, "accept cepheus-samba")
        if not ok:
            return 500, {"ok": False, "error": err or "无法添加 Samba 防火墙规则"}
        r1 = run(["systemctl", "enable", "--now", "smbd.service"], timeout=20)
        r2 = run(["systemctl", "enable", "--now", "nmbd.service"], timeout=20)
        if r1.returncode != 0 or not svc_active("smbd.service"):
            return 500, {"ok": False, "error": "smbd 启动失败", "share": share_status()}
        # nmbd is helpful but not required for \\IP\share
        return 200, {"ok": True, "error": None, "share": share_status(), "nmbd_ok": r2.returncode == 0}
    run(["systemctl", "disable", "--now", "smbd.service"], timeout=20)
    run(["systemctl", "disable", "--now", "nmbd.service"], timeout=20)
    nft_remove(SMB_NFT, "accept cepheus-samba")
    return 200, {"ok": True, "error": None, "share": share_status()}


def set_ftp_enabled(enabled):
    state = load_state()
    if enabled:
        if not shutil.which("vsftpd"):
            return 500, {"ok": False, "error": "未安装 vsftpd"}
        try:
            ensure_share_dir(state["path"], state["username"])
        except OSError:
            return 500, {"ok": False, "error": "无法创建共享目录"}
        write_vsftpd_conf(state)
        Path("/var/empty").mkdir(parents=True, exist_ok=True)
        ok, err = nft_apply(FTP_NFT, FTP_NFT_TEXT, "accept cepheus-ftp")
        if not ok:
            return 500, {"ok": False, "error": err or "无法添加 FTP 防火墙规则"}
        r = run(["systemctl", "enable", "--now", FTP_UNIT], timeout=20)
        if r.returncode != 0 or not svc_active(FTP_UNIT):
            msg = (r.stderr or r.stdout or "vsftpd 启动失败").strip()[:300]
            return 500, {"ok": False, "error": msg, "share": share_status()}
        return 200, {"ok": True, "error": None, "share": share_status()}
    run(["systemctl", "disable", "--now", FTP_UNIT], timeout=20)
    nft_remove(FTP_NFT, "accept cepheus-ftp")
    return 200, {"ok": True, "error": None, "share": share_status()}
