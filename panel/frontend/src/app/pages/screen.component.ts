import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { NgIf } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ApiService, ScreenAction, ScreenState } from '../api.service';

@Component({
  selector: 'app-screen-page',
  imports: [NgIf, RouterLink],
  template: `
    <div class="page-head">
      <h2>屏幕</h2>
      <p>查看面板当前画面，并切换关屏、控制台或监控页</p>
    </div>
    <div class="error-banner" *ngIf="error">{{ error }}</div>
    <div class="grid screen-layout" *ngIf="state">
      <div class="card preview-card">
        <h3>实时预览</h3>
        <p class="hint">画面来自设备帧缓冲，约每 2.5 秒刷新一次。</p>
        <div class="fb-frame">
          <div class="fb-preview">
            <img *ngIf="state.on !== false && snapshotUrl && !imgError"
                 [src]="snapshotUrl"
                 alt="屏幕预览"
                 (error)="onImgError()" />
            <div class="fb-placeholder" *ngIf="state.on === false">屏幕已关闭</div>
            <div class="fb-placeholder" *ngIf="state.on !== false && imgError">无法获取预览</div>
          </div>
        </div>
      </div>
      <div class="stack">
        <div class="card">
          <h3>当前状态</h3>
          <div class="metric">{{ powerLabel() }} · {{ modeLabel() }}</div>
          <div class="metric-sub">亮度 {{ state.brightness || '—' }} · bl_power {{ state.bl_power || '—' }}</div>
          <h3 style="margin-top:20px">显示内容</h3>
          <p class="hint">监控页会点亮屏幕并在面板上全屏绘制系统状态；控制台则恢复 tty 登录提示。</p>
          <div class="row">
            <button class="btn bad" [class.active]="state.mode === 'off'" [disabled]="busy" (click)="set('off')">关屏</button>
            <button class="btn ghost" [class.active]="state.mode === 'console' && state.on !== false" [disabled]="busy" (click)="set('console')">显示控制台</button>
            <button class="btn" [class.active]="state.mode === 'monitor'" [disabled]="busy" (click)="set('monitor')">显示监控数据</button>
          </div>
          <div class="row" style="margin-top:12px">
            <button class="btn ok" [disabled]="busy || state.on === true" (click)="set('on')">开屏</button>
          </div>
          <div class="msg ok" *ngIf="okMsg">{{ okMsg }}</div>
        </div>
        <div class="card">
          <h3>开机关屏</h3>
          <p class="hint">对应 cepheus-screen-off.service。enabled-runtime 表示本次启动已生效，但尚未写入开机自启。</p>
          <dl class="kv">
            <dt>启用状态</dt>
            <dd><span class="pill" [class.ok]="state.screen_off_boot.startsWith('enabled')" [class.muted]="!state.screen_off_boot.startsWith('enabled')">{{ enabledLabel(state.screen_off_boot) }}</span></dd>
            <dt>当前单元</dt>
            <dd>{{ state.screen_off_active ? 'active' : 'inactive' }}</dd>
          </dl>
          <p class="hint" style="margin-top:12px">如需改开机行为，请到<a routerLink="/services">服务</a>页切换「开机关屏」。</p>
        </div>
        <div class="card">
          <h3>防烧屏</h3>
          <p class="hint">监控页默认开启。可单独开关像素微移和定时休息；监控亮度默认中等，控制台仍可保持较亮。</p>
          <dl class="kv">
            <dt>防烧屏</dt>
            <dd><span class="pill" [class.ok]="state.burnin_protect !== false" [class.muted]="state.burnin_protect === false">{{ burninLabel() }}</span></dd>
            <dt>状态</dt>
            <dd>{{ restLabel() }}</dd>
          </dl>
          <div class="row" style="margin-top:12px">
            <button class="btn" [disabled]="busy || state.burnin_protect !== false" (click)="setBurnin(true)">开启</button>
            <button class="btn ghost" [disabled]="busy || state.burnin_protect === false" (click)="setBurnin(false)">关闭</button>
          </div>
          <p class="hint" style="margin-top:16px">像素微移</p>
          <div class="row">
            <button class="btn" [class.active]="state.orbit !== false" [disabled]="busy" (click)="setOrbit(true)">开启</button>
            <button class="btn ghost" [class.active]="state.orbit === false" [disabled]="busy" (click)="setOrbit(false)">关闭</button>
          </div>
          <p class="hint" style="margin-top:16px">定时休息</p>
          <div class="row">
            <button class="btn" [class.active]="state.rest_enabled !== false" [disabled]="busy" (click)="setRestEnabled(true)">开启</button>
            <button class="btn ghost" [class.active]="state.rest_enabled === false" [disabled]="busy" (click)="setRestEnabled(false)">关闭</button>
          </div>
          <p class="hint" style="margin-top:16px">休息间隔</p>
          <div class="row">
            <button class="btn ghost" [class.active]="(state.rest_interval_sec || 720) === 600" [disabled]="busy" (click)="setRestInterval(600)">10 分钟</button>
            <button class="btn ghost" [class.active]="(state.rest_interval_sec || 720) === 720" [disabled]="busy" (click)="setRestInterval(720)">12 分钟</button>
            <button class="btn ghost" [class.active]="(state.rest_interval_sec || 720) === 900" [disabled]="busy" (click)="setRestInterval(900)">15 分钟</button>
          </div>
          <p class="hint" style="margin-top:16px">休息时长</p>
          <div class="row">
            <button class="btn ghost" [class.active]="(state.rest_duration_sec || 45) === 30" [disabled]="busy" (click)="setRestDuration(30)">30 秒</button>
            <button class="btn ghost" [class.active]="(state.rest_duration_sec || 45) === 45" [disabled]="busy" (click)="setRestDuration(45)">45 秒</button>
            <button class="btn ghost" [class.active]="(state.rest_duration_sec || 45) === 60" [disabled]="busy" (click)="setRestDuration(60)">60 秒</button>
          </div>
          <p class="hint" style="margin-top:16px">监控亮度（{{ state.kiosk_brightness || 320 }} / 1023）</p>
          <input class="bright-range" type="range" min="80" max="1023" step="10"
                 [value]="state.kiosk_brightness || 320"
                 [disabled]="busy"
                 (change)="setKioskBrightness($event)" />
        </div>
        <div class="card">
          <h3>开机显示监控</h3>
          <p class="hint">默认关闭。开启后将在开机关屏之后点亮屏幕并显示监控页，二者不会互相覆盖。</p>
          <dl class="kv">
            <dt>开机自启</dt>
            <dd><span class="pill" [class.ok]="state.kiosk_boot.startsWith('enabled')" [class.muted]="!state.kiosk_boot.startsWith('enabled')">{{ bootMonitorLabel(state.kiosk_boot) }}</span></dd>
            <dt>当前单元</dt>
            <dd>{{ state.kiosk_active ? 'active' : 'inactive' }}</dd>
          </dl>
          <div class="row" style="margin-top:12px">
            <button class="btn" [disabled]="busy || state.kiosk_boot === 'enabled'" (click)="setBootMonitor(true)">开启开机显示</button>
            <button class="btn ghost" [disabled]="busy || state.kiosk_boot === 'disabled'" (click)="setBootMonitor(false)">关闭开机显示</button>
          </div>
        </div>
      </div>
    </div>
  `
})
export class ScreenPageComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  state: ScreenState | null = null;
  error = '';
  okMsg = '';
  busy = false;
  snapshotUrl = '';
  imgError = false;
  private previewTimer: ReturnType<typeof setInterval> | null = null;
  private stateTimer: ReturnType<typeof setInterval> | null = null;
  private previewDelay: ReturnType<typeof setTimeout> | null = null;

  ngOnInit() {
    this.refresh();
    this.previewTimer = setInterval(() => this.tickPreview(), 2500);
    this.stateTimer = setInterval(() => this.refresh(true), 5000);
  }
  ngOnDestroy() {
    if (this.previewTimer) clearInterval(this.previewTimer);
    if (this.stateTimer) clearInterval(this.stateTimer);
    if (this.previewDelay) clearTimeout(this.previewDelay);
  }
  refresh(silent = false) {
    this.api.screen().subscribe({
      next: (s) => {
        this.state = s;
        if (!silent) this.error = '';
        if (s.on !== false) this.tickPreview(true);
      },
      error: () => { if (!silent) this.error = '无法读取屏幕状态。'; }
    });
  }
  tickPreview(force = false) {
    if (!this.state || this.state.on === false) {
      return;
    }
    if (!force && this.imgError) return;
    this.imgError = false;
    this.snapshotUrl = '/api/screen/snapshot?t=' + Date.now();
  }
  onImgError() { this.imgError = true; }
  set(action: ScreenAction) {
    this.busy = true; this.okMsg = ''; this.error = '';
    this.api.setScreen(action).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) {
          this.state = r.screen;
          this.okMsg = this.actionMsg(action);
          this.schedulePreview(action === 'monitor' ? 1600 : 800);
        } else {
          this.error = r.error || '操作失败';
          if (r.screen) this.state = r.screen;
        }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  setBootMonitor(enabled: boolean) {
    this.busy = true; this.okMsg = ''; this.error = '';
    this.api.setScreen('boot-monitor', enabled).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) {
          this.state = r.screen;
          this.okMsg = enabled ? '已开启开机显示监控（下次开机生效）' : '已关闭开机显示监控';
        } else {
          this.error = r.error || '操作失败';
          if (r.screen) this.state = r.screen;
        }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  private schedulePreview(ms: number) {
    if (this.previewDelay) clearTimeout(this.previewDelay);
    this.previewDelay = setTimeout(() => this.tickPreview(true), ms);
  }
  powerLabel() {
    if (!this.state) return '未知';
    if (this.state.on === true) return '已开启';
    if (this.state.on === false) return '已关闭';
    return '未知';
  }
  modeLabel() {
    if (!this.state) return '';
    if (this.state.mode === 'monitor') return '监控页';
    if (this.state.mode === 'off') return '关屏';
    return '控制台';
  }
  actionMsg(action: ScreenAction) {
    if (action === 'on') return '已开屏';
    if (action === 'off') return '已关屏';
    if (action === 'console') return '已切换到控制台';
    if (action === 'monitor') return '已切换到监控页';
    return '已更新';
  }
  enabledLabel(v: string) {
    if (v === 'enabled') return '已写入开机自启';
    if (v === 'enabled-runtime') return '本次启动已开（尚未写入开机自启）';
    return v || '未开启';
  }
  bootMonitorLabel(v: string) {
    if (v === 'enabled') return '已写入开机自启';
    if (v === 'enabled-runtime') return '本次启动已开（尚未写入开机自启）';
    if (v === 'disabled') return '未开启（默认）';
    return v || '未开启';
  }
  burninLabel() {
    if (!this.state) return '';
    return this.state.burnin_protect === false ? '已关闭' : '已开启（默认）';
  }
  restLabel() {
    if (!this.state) return '';
    if (this.state.kiosk_resting) return '监控页休息中';
    if (this.state.mode === 'monitor' && this.state.burnin_protect !== false) return '监控页防烧屏生效中';
    if (this.state.burnin_protect === false) return '未启用';
    return '进入监控页后生效';
  }
  setBurnin(enabled: boolean) {
    this.busy = true; this.okMsg = ''; this.error = '';
    this.api.setScreen('burnin', enabled).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) {
          this.state = r.screen;
          this.okMsg = enabled ? '已开启防烧屏' : '已关闭防烧屏';
        } else {
          this.error = r.error || '操作失败';
          if (r.screen) this.state = r.screen;
        }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  setKioskBrightness(ev: Event) {
    const v = Number((ev.target as HTMLInputElement).value);
    if (!Number.isFinite(v)) return;
    this.busy = true; this.okMsg = ''; this.error = '';
    this.api.setScreen('kiosk-settings', undefined, { kiosk_brightness: Math.round(v) }).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) {
          this.state = r.screen;
          this.okMsg = '已更新监控页亮度';
        } else {
          this.error = r.error || '操作失败';
          if (r.screen) this.state = r.screen;
        }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  setRestInterval(sec: number) {
    this.patchSettings({ rest_interval_sec: sec }, '已更新休息间隔');
  }
  setRestDuration(sec: number) {
    this.patchSettings({ rest_duration_sec: sec }, '已更新休息时长');
  }
  setOrbit(enabled: boolean) {
    this.patchSettings({ orbit: enabled }, enabled ? '已开启像素微移' : '已关闭像素微移');
  }
  setRestEnabled(enabled: boolean) {
    this.patchSettings({ rest_enabled: enabled }, enabled ? '已开启定时休息' : '已关闭定时休息');
  }
  private patchSettings(extra: { kiosk_brightness?: number; rest_interval_sec?: number; rest_duration_sec?: number; orbit?: boolean; rest_enabled?: boolean }, ok: string) {
    this.busy = true; this.okMsg = ''; this.error = '';
    this.api.setScreen('kiosk-settings', undefined, extra).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) {
          this.state = r.screen;
          this.okMsg = ok;
        } else {
          this.error = r.error || '操作失败';
          if (r.screen) this.state = r.screen;
        }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
}
