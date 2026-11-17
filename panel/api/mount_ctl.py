"""Allowlisted CIFS / NFS / bind mounts for the Cepheus panel."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import share_ctl

MNT_ROOT = Path("/home/user/mnt")
STATE_FILE = Path("/etc/cepheus-panel/mounts.json")
CRED_DIR = Path("/etc/cepheus-panel")
BOOT_UNIT = "cepheus-mounts.service"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,31}$")
HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
TYPES = ("cifs", "nfs", "bind")
BIND_SOURCE_ROOTS = ("/home/user", "/mnt", "/media", "/run/media", "/srv")
FORBIDDEN_EXACT = {"/", "/home", "/home/user/mnt"}
FORBIDDEN_PREFIXES = (
    "/etc",
    "/boot",
    "/usr",
    "/opt",
    "/root",
    "/proc",
    "/sys",
    "/dev",
    "/run/systemd",
    "/home/user/mnt",
)
MOUNT_TIMEOUT = 15
USER_NAME = "user"

CIFS_SRC_RE = re.compile(
    r"^//(%s|%s)(/[^/\\]+)+$"
    % (IPV4_RE.pattern[1:-1], HOST_RE.pattern[1:-1])
)
NFS_SRC_RE = re.compile(
    r"^(%s|%s):(/.*)$" % (IPV4_RE.pattern[1:-1], HOST_RE.pattern[1:-1])
)


def run(cmd, timeout=MOUNT_TIMEOUT, input_text=None):
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
    except subprocess.TimeoutExpired:
        class R:
            returncode = 124
            stdout = ""
            stderr = "操作超时"
        return R()
    except FileNotFoundError:
        class R:
            returncode = 127
            stdout = ""
            stderr = "找不到命令"
        return R()


def _uid_gid():
    try:
        import pwd
        info = pwd.getpwnam(USER_NAME)
        return info.pw_uid, info.pw_gid
    except KeyError:
        return 10000, 10000


def _default_state():
    return {"mounts": []}


def load_state():
    data = _default_state()
    if STATE_FILE.is_file():
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("mounts"), list):
                data["mounts"] = [m for m in raw["mounts"] if isinstance(m, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(STATE_FILE)
    os.chmod(STATE_FILE, 0o600)


def cred_path(name):
    return CRED_DIR / f"cifs-{name}.cred"


def target_path(name):
    return MNT_ROOT / name


def share_bind_path(entry):
    if not entry.get("bind_to_share"):
        return None
    share = share_ctl.load_state()["path"]
    sub = entry.get("share_subdir") or entry["name"]
    if not NAME_RE.match(str(sub)):
        return None
    return str(Path(share) / sub)


def find_entry(name, state=None):
    state = state or load_state()
    for m in state["mounts"]:
        if m.get("name") == name:
            return m
    return None


def parse_mountinfo():
    mounts = []
    try:
        raw = Path("/proc/self/mountinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return mounts
    for line in raw.splitlines():
        # dest is field before " - "
        try:
            left, right = line.split(" - ", 1)
        except ValueError:
            continue
        parts = left.split()
        if len(parts) < 5:
            continue
        dest = parts[4].replace("\\040", " ")
        typ = right.split()[0] if right.split() else ""
        mounts.append((dest, typ))
    return mounts


def is_mounted(path):
    path = str(Path(path)) if path else ""
    if not path:
        return False
    if os.path.ismount(path):
        return True
    # also compare realpath against mountinfo
    try:
        real = str(Path(path).resolve())
    except (OSError, RuntimeError):
        real = path
    for dest, _typ in parse_mountinfo():
        if dest == path or dest == real:
            return True
    return False


def _valid_host(host):
    if IPV4_RE.match(host):
        return all(0 <= int(p) <= 255 for p in host.split("."))
    return bool(HOST_RE.match(host))


def validate_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        return "名称只能使用字母、数字和连字符，并以字母或数字开头"
    return None


def validate_cifs_source(source):
    if not isinstance(source, str):
        return None, "CIFS 路径无效"
    src = source.strip().replace("\\", "/")
    if src.startswith("smb:"):
        src = src[4:]
    if not src.startswith("//"):
        return None, "CIFS 路径需形如 //主机/共享"
    if ".." in src.split("/") or "\x00" in src or "\n" in src:
        return None, "CIFS 路径无效"
    if not CIFS_SRC_RE.match(src):
        return None, "CIFS 路径需形如 //主机/共享"
    host = src[2:].split("/", 1)[0]
    if not _valid_host(host):
        return None, "CIFS 主机名或地址无效"
    return src, None


def validate_nfs_source(source):
    if not isinstance(source, str):
        return None, "NFS 路径无效"
    src = source.strip()
    m = NFS_SRC_RE.match(src)
    if not m:
        return None, "NFS 路径需形如 主机:/导出目录"
    host, export = m.group(1), m.group(2)
    if not _valid_host(host):
        return None, "NFS 主机名或地址无效"
    if ".." in Path(export).parts or "\x00" in src or "\n" in src:
        return None, "NFS 导出路径无效"
    if not export.startswith("/"):
        return None, "NFS 导出路径必须是绝对路径"
    return f"{host}:{export}", None


def validate_bind_source(source):
    if not isinstance(source, str) or not source.startswith("/") or "\x00" in source or "\n" in source:
        return None, "本地路径无效"
    if any(p == ".." for p in Path(source).parts):
        return None, "本地路径无效"
    try:
        p = Path(source)
        if p.is_symlink():
            # resolve and re-check; do not use the raw symlink if it escapes
            pass
        if not p.exists():
            return None, "本地路径不存在"
        resolved = p.resolve()
    except (OSError, RuntimeError):
        return None, "本地路径无效"
    text = str(resolved)
    if text in FORBIDDEN_EXACT:
        return None, "不允许绑定该路径"
    for pref in FORBIDDEN_PREFIXES:
        if text == pref or text.startswith(pref + "/"):
            return None, "不允许绑定该路径"
    allowed = False
    for root in BIND_SOURCE_ROOTS:
        if text == root or text.startswith(root + "/"):
            allowed = True
            break
    if not allowed:
        return None, "绑定源必须位于 /home/user、/mnt、/media、/run/media 或 /srv 下"
    try:
        st = resolved.lstat()
    except OSError:
        return None, "无法访问本地路径"
    if not stat.S_ISDIR(st.st_mode):
        return None, "绑定源必须是已存在的目录"
    if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISSOCK(st.st_mode):
        return None, "不允许绑定设备或特殊文件"
    return text, None


def validate_source(typ, source):
    if typ == "cifs":
        return validate_cifs_source(source)
    if typ == "nfs":
        return validate_nfs_source(source)
    if typ == "bind":
        return validate_bind_source(source)
    return None, "类型只能是 cifs、nfs 或 bind"


def ensure_mnt_root():
    MNT_ROOT.mkdir(parents=True, exist_ok=True)
    uid, gid = _uid_gid()
    try:
        os.chown(MNT_ROOT, uid, gid)
    except OSError:
        pass
    os.chmod(MNT_ROOT, 0o755)


def ensure_target(name):
    ensure_mnt_root()
    target = target_path(name)
    # refuse if a non-directory is in the way
    if target.exists() and not target.is_dir():
        return None, "挂载点路径被文件占用"
    target.mkdir(parents=True, exist_ok=True)
    uid, gid = _uid_gid()
    try:
        os.chown(target, uid, gid)
    except OSError:
        pass
    os.chmod(target, 0o755)
    return str(target), None


def write_credentials(name, username, password, domain=""):
    path = cred_path(name)
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"username={username or 'guest'}\n"]
    if password:
        lines.append(f"password={password}\n")
    if domain:
        lines.append(f"domain={domain}\n")
    path.write_text("".join(lines), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def delete_credentials(name):
    path = cred_path(name)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def public_entry(entry):
    name = entry.get("name", "")
    target = str(target_path(name))
    share_bind = share_bind_path(entry)
    mounted = is_mounted(target)
    share_bound = bool(share_bind and is_mounted(share_bind))
    return {
        "name": name,
        "type": entry.get("type"),
        "source": entry.get("source"),
        "target": target,
        "read_only": bool(entry.get("read_only")),
        "auto_boot": bool(entry.get("auto_boot")),
        "bind_to_share": bool(entry.get("bind_to_share")),
        "share_subdir": entry.get("share_subdir") or name,
        "share_bind": share_bind,
        "share_bound": share_bound,
        "username": entry.get("username") or "",
        "has_credentials": cred_path(name).is_file(),
        "mounted": mounted,
    }


def list_mounts():
    state = load_state()
    return [public_entry(m) for m in state["mounts"]]


def status():
    ensure_mnt_root()
    return {"ok": True, "mnt_root": str(MNT_ROOT), "mounts": list_mounts()}


def _mount_opts(entry):
    ro = bool(entry.get("read_only"))
    typ = entry["type"]
    extra = []
    if typ == "cifs":
        uid, gid = _uid_gid()
        extra += [
            f"uid={uid}",
            f"gid={gid}",
            "iocharset=utf8",
            "file_mode=0644",
            "dir_mode=0755",
            "nosuid",
            "nodev",
        ]
        cred = cred_path(entry["name"])
        if cred.is_file():
            extra.append(f"credentials={cred}")
        else:
            extra.append("guest")
        if ro:
            extra.append("ro")
        return "cifs", extra
    if typ == "nfs":
        extra += ["nosuid", "nodev", "hard", "timeo=50", "retrans=2"]
        if ro:
            extra.append("ro")
        return "nfs", extra
    # bind
    extra.append("bind")
    if ro:
        extra.append("ro")
    return "none", extra


def _do_mount(source, target, typ, opts, timeout=MOUNT_TIMEOUT):
    cmd = ["timeout", str(timeout), "mount", "-t", typ]
    if typ == "none" and "bind" in opts:
        # mount --bind [-o ro] src dest
        cmd = ["timeout", str(timeout), "mount", "--bind"]
        if "ro" in opts:
            # remount ro after bind, or use -o bind,ro
            cmd = ["timeout", str(timeout), "mount", "-o", "bind,ro", source, target]
        else:
            cmd += [source, target]
        r = run(cmd, timeout=timeout + 2)
        return r
    if opts:
        cmd += ["-o", ",".join(opts)]
    cmd += [source, target]
    return run(cmd, timeout=timeout + 2)


def _err_text(r, fallback):
    text = ((r.stderr or "") + "\n" + (r.stdout or "")).strip()
    text = text.replace("\n", " ").strip()
    if r.returncode == 124 or "操作超时" in text:
        return "服务器无响应或挂载超时，请检查地址后重试"
    # never leak credential file contents
    text = re.sub(r"password=[^\s,]+", "password=******", text, flags=re.I)
    return (text or fallback)[:300]


def mount_share_bind(entry):
    dest = share_bind_path(entry)
    if not dest:
        return True, None
    src = str(target_path(entry["name"]))
    if not is_mounted(src) and entry["type"] != "bind":
        return False, "请先挂载外部目录，再绑定到共享"
    p = Path(dest)
    if p.exists() and not p.is_dir():
        return False, "共享子目录被文件占用"
    if p.exists() and any(p.iterdir()) and not is_mounted(dest):
        return False, "共享子目录不是空目录，拒绝覆盖"
    p.mkdir(parents=True, exist_ok=True)
    uid, gid = _uid_gid()
    try:
        os.chown(p, uid, gid)
    except OSError:
        pass
    if is_mounted(dest):
        return True, None
    opts = ["bind"]
    if entry.get("read_only"):
        r = run(["timeout", str(MOUNT_TIMEOUT), "mount", "-o", "bind,ro", src, dest], timeout=MOUNT_TIMEOUT + 2)
    else:
        r = run(["timeout", str(MOUNT_TIMEOUT), "mount", "--bind", src, dest], timeout=MOUNT_TIMEOUT + 2)
    if r.returncode != 0:
        return False, _err_text(r, "绑定到共享目录失败")
    return True, None


def unmount_path(path, timeout=MOUNT_TIMEOUT):
    if not path or not is_mounted(path):
        return True, None
    r = run(["timeout", str(timeout), "umount", path], timeout=timeout + 2)
    if r.returncode == 0:
        return True, None
    return False, _err_text(r, "卸载失败，目录可能正在使用")


def mount_one(name):
    entry = find_entry(name)
    if not entry:
        return 404, {"ok": False, "error": "找不到该挂载", "mounts": list_mounts()}
    target, err = ensure_target(name)
    if err:
        return 400, {"ok": False, "error": err, "mounts": list_mounts()}
    if is_mounted(target):
        if entry.get("bind_to_share"):
            ok, err = mount_share_bind(entry)
            if not ok:
                return 500, {"ok": False, "error": err, "mounts": list_mounts()}
        return 200, {"ok": True, "error": None, "mounts": list_mounts()}
    typ, opts = _mount_opts(entry)
    r = _do_mount(entry["source"], target, typ, opts)
    if r.returncode != 0:
        return 500, {"ok": False, "error": _err_text(r, "挂载失败"), "mounts": list_mounts()}
    if entry.get("bind_to_share"):
        ok, err = mount_share_bind(entry)
        if not ok:
            return 500, {"ok": False, "error": err, "mounts": list_mounts()}
    return 200, {"ok": True, "error": None, "mounts": list_mounts()}


def unmount_one(name):
    entry = find_entry(name)
    if not entry:
        return 404, {"ok": False, "error": "找不到该挂载", "mounts": list_mounts()}
    dest = share_bind_path(entry)
    if dest:
        ok, err = unmount_path(dest)
        if not ok:
            return 500, {"ok": False, "error": err, "mounts": list_mounts()}
    ok, err = unmount_path(str(target_path(name)))
    if not ok:
        return 500, {"ok": False, "error": err, "mounts": list_mounts()}
    return 200, {"ok": True, "error": None, "mounts": list_mounts()}


def sync_boot_unit():
    state = load_state()
    want = any(m.get("auto_boot") for m in state["mounts"])
    if want:
        run(["systemctl", "enable", BOOT_UNIT], timeout=15)
    else:
        run(["systemctl", "disable", BOOT_UNIT], timeout=15)


def add_mount(body):
    name = str(body.get("name") or "").strip()
    err = validate_name(name)
    if err:
        return 400, {"ok": False, "error": err, "mounts": list_mounts()}
    typ = str(body.get("type") or "").strip().lower()
    if typ not in TYPES:
        return 400, {"ok": False, "error": "类型只能是 cifs、nfs 或 bind", "mounts": list_mounts()}
    source, err = validate_source(typ, body.get("source"))
    if err:
        return 400, {"ok": False, "error": err, "mounts": list_mounts()}
    state = load_state()
    if find_entry(name, state):
        return 400, {"ok": False, "error": "该名称已存在", "mounts": list_mounts()}
    sub = str(body.get("share_subdir") or name).strip()
    if body.get("bind_to_share") and not NAME_RE.match(sub):
        return 400, {"ok": False, "error": "共享子目录名称无效", "mounts": list_mounts()}
    entry = {
        "name": name,
        "type": typ,
        "source": source,
        "read_only": bool(body.get("read_only")),
        "auto_boot": bool(body.get("auto_boot")),
        "bind_to_share": bool(body.get("bind_to_share")),
        "share_subdir": sub if body.get("bind_to_share") else sub,
        "username": str(body.get("username") or "").strip() if typ == "cifs" else "",
    }
    if typ == "cifs":
        username = entry["username"]
        password = body.get("password")
        domain = str(body.get("domain") or "").strip()
        if password and not isinstance(password, str):
            return 400, {"ok": False, "error": "密码格式无效", "mounts": list_mounts()}
        if isinstance(password, str) and ("\x00" in password or "\n" in password or "\r" in password):
            return 400, {"ok": False, "error": "密码含有非法字符", "mounts": list_mounts()}
        if username or password:
            write_credentials(name, username, password or "", domain)
        elif body.get("guest"):
            delete_credentials(name)
        elif password == "":
            delete_credentials(name)
    target, err = ensure_target(name)
    if err:
        return 400, {"ok": False, "error": err, "mounts": list_mounts()}
    state["mounts"].append(entry)
    save_state(state)
    sync_boot_unit()
    # Try to mount immediately unless skip_mount
    if not body.get("add_only"):
        code, payload = mount_one(name)
        return code, payload
    return 200, {"ok": True, "error": None, "mounts": list_mounts()}


def update_mount(body):
    name = str(body.get("name") or "").strip()
    state = load_state()
    entry = find_entry(name, state)
    if not entry:
        return 404, {"ok": False, "error": "找不到该挂载", "mounts": list_mounts()}
    if "auto_boot" in body:
        entry["auto_boot"] = bool(body.get("auto_boot"))
    if "read_only" in body:
        entry["read_only"] = bool(body.get("read_only"))
    if "bind_to_share" in body:
        entry["bind_to_share"] = bool(body.get("bind_to_share"))
    if "share_subdir" in body and body["share_subdir"]:
        sub = str(body["share_subdir"]).strip()
        if not NAME_RE.match(sub):
            return 400, {"ok": False, "error": "共享子目录名称无效", "mounts": list_mounts()}
        entry["share_subdir"] = sub
    if entry["type"] == "cifs":
        if "username" in body and body["username"] is not None:
            entry["username"] = str(body.get("username") or "").strip()
        if body.get("password"):
            password = body.get("password")
            if not isinstance(password, str) or "\x00" in password or "\n" in password or "\r" in password:
                return 400, {"ok": False, "error": "密码含有非法字符", "mounts": list_mounts()}
            write_credentials(name, entry.get("username") or "guest", password, str(body.get("domain") or ""))
        elif body.get("clear_credentials"):
            delete_credentials(name)
    save_state(state)
    sync_boot_unit()
    return 200, {"ok": True, "error": None, "mounts": list_mounts()}


def remove_mount(name):
    state = load_state()
    entry = find_entry(name, state)
    if not entry:
        return 404, {"ok": False, "error": "找不到该挂载", "mounts": list_mounts()}
    code, payload = unmount_one(name)
    if code != 200:
        return code, payload
    state["mounts"] = [m for m in state["mounts"] if m.get("name") != name]
    save_state(state)
    delete_credentials(name)
    target = target_path(name)
    try:
        if target.is_dir() and not is_mounted(str(target)) and not any(target.iterdir()):
            target.rmdir()
    except OSError:
        pass
    dest = share_bind_path(entry) if entry.get("bind_to_share") else None
    if dest:
        p = Path(dest)
        try:
            if p.is_dir() and not is_mounted(dest) and not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass
    sync_boot_unit()
    return 200, {"ok": True, "error": None, "mounts": list_mounts()}


def boot_mounts():
    """Called by cepheus-mounts.service at boot."""
    ensure_mnt_root()
    errors = []
    for entry in load_state()["mounts"]:
        if not entry.get("auto_boot"):
            continue
        code, payload = mount_one(entry["name"])
        if code != 200:
            errors.append(f"{entry['name']}: {payload.get('error')}")
    if errors:
        print("cepheus-mounts: " + "; ".join(errors), file=sys.stderr)
        return 1
    return 0


def dispatch(body):
    action = str(body.get("action") or "").strip()
    if action == "add":
        return add_mount(body)
    if action == "mount":
        return mount_one(str(body.get("name") or ""))
    if action == "unmount":
        return unmount_one(str(body.get("name") or ""))
    if action == "remove":
        return remove_mount(str(body.get("name") or ""))
    if action == "update":
        return update_mount(body)
    return 400, {"ok": False, "error": "action 只能是 add、mount、unmount、remove 或 update", "mounts": list_mounts()}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--boot"]:
        return boot_mounts()
    if argv == ["--list"]:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    print("usage: mount_ctl.py --boot | --list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
