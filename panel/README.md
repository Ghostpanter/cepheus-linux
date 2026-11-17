# Cepheus 控制面板

小米 9（cepheus）上的设备控制网页：1Panel 风格侧栏 + 卡片，Argon 启发配色（强调色 `#5e72e4`）。自有布局和样式，不含 1Panel / Argon 的标志或受版权保护的素材。

## 组成

- `frontend/`：Angular 19 单页应用（中文）
- `api/cepheus_panel.py`：本机允许清单 API + 静态文件服务（Python 3 标准库）
- `systemd/cepheus-panel.service`
- `nft/50_cepheus_panel.nft`：放行 TCP 8088

页面：概览、屏幕（实时预览、关屏/控制台/监控页、开机关屏与开机显示监控）、Wi-Fi 扫描/连接（含「连接隐藏网络」）、服务开关、文件共享、硬件状态。

「屏幕」页的实时预览来自 `/dev/fb0`（`GET /api/screen/snapshot`）。监控页由 `cepheus-fb-kiosk.service` 在帧缓冲上绘制，默认不开机自启。隐藏 SSID 不会出现在扫描列表。关闭 SSH / WireGuard 必须输入 `YES`。不会自动连接 Wi-Fi。

## 设备上的路径

- 安装目录：`/opt/cepheus-panel`
- 网页根目录：`/opt/cepheus-panel/web`
- 单元：`cepheus-panel.service`
- 监听：`0.0.0.0:8088`

## 构建说明

手机上没有 node/npm，Docker 里也没有现成的 node 镜像。前端在开发机（box）上构建，再把 `dist` 和 API 拷到手机。


## 文件共享（Samba 4 / FTP）

面板「文件共享」页可配置并开关 Samba 与 vsftpd。默认不启动。

- 共享目录默认 `/home/user/share`，用户 `user`。
- Samba 端口 TCP 445/139、UDP 137/138；FTP 21 与被动端口 50000–50010。
- 开启时写入 `/etc/nftables.d/53_samba.nft`、`54_ftp.nft` 并用 `nft -f` 放行；关闭时删除对应规则和片段。
- 单元：`smbd.service`、`nmbd.service`、`vsftpd.service`（发行版包未带 systemd 单元，由本仓库提供）。


## 外部挂载与文件管理

「文件共享」页支持：

- 将 CIFS/SMB、NFS 或本机目录挂载到 `/home/user/mnt/<名称>`，可选开机自动挂载，也可绑定到共享子目录供 Samba/FTP 使用。配置在 `/etc/cepheus-panel/mounts.json`（0600），CIFS 密码单独存放且不会通过 API 返回。
- 「文件管理」是独立菜单，可浏览整台设备的文件系统（从 `/` 开始）。「文件共享」页只保留 Samba/FTP 与外部挂载。

单元：`cepheus-mounts.service`（oneshot，仅挂载勾选了开机自动的项）。
