# 小米 9（cepheus）postmarketOS 服务机

基于 [NiHaiden/cepheus_linux_postmarketOS](https://github.com/NiHaiden/cepheus_linux_postmarketOS)（MIT，上游说明见 [docs/README.upstream.md](docs/README.upstream.md)）。本仓库在其主线内核（`7.0.0-sm8150-aurora`）与设备树工作之上，加入服务机控制面板、AMOLED 防烧屏策略、设备叠加层，以及安全刷机约定。

这不是官方系统，也不是日常手机 ROM。只适合你自己的已解锁设备，有变砖风险，请先备份关键分区。

## 本仓库里有什么

- `panel/`：Cepheus 控制面板（Angular 前端 + Python API）。覆盖开机关屏、监控页、文件管理、共享、Wi-Fi 等。
- 防烧屏（默认开启）：像素微移、定时休息画面、监控亮度下限。配置写在 `/etc/cepheus-panel/screen.json`，也可在「屏幕」页调整。
- `device/device-xiaomi-cepheus/`：设备包 7-r3 的叠加层与 APKBUILD（控制面板、开机关屏、SLPI 守卫、nft 放行 8088 等）。**不含** SSH 密钥、WireGuard 配置或 Samba/CIFS 密码。
- `kernel/`、`pmaports/`、`phone-config/`、`scripts/`：来自上游的内核/设备树补丁与辅助脚本（已去掉仓库中的真实密码）。
- `ubuntu-build.sh`：在 Linux 主机上用 pmbootstrap 安装镜像的脚本（需自行设置工作目录和 `PHONE_PASS`）。

设备包会默认启用：控制面板、开机关屏、`slpi-stop-fastrpc-storm`（SLPI 守卫）、ath10k board 固件辅助。默认**不**启用 kiosk、Samba、FTP、挂载单元和 `wg-quick`（配置存在，需要时再开）。

## 安全刷机约定

只做下面四步，不要扩大范围：

1. `erase dtbo`
2. `fastboot --disable-verity --disable-verification flash vbmeta <vbmeta.img>`
3. `fastboot flash userdata <xiaomi-cepheus.img>`
4. `fastboot flash boot <boot.img>`

**不要刷** `persist`、`modem`、`vendor`、`dsp`、`bluetooth`。不要解绑 GPU，不要手动启动 SLPI，不要改写 vendor 分区。本树中的 SLPI 守卫默认保持开启。

刷完后首次启动会换 SSH 主机密钥；`/home/user` 可能被首次启动脚本重建，因此镜像里**不包含** `authorized_keys`，需要在能登录之后自行安装公钥。本仓库也不包含 `wg0.conf`：请从你自己的备份恢复 WireGuard 与其它私有数据后再启用 `wg-quick@wg0`。

## 构建要点

依赖上游的 pmbootstrap / pmaports 工作流。示例：

```sh
export DEST="$PWD"
export WORK="$HOME/cepheus-pmbootstrap-work"
export PHONE_PASS='你自己设定的镜像登录密码'   # 不要写进 git
# 如需代理，使用环境变量 http_proxy / https_proxy，不要把局域网代理写进仓库
./ubuntu-build.sh
```

`PHONE_PASS` 只用于 `pmbootstrap install --password`，必须由你在环境里提供。`scripts/common.sh` 里的默认值是占位符 `CHANGE_ME`。

GPU 相关 Qualcomm 固件（如 `a640_zap.mbn`）以及其它 non-free 固件不放在本仓库的叠加层里，请使用 linux-firmware 或设备上已有的 stock 分区（见设备包的 `nonfree_firmware` 子包说明）。请自行确认分发许可。

## 控制面板

编译后的静态资源也在设备叠加层的 `overlay/opt/cepheus-panel/`。开发请用 `panel/` 源码。服务默认监听 `0.0.0.0:8088`。设备包已加入 `wireguard-tools` 依赖，但仍不会把私钥或接口配置提交到 git。

## 开源范围（明确不包含）

- WireGuard 私钥、预共享密钥、`wg0.conf`、客户端配置
- SSH 私钥、`authorized_keys`、主机密钥
- Samba / CIFS / 分享密码、其它登录口令
- 刷机镜像、本地备份、构建日志、pmbootstrap 工作目录

## 许可

[MIT](LICENSE)。上游版权归原作者；控制面板、设备叠加层及后续新增文件的版权见 LICENSE 中的补充声明。

## 致谢

感谢 [NiHaiden](https://github.com/NiHaiden/cepheus_linux_postmarketOS) 与 postmarketOS 社区把小米 9 跑在主线内核上。
