#!/bin/sh
# 交互式扫描并连接 Wi-Fi（NetworkManager / nmcli）
# 用法：wifi-connect
# 选网后输入密码；开放网络直接回车；隐藏网络选 h。
set -eu

die() {
    echo "$*" >&2
    exit 1
}

need_wifi_dev() {
    if nmcli -t -f TYPE,DEVICE device | grep -q '^wifi:'; then
        return 0
    fi
    if [ -x /usr/local/sbin/cepheus-ath10k-board.sh ]; then
        echo "未找到 Wi-Fi 网卡，正在尝试加载固件路径..."
        sudo /usr/local/sbin/cepheus-ath10k-board.sh || true
        # 网卡通常要等服务/驱动就绪
        i=0
        while [ "$i" -lt 8 ]; do
            if nmcli -t -f TYPE,DEVICE device | grep -q '^wifi:'; then
                return 0
            fi
            i=$((i + 1))
            sleep 1
        done
    fi
    die "没有 Wi-Fi 网卡。确认 wlan0 已出现后再试：nmcli device"
}

if ! command -v nmcli >/dev/null 2>&1; then
    die "找不到 nmcli，请确认已安装 NetworkManager。"
fi

nmcli radio wifi on >/dev/null
need_wifi_dev

echo "正在扫描周围的 Wi-Fi..."
nmcli device wifi rescan >/dev/null 2>&1 || true
sleep 2

LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT

# nmcli terse 会把 SSID 里的冒号转义为 \: ，按未转义冒号拆字段。
# 同一名称只保留信号最强的一条；空 SSID（隐藏网络）不进列表。
nmcli -t -f SSID,SIGNAL,SECURITY device wifi list | awk '
function unesc_split(s, a,    n, i, c, cur) {
    n = 0
    cur = ""
    for (i = 1; i <= length(s); i++) {
        c = substr(s, i, 1)
        if (c == "\\") {
            i++
            cur = cur substr(s, i, 1)
        } else if (c == ":") {
            a[++n] = cur
            cur = ""
        } else {
            cur = cur c
        }
    }
    a[++n] = cur
    return n
}
{
    n = unesc_split($0, f)
    ssid = f[1]
    signal = f[2] + 0
    sec = f[3]
    for (i = 4; i <= n; i++)
        sec = sec ":" f[i]
    if (ssid == "")
        next
    if (!(ssid in best) || signal > best[ssid]) {
        best[ssid] = signal
        security[ssid] = (sec == "" ? "开放" : sec)
    }
}
END {
    idx = 0
    for (s in best)
        order[++idx] = s
    for (i = 1; i <= idx; i++) {
        for (j = i + 1; j <= idx; j++) {
            if (best[order[j]] > best[order[i]]) {
                t = order[i]; order[i] = order[j]; order[j] = t
            }
        }
    }
    for (i = 1; i <= idx; i++) {
        s = order[i]
        printf "%d\t%s\t%s\t%s\n", i, s, best[s], security[s]
    }
}
' > "$LIST"

if [ ! -s "$LIST" ]; then
    die "没有扫到可见的 Wi-Fi。可以选 h 连隐藏网络，或稍后再试。"
fi

echo
printf "%-4s %-32s %-6s %s\n" "序号" "名称" "信号" "加密"
echo "--------------------------------------------------------------"
awk -F '\t' '{ printf "%-4s %-32s %-6s %s\n", $1, $2, $3, $4 }' "$LIST"
echo "--------------------------------------------------------------"
echo "输入序号连接，h 连接隐藏网络，r 重新扫描，q 退出。"

printf "请选择: "
read -r choice || die "已取消"

case "$choice" in
    q|Q)
        exit 0
        ;;
    r|R)
        exec "$0"
        ;;
    h|H)
        printf "隐藏网络名称: "
        read -r ssid || die "已取消"
        [ -n "$ssid" ] || die "名称不能为空"
        hidden=yes
        ;;
    *)
        echo "$choice" | grep -Eq '^[0-9]+$' || die "无效选择: $choice"
        ssid=$(awk -F '\t' -v n="$choice" '$1 == n { print $2; found=1 } END { if (!found) exit 1 }' "$LIST") || die "没有这个序号: $choice"
        hidden=no
        ;;
esac

printf "密码（开放网络直接回车）: "
if stty -echo 2>/dev/null; then
    read -r psk || { stty echo; die "已取消"; }
    stty echo
    echo
else
    read -r psk || die "已取消"
fi

echo "正在连接: $ssid"
set +e
if [ -z "${psk:-}" ]; then
    if [ "$hidden" = yes ]; then
        sudo nmcli device wifi connect "$ssid" hidden yes
    else
        sudo nmcli device wifi connect "$ssid"
    fi
else
    if [ "$hidden" = yes ]; then
        sudo nmcli device wifi connect "$ssid" password "$psk" hidden yes
    else
        sudo nmcli device wifi connect "$ssid" password "$psk"
    fi
fi
rc=$?
set -e
unset psk

echo
if [ "$rc" -eq 0 ]; then
    echo "连接成功。"
    nmcli -t -f NAME,TYPE,DEVICE,STATE connection show --active | grep ':802-11-wireless:' || true
    ip -4 addr show scope global 2>/dev/null | awk '/inet /{print "地址: "$2}'
else
    die "连接失败（退出码 $rc）。请检查名称和密码后重试。"
fi
