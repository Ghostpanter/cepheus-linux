"""Whole-device file manager for the Cepheus panel."""
from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import mount_ctl
import share_ctl

MAX_UPLOAD = 512 * 1024 * 1024
MAX_DOWNLOAD_VIRTUAL = 64 * 1024 * 1024
MAX_NAME_LEN = 255
LIST_MAX = 2000
LIST_SECONDS = 8.0
DOWNLOAD_SECONDS = 15.0
NAME_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f/\\]")
VIRTUAL_PREFIXES = ("/proc", "/sys", "/dev", "/run")
PROTECTED_PATHS = {
    "/", "/boot", "/bin", "/sbin", "/lib", "/lib64", "/usr", "/etc", "/opt",
    "/home", "/root", "/var", "/proc", "/sys", "/dev", "/run",
}


def _is_under(path, prefix):
    text = str(path)
    return text == prefix or text.startswith(prefix.rstrip("/") + "/")


def is_virtual(path):
    text = str(path)
    return any(_is_under(text, p) for p in VIRTUAL_PREFIXES)


def write_forbidden(path):
    return is_virtual(path)


def is_protected(path):
    return str(path) in PROTECTED_PATHS


def validate_name(name):
    if not isinstance(name, str) or not name or name in (".", ".."):
        return "名称无效"
    if NAME_FORBIDDEN.search(name) or "/" in name or "\\" in name:
        return "名称不能包含斜杠或控制字符"
    if len(name) > MAX_NAME_LEN:
        return "文件名过长"
    return None


def normalize_abs(path):
    if path is None or path == "":
        path = "/"
    if not isinstance(path, str) or "\x00" in path:
        return None, "路径无效"
    path = path.replace("\\", "/").strip()
    if not path.startswith("/"):
        return None, "路径必须是绝对路径"
    parts = []
    for p in path.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        if NAME_FORBIDDEN.search(p) or len(p) > MAX_NAME_LEN:
            return None, "路径无效"
        parts.append(p)
    return ("/" + "/".join(parts)) if parts else "/", None


def shortcut_base(root_id):
    if not root_id:
        return None
    if root_id == "share":
        return share_ctl.load_state()["path"]
    if isinstance(root_id, str) and root_id.startswith("mnt/"):
        name = root_id[4:]
        for m in mount_ctl.list_mounts():
            if m.get("name") == name:
                return m["target"]
        return None
    if isinstance(root_id, str) and root_id.startswith("/"):
        return root_id
    return None


def coerce_path(path, root=None):
    """Turn new absolute path or legacy root+relative path into an absolute path."""
    if isinstance(path, str) and path.startswith("/"):
        return normalize_abs(path)
    base = shortcut_base(root)
    if base:
        rel = path or ""
        if not isinstance(rel, str) or "\x00" in rel:
            return None, "路径无效"
        rel = rel.replace("\\", "/").strip()
        if rel.startswith("/"):
            return normalize_abs(rel)
        parts = []
        for p in rel.split("/"):
            if p in ("", "."):
                continue
            if p == ".." or NAME_FORBIDDEN.search(p) or len(p) > MAX_NAME_LEN:
                return None, "路径无效"
            parts.append(p)
        joined = str(Path(base).joinpath(*parts)) if parts else base
        return normalize_abs(joined)
    if path in (None, ""):
        return "/home/user", None
    return None, "路径必须是绝对路径"


def _follow(path: Path, max_links=40):
    """Follow symlinks with loop detection. Returns (final_path, lstat or None, error)."""
    cur = path
    seen = set()
    last_st = None
    for _ in range(max_links):
        try:
            st = os.lstat(cur)
        except OSError as exc:
            return cur, None, "路径不存在" if not os.path.lexists(cur) else "无法访问路径"
        last_st = st
        if not stat.S_ISLNK(st.st_mode):
            return Path(cur), st, None
        ident = (st.st_dev, st.st_ino)
        if ident in seen:
            return None, None, "符号链接存在循环"
        seen.add(ident)
        try:
            target = os.readlink(cur)
        except OSError:
            return None, None, "无法读取符号链接"
        nxt = Path(target) if target.startswith("/") else (cur.parent / target)
        cur = Path(os.path.normpath(str(nxt)))
        if not str(cur).startswith("/"):
            cur = Path("/") / cur
    return None, None, "符号链接层级过深"


def resolve_dir(path_str, root=None):
    abs_path, err = coerce_path(path_str, root)
    if err:
        return None, err
    path = Path(abs_path)
    final, st, err = _follow(path)
    if err:
        return None, err
    if st is None:
        return None, "路径不存在"
    if not stat.S_ISDIR(st.st_mode):
        return None, "不是目录"
    return final, None


def resolve_parent(path_str, root=None):
    """Resolve a directory used as the parent for mkdir/upload/rename/delete."""
    return resolve_dir(path_str, root)


def list_shortcuts():
    items = [
        {"id": "/", "label": "系统根目录 /", "path": "/"},
        {"id": "/home/user", "label": "用户目录 /home/user", "path": "/home/user"},
        {"id": "/tmp", "label": "临时目录 /tmp", "path": "/tmp"},
    ]
    try:
        share = share_ctl.load_state()["path"]
        items.append({"id": share, "label": f"共享目录 {share}", "path": share})
    except Exception:
        pass
    try:
        for m in mount_ctl.list_mounts():
            items.append({
                "id": m["target"],
                "label": f"挂载：{m['name']}",
                "path": m["target"],
            })
    except Exception:
        pass
    return items


def _fs_readonly(path: Path):
    try:
        target = path if path.exists() else path.parent
        return bool(os.statvfs(str(target)).f_flag & os.ST_RDONLY)
    except OSError:
        return False


def _read_only(path: Path):
    return write_forbidden(path) or _fs_readonly(path)


def _entry_type(st):
    if stat.S_ISLNK(st.st_mode):
        return "link"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
        return "device"
    if stat.S_ISFIFO(st.st_mode):
        return "fifo"
    if stat.S_ISSOCK(st.st_mode):
        return "socket"
    return "other"


def list_dir(path_str, root=None):
    directory, err = resolve_dir(path_str, root)
    if err:
        return 400 if err != "路径不存在" else 404, {
            "ok": False,
            "error": err,
            "shortcuts": list_shortcuts(),
        }
    entries = []
    truncated = False
    deadline = time.monotonic() + LIST_SECONDS
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if time.monotonic() > deadline or len(entries) >= LIST_MAX:
                    truncated = True
                    break
                name = entry.name
                if name in (".", ".."):
                    continue
                try:
                    lst = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                typ = _entry_type(lst)
                size = 0
                if typ not in ("dir",):
                    try:
                        size = int(lst.st_size)
                    except Exception:
                        size = 0
                try:
                    mtime = int(lst.st_mtime)
                except Exception:
                    mtime = 0
                entries.append({
                    "name": name,
                    "type": typ,
                    "size": size,
                    "mtime": mtime,
                })
    except OSError:
        return 500, {"ok": False, "error": "无法读取目录", "shortcuts": list_shortcuts(), "path": str(directory)}
    entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
    return 200, {
        "ok": True,
        "path": str(directory),
        "resolved": str(directory),
        "read_only": _read_only(directory),
        "truncated": truncated,
        "entries": entries,
        "shortcuts": list_shortcuts(),
    }


def _can_write(path: Path, for_create=False):
    if write_forbidden(path):
        return "不能在 /proc、/sys、/dev 或 /run 下写入"
    if is_protected(path) and not for_create:
        # deleting or renaming the protected directory itself
        return "不能修改这个系统目录本身"
    if _fs_readonly(path):
        return "该位置是只读的"
    return None


def mkdir(path_str, name, root=None):
    err = validate_name(name)
    if err:
        return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    parent, err = resolve_parent(path_str, root)
    if err:
        return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    err = _can_write(parent, for_create=True)
    if err:
        return 403, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    dest = parent / name
    if dest.exists() or dest.is_symlink():
        return 400, {"ok": False, "error": "已存在同名文件或目录", "shortcuts": list_shortcuts()}
    if write_forbidden(dest) or is_protected(dest):
        return 403, {"ok": False, "error": "不能在该位置创建", "shortcuts": list_shortcuts()}
    try:
        dest.mkdir(exist_ok=False)
        _maybe_chown(dest)
    except OSError:
        return 500, {"ok": False, "error": "无法创建目录", "shortcuts": list_shortcuts()}
    return list_dir(str(parent))


def rename(path_str, src, dest_name, root=None):
    err = validate_name(src) or validate_name(dest_name)
    if err:
        return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    parent, err = resolve_parent(path_str, root)
    if err:
        return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    err = _can_write(parent, for_create=True)
    if err:
        return 403, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    src_path = parent / src
    dest_path = parent / dest_name
    if is_protected(src_path) or is_protected(dest_path):
        return 403, {"ok": False, "error": "不能重命名这个系统目录", "shortcuts": list_shortcuts()}
    if not src_path.exists() and not src_path.is_symlink():
        return 404, {"ok": False, "error": "源文件不存在", "shortcuts": list_shortcuts()}
    if dest_path.exists() or dest_path.is_symlink():
        return 400, {"ok": False, "error": "目标名称已存在", "shortcuts": list_shortcuts()}
    try:
        src_path.rename(dest_path)
    except OSError:
        return 500, {"ok": False, "error": "重命名失败", "shortcuts": list_shortcuts()}
    return list_dir(str(parent))


def _rmtree(path: Path, deadline, counters):
    if time.monotonic() > deadline:
        raise TimeoutError("删除超时")
    counters[0] += 1
    if counters[0] > 20000:
        raise TimeoutError("条目过多，已中止删除")
    try:
        st = os.lstat(path)
    except OSError:
        return
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        path.unlink()
        return
    try:
        for child in path.iterdir():
            _rmtree(child, deadline, counters)
        path.rmdir()
    except OSError:
        raise


def delete(path_str, name, recursive=False, confirm=None, root=None):
    err = validate_name(name)
    if err:
        return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    parent, err = resolve_parent(path_str, root)
    if err:
        return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    err = _can_write(parent, for_create=True)
    if err:
        return 403, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    target = parent / name
    if is_protected(target) or write_forbidden(target):
        return 403, {"ok": False, "error": "不能删除这个路径", "shortcuts": list_shortcuts()}
    try:
        st = os.lstat(target)
    except OSError:
        return 404, {"ok": False, "error": "文件不存在", "shortcuts": list_shortcuts()}
    is_dir = stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)
    if is_dir:
        nonempty = False
        try:
            nonempty = any(target.iterdir())
        except OSError:
            nonempty = True
        if nonempty:
            if not recursive or confirm != "YES":
                return 400, {
                    "ok": False,
                    "error": "目录非空，递归删除需要 confirm=YES",
                    "requires_confirm": True,
                    "shortcuts": list_shortcuts(),
                }
        try:
            _rmtree(target, time.monotonic() + 20, [0])
        except TimeoutError as exc:
            return 500, {"ok": False, "error": str(exc), "shortcuts": list_shortcuts()}
        except OSError:
            return 500, {"ok": False, "error": "删除失败", "shortcuts": list_shortcuts()}
    else:
        try:
            target.unlink()
        except OSError:
            return 500, {"ok": False, "error": "删除失败", "shortcuts": list_shortcuts()}
    return list_dir(str(parent))


def _maybe_chown(path: Path):
    text = str(path)
    if not (_is_under(text, "/home/user") or _is_under(text, "/tmp")):
        return
    try:
        uid, gid = mount_ctl._uid_gid()
        os.chown(path, uid, gid)
    except OSError:
        pass


def download_spec(path_str, root=None):
    abs_path, err = coerce_path(path_str, root)
    if err:
        return None, err
    path = Path(abs_path)
    # If the last component is a dangling or circular link, follow with detection
    final, st, err = _follow(path)
    if err:
        return None, err
    if st is None:
        return None, "文件不存在"
    if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
        return None, "不能下载设备节点"
    if stat.S_ISFIFO(st.st_mode):
        return None, "不能下载管道文件"
    if stat.S_ISSOCK(st.st_mode):
        return None, "不能下载套接字"
    if stat.S_ISDIR(st.st_mode):
        return None, "只能下载普通文件"
    if not stat.S_ISREG(st.st_mode):
        return None, "只能下载普通文件"
    return final, None


def rfc5987_filename(name):
    ascii_name = re.sub(r"[^\w.\-]+", "_", name) or "download"
    return ascii_name, quote(name, safe="")


def handle_download(handler, path_str, root=None):
    path, err = download_spec(path_str, root)
    if err:
        return err
    virtual = is_virtual(path)
    try:
        size = path.stat().st_size
    except OSError:
        return "无法读取文件"
    ascii_name, utf8_name = rfc5987_filename(path.name)
    if virtual or size == 0 and virtual:
        # Virtual files often report size 0; read with a cap and timeout.
        deadline = time.monotonic() + DOWNLOAD_SECONDS
        data = bytearray()
        try:
            with open(path, "rb") as f:
                while True:
                    if time.monotonic() > deadline:
                        return "读取超时"
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > MAX_DOWNLOAD_VIRTUAL:
                        return "该文件过大或不是普通存储文件，已拒绝下载"
        except OSError:
            return "无法读取文件"
        payload = bytes(data)
        handler.send_response(200)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}",
        )
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(payload)
        return None

    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header(
        "Content-Disposition",
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}",
    )
    handler.send_header("Content-Length", str(size))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    deadline = time.monotonic() + max(DOWNLOAD_SECONDS, min(size / (1024 * 64), 300))
    try:
        with open(path, "rb") as f:
            while True:
                if time.monotonic() > deadline:
                    break
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                handler.wfile.write(chunk)
    except OSError:
        return "读取文件失败"
    return None


def parse_multipart(handler):
    """Stream a multipart/form-data body. File part is written to a temp file."""
    ctype = handler.headers.get("Content-Type") or ""
    m = re.search(r'boundary=(?P<q>"?)(?P<b>[0-9A-Za-z\'()+_,./:=?\-]+)(?P=q)', ctype, re.I)
    if not m:
        return None, "请求不是有效的上传格式"
    boundary = m.group("b").encode("ascii")
    try:
        clen = int(handler.headers.get("Content-Length") or "0")
    except ValueError:
        return None, "缺少 Content-Length"
    if clen <= 0:
        return None, "上传内容为空"
    if clen > MAX_UPLOAD + 1024 * 1024:
        return None, "文件超过 512MB 限制"

    remaining = [clen]
    rfile = handler.rfile
    marker = b"--" + boundary
    end_marker = b"--" + boundary + b"--"
    buf = b""

    def pull(n=65536):
        nonlocal buf
        if remaining[0] <= 0:
            return
        data = rfile.read(min(n, remaining[0]))
        if not data:
            remaining[0] = 0
            return
        remaining[0] -= len(data)
        buf += data

    def take_until(token):
        nonlocal buf
        while True:
            idx = buf.find(token)
            if idx != -1:
                data = buf[:idx]
                buf = buf[idx + len(token):]
                return data
            # keep a tail so we don't split the token
            keep = len(token) - 1
            if remaining[0] <= 0:
                data, buf = buf, b""
                return data
            pull()
            if len(buf) > 2 * 1024 * 1024 and keep > 0:
                # should not happen for headers; for body we use a different path
                pass

    # preamble until first boundary
    pull(4096)
    # optional leading CRLF
    if buf.startswith(b"\r\n"):
        buf = buf[2:]
    if not buf.startswith(marker):
        # read until marker
        pre = take_until(marker)
        if not buf and marker not in (pre + buf):
            # take_until consumed marker if found
            pass
    else:
        buf = buf[len(marker):]
    # after first --boundary comes -- (end) or \r\n (headers)
    fields = {}
    tmp_path = None
    filename = None
    file_size = 0
    try:
        while True:
            if buf.startswith(b"--"):
                break
            if buf.startswith(b"\r\n"):
                buf = buf[2:]
            # if buffer doesn't have header yet
            while b"\r\n\r\n" not in buf and remaining[0] > 0:
                pull(4096)
            if b"\r\n\r\n" not in buf:
                return None, "上传格式无效"
            header_blob, buf = buf.split(b"\r\n\r\n", 1)
            header_text = header_blob.decode("utf-8", "replace")
            name = None
            fname = None
            for line in header_text.split("\r\n"):
                if line.lower().startswith("content-disposition:"):
                    nm = re.search(r'name="([^"]*)"', line)
                    if nm:
                        name = nm.group(1)
                    fm = re.search(r'filename\*?=([^;]+)', line, re.I)
                    # filename="..." or filename*=UTF-8''...
                    fm2 = re.search(r'filename="([^"]*)"', line)
                    if fm2:
                        fname = fm2.group(1)
            is_file = name == "file" or (fname is not None and name in (None, "file"))
            close_token = b"\r\n" + marker
            if is_file:
                fd, tmp_path = tempfile.mkstemp(prefix=".cepheus-upload-", suffix=".part")
                os.close(fd)
                filename = fname or "upload.bin"
                # only keep the basename
                filename = Path(filename).name
                if validate_name(filename):
                    # still accept after sanitizing?
                    filename = re.sub(r"[^\w.\-]+", "_", filename) or "upload.bin"
                    if validate_name(filename):
                        return None, "上传的文件名无效"
                written = 0
                with open(tmp_path, "wb") as out:
                    while True:
                        idx = buf.find(close_token)
                        if idx != -1:
                            out.write(buf[:idx])
                            written += idx
                            buf = buf[idx + 2:]  # leave marker in buf (strip only \r\n)
                            break
                        keep = len(close_token) - 1
                        if remaining[0] <= 0:
                            # try once more
                            idx = buf.find(close_token)
                            if idx != -1:
                                out.write(buf[:idx])
                                written += idx
                                buf = buf[idx + 2:]
                                break
                            return None, "上传内容不完整"
                        if len(buf) > keep:
                            out.write(buf[:-keep])
                            written += len(buf) - keep
                            buf = buf[-keep:]
                        if written > MAX_UPLOAD:
                            return None, "文件超过 512MB 限制"
                        pull(65536)
                file_size = written
                if file_size > MAX_UPLOAD:
                    return None, "文件超过 512MB 限制"
                # next should be marker
                if not buf.startswith(marker):
                    while len(buf) < len(marker) and remaining[0] > 0:
                        pull(4096)
                    if not buf.startswith(marker):
                        return None, "上传格式无效"
                buf = buf[len(marker):]
            else:
                data = take_until(close_token)
                # take_until already consumed \r\n--boundary? we used close_token = \r\n + marker
                # so remaining buf should start after marker? wait, take_until(close_token) consumes
                # \r\n--boundary and leaves the rest. But I need the marker consumed and -- or \r\n after.
                # After take_until(close_token), buf is whatever followed \r\n--boundary, e.g. -- or \r\n
                if name:
                    try:
                        fields[name] = data.decode("utf-8")
                    except UnicodeDecodeError:
                        fields[name] = data.decode("utf-8", "replace")
            # after marker: -- means end, \r\n means next part
            if buf.startswith(b"--"):
                break
            # loop continues for next part
        if remaining[0] > 0:
            # drain
            while remaining[0] > 0:
                junk = rfile.read(min(65536, remaining[0]))
                if not junk:
                    break
                remaining[0] -= len(junk)
        return {"fields": fields, "tmp_path": tmp_path, "filename": filename, "size": file_size}, None
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise




def handle_upload(handler):
    parsed, err = parse_multipart(handler)
    if err:
        return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
    fields = parsed["fields"]
    tmp_path = parsed["tmp_path"]
    filename = parsed["filename"]
    try:
        if not tmp_path or not filename:
            return 400, {"ok": False, "error": "没有收到文件", "shortcuts": list_shortcuts()}
        root_id = fields.get("root") or ""
        relpath = fields.get("path") or ""
        overwrite = str(fields.get("overwrite") or "").lower() in ("1", "true", "yes")
        err = validate_name(filename)
        if err:
            return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
        parent, err = resolve_parent(relpath, root_id)
        if err:
            return 400, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
        err = _can_write(parent, for_create=True)
        if err:
            return 403, {"ok": False, "error": err, "shortcuts": list_shortcuts()}
        dest = parent / filename
        if write_forbidden(dest):
            return 403, {"ok": False, "error": "不能在该位置写入", "shortcuts": list_shortcuts()}
        if dest.is_symlink():
            return 400, {"ok": False, "error": "拒绝覆盖符号链接", "shortcuts": list_shortcuts()}
        if dest.exists() and not overwrite:
            return 409, {"ok": False, "error": "同名文件已存在（可勾选覆盖后重试）", "shortcuts": list_shortcuts()}
        if dest.exists() and dest.is_dir():
            return 400, {"ok": False, "error": "同名目录已存在", "shortcuts": list_shortcuts()}
        mid = None
        try:
            fd, mid = tempfile.mkstemp(prefix=".cepheus-upload-", suffix=".part", dir=str(parent))
            os.close(fd)
            shutil.copyfile(tmp_path, mid)
            os.chmod(mid, 0o644)
            _maybe_chown(Path(mid))
            os.replace(mid, dest)
            mid = None
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            tmp_path = None
        except OSError:
            if mid:
                try:
                    os.unlink(mid)
                except OSError:
                    pass
            return 500, {"ok": False, "error": "保存文件失败", "shortcuts": list_shortcuts()}
        code, payload = list_dir(str(parent))
        if code == 200:
            payload["uploaded"] = filename
        return code, payload
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
