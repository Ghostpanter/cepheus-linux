import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { ApiService, Overview } from '../api.service';

@Component({
  selector: 'app-overview',
  imports: [NgIf],
  template: `
    <div class="page-head">
      <h2>概览</h2>
      <p>主机状态、网络与基础服务一览</p>
    </div>
    <div class="error-banner" *ngIf="error">{{ error }}</div>
    <div class="grid grid-4" *ngIf="data">
      <div class="card">
        <h3>主机</h3>
        <div class="metric">{{ data.hostname }}</div>
        <div class="metric-sub">已运行 {{ formatUptime(data.uptime.seconds) }}</div>
      </div>
      <div class="card">
        <h3>负载</h3>
        <div class="metric">{{ data.load.load1 }}</div>
        <div class="metric-sub">5 分钟 {{ data.load.load5 }} · 15 分钟 {{ data.load.load15 }}</div>
      </div>
      <div class="card">
        <h3>内存</h3>
        <div class="metric">{{ pct(data.memory.used, data.memory.total) }}%</div>
        <div class="metric-sub">{{ human(data.memory.used) }} / {{ human(data.memory.total) }}</div>
        <div class="bar"><span [style.width.%]="pct(data.memory.used, data.memory.total)"></span></div>
      </div>
      <div class="card">
        <h3>磁盘 {{ data.disk.mount }}</h3>
        <div class="metric">{{ pct(data.disk.used, data.disk.total) }}%</div>
        <div class="metric-sub">{{ human(data.disk.used) }} / {{ human(data.disk.total) }}</div>
        <div class="bar"><span [style.width.%]="pct(data.disk.used, data.disk.total)"></span></div>
      </div>
    </div>
    <div class="grid grid-2" style="margin-top:16px" *ngIf="data">
      <div class="card">
        <h3>网络</h3>
        <dl class="kv">
          <dt>Wi-Fi</dt>
          <dd>{{ data.wifi.connected ? (data.wifi.ssid || '已连接') : '未连接' }}</dd>
          <dt>Wi-Fi 地址</dt>
          <dd>{{ data.wlan_ipv4 || data.wifi.ipv4 || '—' }}</dd>
          <dt>WireGuard</dt>
          <dd>{{ data.wireguard_ipv4 || '—' }}</dd>
          <dt>USB</dt>
          <dd>{{ data.usb_ipv4 || '—' }}</dd>
        </dl>
      </div>
      <div class="card">
        <h3>服务</h3>
        <dl class="kv">
          <dt>SSH</dt><dd><span class="pill" [class.ok]="data.services.ssh.active" [class.bad]="!data.services.ssh.active">{{ label(data.services.ssh) }}</span></dd>
          <dt>Docker</dt><dd><span class="pill" [class.ok]="data.services.docker.active" [class.bad]="!data.services.docker.active">{{ label(data.services.docker) }}</span></dd>
          <dt>node_exporter</dt><dd><span class="pill" [class.ok]="data.services.node_exporter.active" [class.bad]="!data.services.node_exporter.active">{{ label(data.services.node_exporter) }}</span></dd>
          <dt>WireGuard</dt><dd><span class="pill" [class.ok]="data.services.wireguard.active" [class.bad]="!data.services.wireguard.active">{{ label(data.services.wireguard) }}</span></dd>
          <dt>屏幕</dt><dd>{{ data.screen.on === true ? '已开启' : data.screen.on === false ? '已关闭' : '未知' }}</dd>
        </dl>
      </div>
    </div>
  `
})
export class OverviewComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  data: Overview | null = null;
  error = '';
  private timer: ReturnType<typeof setInterval> | null = null;

  ngOnInit() {
    this.refresh();
    this.timer = setInterval(() => this.refresh(), 8000);
  }
  ngOnDestroy() {
    if (this.timer) clearInterval(this.timer);
  }
  refresh() {
    this.api.overview().subscribe({
      next: (d) => { this.data = d; this.error = ''; },
      error: () => { this.error = '无法读取概览，请确认面板服务正在运行。'; }
    });
  }
  pct(used: number, total: number) {
    if (!total) return 0;
    return Math.round((used / total) * 100);
  }
  human(n: number) {
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0; let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  }
  formatUptime(sec: number) {
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d > 0) return `${d} 天 ${h} 小时 ${m} 分`;
    if (h > 0) return `${h} 小时 ${m} 分`;
    return `${m} 分钟`;
  }
  label(s: { active: boolean; enabled: string }) {
    if (s.active) return '运行中';
    if (s.enabled === 'enabled' || s.enabled === 'enabled-runtime') return '已配置，未运行';
    return '未开启';
  }
}
