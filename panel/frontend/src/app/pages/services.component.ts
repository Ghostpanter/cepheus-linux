import { Component, OnInit, inject } from '@angular/core';
import { NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, ServicesState } from '../api.service';

@Component({
  selector: 'app-services',
  imports: [NgIf, FormsModule],
  template: `
    <div class="page-head">
      <h2>服务</h2>
      <p>通过 cepheus-init 开关基础服务。关闭 SSH 或 WireGuard 必须输入 YES。</p>
    </div>
    <div class="error-banner" *ngIf="error">{{ error }}</div>
    <div class="card" *ngIf="state">
      <div class="toggle">
        <div>
          <strong>SSH</strong>
          <div class="metric-sub">远程登录（端口 22）</div>
        </div>
        <div class="row">
          <span class="pill" [class.ok]="state.ssh.active" [class.bad]="!state.ssh.active">{{ state.ssh.active ? '运行中' : '未运行' }}</span>
          <button class="btn ghost" [disabled]="busy" *ngIf="!state.ssh.active" (click)="toggle('ssh', true)">开启</button>
          <button class="btn bad" [disabled]="busy" *ngIf="state.ssh.active" (click)="beginDanger('ssh')">关闭</button>
        </div>
      </div>
      <div class="toggle">
        <div>
          <strong>Docker</strong>
          <div class="metric-sub">{{ state.docker.installed ? '已安装' : '未安装' }}</div>
        </div>
        <div class="row">
          <span class="pill" [class.ok]="state.docker.active" [class.bad]="!state.docker.active">{{ state.docker.active ? '运行中' : '未运行' }}</span>
          <button class="btn ghost" [disabled]="busy" (click)="toggle('docker', !state.docker.active)">{{ state.docker.active ? '关闭' : '开启' }}</button>
        </div>
      </div>
      <div class="toggle">
        <div>
          <strong>node_exporter</strong>
          <div class="metric-sub">监控指标，端口 9100</div>
        </div>
        <div class="row">
          <span class="pill" [class.ok]="state.node_exporter.active" [class.bad]="!state.node_exporter.active">{{ state.node_exporter.active ? '运行中' : '未运行' }}</span>
          <button class="btn ghost" [disabled]="busy" (click)="toggle('node-exporter', !state.node_exporter.active)">{{ state.node_exporter.active ? '关闭' : '开启' }}</button>
        </div>
      </div>
      <div class="toggle">
        <div>
          <strong>WireGuard</strong>
          <div class="metric-sub">{{ state.wireguard.configured ? '已有配置' : '没有配置文件' }}</div>
        </div>
        <div class="row">
          <span class="pill" [class.ok]="state.wireguard.active" [class.bad]="!state.wireguard.active">{{ state.wireguard.active ? '运行中' : '未运行' }}</span>
          <button class="btn ghost" [disabled]="busy || !state.wireguard.configured" *ngIf="!state.wireguard.active" (click)="toggle('wireguard', true)">开启</button>
          <button class="btn bad" [disabled]="busy" *ngIf="state.wireguard.active" (click)="beginDanger('wireguard')">关闭</button>
        </div>
      </div>
      <div class="toggle">
        <div>
          <strong>开机关屏</strong>
          <div class="metric-sub">cepheus-screen-off.service（{{ enabledLabel(state.screen_off.enabled) }}）</div>
        </div>
        <div class="row">
          <span class="pill" [class.ok]="state.screen_off.enabled.startsWith('enabled')" [class.muted]="!state.screen_off.enabled.startsWith('enabled')">{{ enabledLabel(state.screen_off.enabled) }}</span>
          <button class="btn ghost" [disabled]="busy" (click)="toggle('screen-off', !state.screen_off.enabled.startsWith('enabled'))">{{ state.screen_off.enabled.startsWith('enabled') ? '关闭' : '开启' }}</button>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:16px" *ngIf="danger">
      <h3>危险操作确认</h3>
      <p class="hint">关闭 {{ danger === 'ssh' ? 'SSH' : 'WireGuard' }} 可能导致远程连接断开。请输入大写 YES 后确认。</p>
      <form class="form-grid" (ngSubmit)="confirmDanger()">
        <div>
          <label>输入 YES</label>
          <input type="text" [(ngModel)]="yesText" name="yesText" autocomplete="off" placeholder="YES">
        </div>
        <div class="row">
          <button class="btn bad" type="submit" [disabled]="busy || yesText !== 'YES'">确认关闭</button>
          <button class="btn ghost" type="button" (click)="danger=null; yesText=''">取消</button>
        </div>
      </form>
    </div>

    <div class="grid grid-2" style="margin-top:16px" *ngIf="state">
      <div class="card">
        <h3>主机名</h3>
        <form class="form-grid" (ngSubmit)="saveHostname()">
          <div>
            <label>新主机名</label>
            <input type="text" [(ngModel)]="hostname" name="hostname" maxlength="63">
          </div>
          <button class="btn" type="submit" [disabled]="busy">保存</button>
        </form>
      </div>
      <div class="card">
        <h3>代理</h3>
        <form class="form-grid" (ngSubmit)="saveProxy()">
          <div>
            <label>Docker 拉取代理（URL 或 none）</label>
            <input type="text" [(ngModel)]="dockerProxy" name="dockerProxy" placeholder="http://127.0.0.1:7890 或 none">
          </div>
          <div>
            <label>系统 HTTP 代理（URL 或 none）</label>
            <input type="text" [(ngModel)]="sysProxy" name="sysProxy" placeholder="http://127.0.0.1:7890 或 none">
          </div>
          <button class="btn" type="submit" [disabled]="busy">保存代理</button>
        </form>
      </div>
    </div>
    <div class="msg ok" *ngIf="okMsg">{{ okMsg }}</div>
  `
})
export class ServicesComponent implements OnInit {
  private api = inject(ApiService);
  state: ServicesState | null = null;
  error = '';
  okMsg = '';
  busy = false;
  danger: 'ssh' | 'wireguard' | null = null;
  yesText = '';
  hostname = '';
  dockerProxy = '';
  sysProxy = '';

  ngOnInit() { this.refresh(); }
  refresh() {
    this.api.services().subscribe({
      next: (s) => {
        this.state = s;
        this.hostname = s.hostname;
        this.dockerProxy = s.docker_proxy || '';
        this.sysProxy = s.sys_proxy || '';
        this.error = '';
      },
      error: () => { this.error = '无法读取服务状态。'; }
    });
  }
  enabledLabel(v: string) {
    if (v === 'enabled') return '已开机自启';
    if (v === 'enabled-runtime') return '本次启动已开（尚未写入开机自启）';
    return '未开启';
  }
  beginDanger(name: 'ssh' | 'wireguard') {
    this.danger = name;
    this.yesText = '';
    this.okMsg = '';
    this.error = '';
  }
  confirmDanger() {
    if (!this.danger || this.yesText !== 'YES') return;
    this.toggle(this.danger, false, 'YES');
  }
  toggle(name: string, enabled: boolean, confirm?: string) {
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setService(name, enabled, confirm).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) {
          this.state = r.services;
          this.okMsg = enabled ? '已开启' : '已关闭';
          this.danger = null;
          this.yesText = '';
        } else {
          this.error = r.error || '操作失败';
        }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  saveHostname() {
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setHostname(this.hostname).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) { this.okMsg = '主机名已更新'; this.hostname = r.hostname; }
        else this.error = r.error || '保存失败';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  saveProxy() {
    const jobs: Array<['docker' | 'sys', string]> = [];
    if (this.dockerProxy) jobs.push(['docker', this.dockerProxy]);
    if (this.sysProxy) jobs.push(['sys', this.sysProxy]);
    if (!jobs.length) { this.error = '请填写代理 URL，或输入 none 清除。'; return; }
    this.busy = true; this.error = ''; this.okMsg = '';
    const run = (i: number) => {
      if (i >= jobs.length) { this.busy = false; this.okMsg = '代理已保存'; this.refresh(); return; }
      const [kind, url] = jobs[i];
      this.api.setProxy(kind, url).subscribe({
        next: (r) => {
          if (!r.ok) { this.busy = false; this.error = r.error || '保存失败'; return; }
          run(i + 1);
        },
        error: () => { this.busy = false; this.error = '请求失败。'; }
      });
    };
    run(0);
  }
}
