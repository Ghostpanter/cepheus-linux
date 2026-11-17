import { Component, OnInit, inject } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, WifiCurrent, WifiNet } from '../api.service';

@Component({
  selector: 'app-wifi',
  imports: [NgIf, NgFor, FormsModule],
  template: `
    <div class="page-head">
      <h2>Wi-Fi</h2>
      <p>扫描可见网络并连接。隐藏网络不会出现在扫描列表中。</p>
    </div>
    <div class="error-banner" *ngIf="error">{{ error }}</div>
    <div class="card" style="margin-bottom:16px">
      <h3>当前连接</h3>
      <dl class="kv" *ngIf="current">
        <dt>名称</dt><dd>{{ current.connected ? (current.ssid || '已连接') : '未连接' }}</dd>
        <dt>网卡</dt><dd>{{ current.device || '—' }}</dd>
        <dt>地址</dt><dd>{{ current.ipv4 || '—' }}</dd>
      </dl>
    </div>
    <div class="card" style="margin-bottom:16px">
      <h3>可见网络</h3>
      <p class="hint">扫描列表里看不到隐藏 Wi-Fi，因为它不广播名称。这是预期行为，不是搜索失败。</p>
      <div class="row" style="margin-bottom:10px">
        <button class="btn" [disabled]="scanning || connecting" (click)="scan()">{{ scanning ? '正在扫描…' : '扫描网络' }}</button>
      </div>
      <table *ngIf="networks.length">
        <thead>
          <tr><th>名称</th><th>信号</th><th>加密</th><th></th></tr>
        </thead>
        <tbody>
          <tr *ngFor="let n of networks">
            <td class="ssid">{{ n.ssid }} <span class="pill ok" *ngIf="n.in_use">当前</span></td>
            <td>{{ n.signal }}%</td>
            <td>{{ n.security }}</td>
            <td>
              <form class="row" (ngSubmit)="connect(n.ssid, n.password || '', false)">
                <input type="password" [(ngModel)]="n.password" name="pw-{{n.ssid}}" placeholder="密码（开放网络可留空）" style="max-width:220px">
                <button class="btn ghost" type="submit" [disabled]="connecting">连接</button>
              </form>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="hint" *ngIf="scanned && !networks.length">没有扫到可见的 Wi-Fi。可以使用下方表单连接隐藏网络。</p>
    </div>
    <div class="card">
      <h3>连接隐藏网络</h3>
      <p class="hint">手动输入名称和密码。不会自动连接；只有你提交时才会执行。</p>
      <form class="form-grid" (ngSubmit)="connect(hiddenSsid, hiddenPassword, true)">
        <div>
          <label>网络名称（SSID）</label>
          <input type="text" [(ngModel)]="hiddenSsid" name="hiddenSsid" required maxlength="32" autocomplete="off">
        </div>
        <div>
          <label>密码（开放网络可留空）</label>
          <input type="password" [(ngModel)]="hiddenPassword" name="hiddenPassword" maxlength="63">
        </div>
        <div class="row">
          <button class="btn" type="submit" [disabled]="connecting || !hiddenSsid">连接隐藏网络</button>
        </div>
      </form>
      <div class="msg ok" *ngIf="okMsg">{{ okMsg }}</div>
    </div>
  `
})
export class WifiComponent implements OnInit {
  private api = inject(ApiService);
  current: WifiCurrent | null = null;
  networks: (WifiNet & { password?: string })[] = [];
  scanning = false;
  scanned = false;
  connecting = false;
  error = '';
  okMsg = '';
  hiddenSsid = '';
  hiddenPassword = '';

  ngOnInit() {
    this.api.wifi().subscribe({
      next: (r) => this.current = r.current,
      error: () => { this.error = '无法读取当前 Wi-Fi 状态。'; }
    });
  }
  scan() {
    this.scanning = true; this.error = ''; this.okMsg = '';
    this.api.scanWifi().subscribe({
      next: (r) => {
        this.scanning = false;
        this.scanned = true;
        this.current = r.current;
        this.networks = r.networks.map((n) => ({ ...n, password: '' }));
      },
      error: () => { this.scanning = false; this.error = '扫描失败。'; }
    });
  }
  connect(ssid: string, password: string, hidden: boolean) {
    this.connecting = true; this.error = ''; this.okMsg = '';
    this.api.connectWifi(ssid, password, hidden).subscribe({
      next: (r) => {
        this.connecting = false;
        if (r.ok) {
          this.current = r.current;
          this.okMsg = hidden ? `已请求连接隐藏网络「${ssid}」` : `已请求连接「${ssid}」`;
          if (hidden) { this.hiddenPassword = ''; }
        } else {
          this.error = r.error || '连接失败';
        }
      },
      error: () => { this.connecting = false; this.error = '请求失败。'; }
    });
  }
}
