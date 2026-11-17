import { Component, OnInit, inject } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService, MountEntry, ShareState } from '../api.service';

@Component({
  selector: 'app-share',
  imports: [NgIf, NgFor, FormsModule, RouterLink],
  template: `
    <div class="page-head">
      <h2>文件共享</h2>
      <p>Samba 4 与 FTP、外部目录挂载。Samba / FTP 默认关闭，需在本页开启。</p>
    </div>
    <div class="error-banner" *ngIf="error">{{ error }}</div>
    <div class="msg ok" *ngIf="okMsg">{{ okMsg }}</div>

    <div class="card" *ngIf="state" style="margin-bottom:16px">
      <h3>共享目录</h3>
      <p class="hint">路径限于 /home/user、/srv/samba 或 /srv/ftp。保存时会创建目录并写入配置，但不会自动启动服务。</p>
      <form class="form-grid" (ngSubmit)="saveSettings()" style="max-width:560px">
        <div>
          <label>共享路径</label>
          <input type="text" [(ngModel)]="path" name="path" required>
        </div>
        <div>
          <label>共享名称</label>
          <input type="text" [(ngModel)]="shareName" name="shareName" required maxlength="32">
        </div>
        <div>
          <label>工作组</label>
          <input type="text" [(ngModel)]="workgroup" name="workgroup" required maxlength="16">
        </div>
        <div>
          <label>系统用户</label>
          <input type="text" [(ngModel)]="username" name="username" required maxlength="32">
        </div>
        <label style="display:flex;align-items:center;gap:8px;color:var(--text)">
          <input type="checkbox" [(ngModel)]="readOnly" name="readOnly"> 只读（Samba 与 FTP 写入一并关闭）
        </label>
        <div class="row">
          <button class="btn" type="submit" [disabled]="busy">保存设置</button>
        </div>
      </form>
    </div>

    <div class="grid grid-2" *ngIf="state">
      <div class="card">
        <h3>Samba 4</h3>
        <p class="hint">端口 TCP 445 / 139，UDP 137 / 138。开启时才会放行防火墙。游客写入默认关闭。</p>
        <dl class="kv">
          <dt>软件包</dt><dd>{{ state.samba.installed ? '已安装' : '未安装' }}</dd>
          <dt>状态</dt>
          <dd>
            <span class="pill" [class.ok]="state.samba.active" [class.muted]="!state.samba.active">{{ state.samba.active ? '运行中' : '未运行' }}</span>
            <span class="metric-sub" style="margin-left:8px">开机 {{ enabledLabel(state.samba.enabled) }}</span>
          </dd>
          <dt>密码</dt><dd>{{ state.samba.password_set ? '已设置' : '尚未设置（开启前必须设置）' }}</dd>
        </dl>
        <form class="form-grid" style="margin-top:14px" (ngSubmit)="saveSambaPassword()">
          <div>
            <label>设置 / 更新 Samba 密码（不会回显，也不同于系统登录密码）</label>
            <input type="password" [(ngModel)]="sambaPassword" name="sambaPassword" maxlength="63" autocomplete="new-password">
          </div>
          <div class="row">
            <button class="btn ghost" type="submit" [disabled]="busy || !sambaPassword">保存密码</button>
            <button class="btn" type="button" [disabled]="busy || !state.samba.installed" *ngIf="!state.samba.active" (click)="toggleSamba(true)">开启 Samba</button>
            <button class="btn bad" type="button" [disabled]="busy" *ngIf="state.samba.active" (click)="toggleSamba(false)">关闭 Samba</button>
          </div>
        </form>
        <div style="margin-top:16px">
          <div class="metric-sub">连接路径</div>
          <dl class="kv" style="margin-top:8px">
            <dt>WireGuard</dt><dd><code>{{ state.connect.samba_wg }}</code></dd>
            <dt>Wi-Fi</dt><dd><code *ngIf="state.connect.samba_wifi">{{ state.connect.samba_wifi }}</code><span *ngIf="!state.connect.samba_wifi">当前没有 Wi-Fi 地址</span></dd>
            <dt>URI</dt><dd><code>{{ state.connect.samba_wg_uri }}</code></dd>
          </dl>
        </div>
      </div>

      <div class="card">
        <h3>FTP（vsftpd）</h3>
        <p class="hint">端口 21，被动端口 50000–50010。用户限制在共享目录内。使用系统用户 {{ state.username }} 的登录密码，本页不会修改系统密码。匿名写入关闭。</p>
        <dl class="kv">
          <dt>软件包</dt><dd>{{ state.ftp.installed ? '已安装' : '未安装' }}</dd>
          <dt>状态</dt>
          <dd>
            <span class="pill" [class.ok]="state.ftp.active" [class.muted]="!state.ftp.active">{{ state.ftp.active ? '运行中' : '未运行' }}</span>
            <span class="metric-sub" style="margin-left:8px">开机 {{ enabledLabel(state.ftp.enabled) }}</span>
          </dd>
        </dl>
        <label style="display:flex;align-items:center;gap:8px;margin:12px 0;color:var(--text)">
          <input type="checkbox" [(ngModel)]="anonRead" name="anonRead"> 允许匿名只读（默认关闭，仍禁止匿名写入）
        </label>
        <div class="row">
          <button class="btn ghost" type="button" [disabled]="busy" (click)="saveAnon()">保存匿名选项</button>
          <button class="btn" type="button" [disabled]="busy || !state.ftp.installed" *ngIf="!state.ftp.active" (click)="toggleFtp(true)">开启 FTP</button>
          <button class="btn bad" type="button" [disabled]="busy" *ngIf="state.ftp.active" (click)="toggleFtp(false)">关闭 FTP</button>
        </div>
        <div style="margin-top:16px">
          <div class="metric-sub">连接地址</div>
          <dl class="kv" style="margin-top:8px">
            <dt>WireGuard</dt><dd><code>{{ state.connect.ftp_wg }}</code></dd>
            <dt>Wi-Fi</dt><dd><code *ngIf="state.connect.ftp_wifi">{{ state.connect.ftp_wifi }}</code><span *ngIf="!state.connect.ftp_wifi">当前没有 Wi-Fi 地址</span></dd>
          </dl>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <h3>外部目录挂载</h3>
      <p class="hint">将 CIFS/SMB、NFS 或本机目录挂载到 <code>/home/user/mnt/名称</code>。凭据只保存在设备上，接口不会返回密码。开机自动挂载为可选项。</p>
      <form class="form-grid mount-form" (ngSubmit)="addMount()">
        <div>
          <label>名称</label>
          <input type="text" [(ngModel)]="mntName" name="mntName" required maxlength="32" placeholder="例如 testdir">
        </div>
        <div>
          <label>类型</label>
          <select [(ngModel)]="mntType" name="mntType">
            <option value="bind">本地绑定</option>
            <option value="cifs">CIFS / SMB</option>
            <option value="nfs">NFS</option>
          </select>
        </div>
        <div class="span-2">
          <label>源路径</label>
          <input type="text" [(ngModel)]="mntSource" name="mntSource" required [placeholder]="sourcePlaceholder()">
        </div>
        <div *ngIf="mntType === 'cifs'">
          <label>用户名（可空，空则尝试访客）</label>
          <input type="text" [(ngModel)]="mntUser" name="mntUser" maxlength="64" autocomplete="off">
        </div>
        <div *ngIf="mntType === 'cifs'">
          <label>密码（不会在列表中回显）</label>
          <input type="password" [(ngModel)]="mntPassword" name="mntPassword" maxlength="128" autocomplete="new-password">
        </div>
        <label style="display:flex;align-items:center;gap:8px;color:var(--text)">
          <input type="checkbox" [(ngModel)]="mntReadOnly" name="mntReadOnly"> 只读
        </label>
        <label style="display:flex;align-items:center;gap:8px;color:var(--text)">
          <input type="checkbox" [(ngModel)]="mntAutoBoot" name="mntAutoBoot"> 开机自动挂载
        </label>
        <label class="span-2" style="display:flex;align-items:center;gap:8px;color:var(--text)">
          <input type="checkbox" [(ngModel)]="mntBindShare" name="mntBindShare"> 同时绑定到共享子目录，供 Samba / FTP 使用
        </label>
        <div *ngIf="mntBindShare">
          <label>共享子目录名</label>
          <input type="text" [(ngModel)]="mntShareSub" name="mntShareSub" maxlength="32" [placeholder]="mntName || '与挂载名称相同'">
        </div>
        <div class="row span-2">
          <button class="btn" type="submit" [disabled]="busy || !mntName || !mntSource">添加并挂载</button>
        </div>
      </form>

      <table *ngIf="mounts.length" style="margin-top:16px">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>源</th>
            <th>状态</th>
            <th>选项</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let m of mounts">
            <td>
              <strong>{{ m.name }}</strong>
              <div class="metric-sub"><code>{{ m.target }}</code></div>
            </td>
            <td>{{ typeLabel(m.type) }}</td>
            <td class="src-cell">{{ m.source }}</td>
            <td>
              <span class="pill" [class.ok]="m.mounted" [class.muted]="!m.mounted">{{ m.mounted ? '已挂载' : '未挂载' }}</span>
              <div class="metric-sub" *ngIf="m.bind_to_share">共享 {{ m.share_bound ? '已绑定' : '未绑定' }} · {{ m.share_subdir }}</div>
            </td>
            <td>
              <div class="metric-sub">{{ m.read_only ? '只读' : '可写' }}{{ m.auto_boot ? ' · 开机自动' : '' }}{{ m.has_credentials ? ' · 已保存凭据' : '' }}</div>
            </td>
            <td>
              <div class="row" style="justify-content:flex-end">
                <button class="btn ghost" type="button" [disabled]="busy || m.mounted" (click)="mountAction('mount', m.name)">挂载</button>
                <button class="btn ghost" type="button" [disabled]="busy || !m.mounted" (click)="mountAction('unmount', m.name)">卸载</button>
                <button class="btn" type="button" [disabled]="busy" (click)="toggleAuto(m)">{{ m.auto_boot ? '取消开机自动' : '开机自动挂载' }}</button>
                <button class="btn bad" type="button" [disabled]="busy" (click)="mountAction('remove', m.name)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="hint" *ngIf="!mounts.length" style="margin-top:12px">还没有挂载项。可先用「本地绑定」把已有目录挂到 /home/user/mnt/ 下。</p>
    </div>

    <p class="hint" style="margin-top:16px">浏览、上传或删除文件请到「<a routerLink="/files">文件管理</a>」菜单，可访问整台设备。</p>
  `
})
export class ShareComponent implements OnInit {
  private api = inject(ApiService);
  state: ShareState | null = null;
  mounts: MountEntry[] = [];
  error = '';
  okMsg = '';
  busy = false;
  path = '';
  shareName = '';
  workgroup = '';
  username = '';
  readOnly = false;
  anonRead = false;
  sambaPassword = '';

  mntName = '';
  mntType: 'bind' | 'cifs' | 'nfs' = 'bind';
  mntSource = '';
  mntUser = '';
  mntPassword = '';
  mntReadOnly = false;
  mntAutoBoot = false;
  mntBindShare = false;
  mntShareSub = '';


  ngOnInit() {
    this.refresh();
    this.refreshMounts();
  }

  refresh() {
    this.api.share().subscribe({
      next: (s) => { this.applyState(s); this.error = ''; },
      error: () => { this.error = '无法读取文件共享状态。'; }
    });
  }

  refreshMounts() {
    this.api.mounts().subscribe({
      next: (s) => { this.mounts = s.mounts || []; },
      error: () => { /* keep share usable even if mounts fail */ }
    });
  }


  applyState(s: ShareState) {
    this.state = s;
    this.path = s.path;
    this.shareName = s.share_name;
    this.workgroup = s.workgroup;
    this.username = s.username;
    this.readOnly = s.read_only;
    this.anonRead = s.ftp_anonymous_read;
  }

  enabledLabel(v: string) {
    if (v === 'enabled') return '已自启';
    if (v === 'enabled-runtime') return '本次已开';
    return '未自启';
  }

  typeLabel(t: string) {
    if (t === 'cifs') return 'CIFS / SMB';
    if (t === 'nfs') return 'NFS';
    if (t === 'bind') return '本地绑定';
    return t;
  }
  typeFileLabel(t: string) {
    if (t === 'dir') return '目录';
    if (t === 'file') return '文件';
    if (t === 'link') return '链接';
    return t;
  }
  sourcePlaceholder() {
    if (this.mntType === 'cifs') return '//192.168.1.10/share';
    if (this.mntType === 'nfs') return '192.168.1.10:/export';
    return '/home/user/某个已存在的目录';
  }

  saveSettings() {
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.saveShare({
      path: this.path,
      share_name: this.shareName,
      workgroup: this.workgroup,
      username: this.username,
      read_only: this.readOnly,
      ftp_anonymous_read: this.anonRead,
    } as Partial<ShareState>).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) { this.applyState(r.share); this.okMsg = '共享设置已保存'; }
        else this.error = r.error || '保存失败';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }

  saveSambaPassword() {
    if (!this.sambaPassword) return;
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setSamba({ password: this.sambaPassword, username: this.username }).subscribe({
      next: (r) => {
        this.busy = false;
        this.sambaPassword = '';
        if (r.ok) { this.applyState(r.share); this.okMsg = 'Samba 密码已更新'; }
        else this.error = r.error || '设置密码失败';
      },
      error: () => { this.busy = false; this.sambaPassword = ''; this.error = '请求失败。'; }
    });
  }

  toggleSamba(enabled: boolean) {
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setSamba({ enabled }).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) { this.applyState(r.share); this.okMsg = enabled ? 'Samba 已开启' : 'Samba 已关闭'; }
        else this.error = r.error || '操作失败';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }

  saveAnon() {
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setFtp({ ftp_anonymous_read: this.anonRead }).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) { this.applyState(r.share); this.okMsg = '匿名只读选项已保存'; }
        else this.error = r.error || '保存失败';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }

  toggleFtp(enabled: boolean) {
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setFtp({ enabled, ftp_anonymous_read: this.anonRead }).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) { this.applyState(r.share); this.okMsg = enabled ? 'FTP 已开启' : 'FTP 已关闭'; }
        else this.error = r.error || '操作失败';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }

  addMount() {
    this.busy = true; this.error = ''; this.okMsg = '';
    const body: Record<string, unknown> = {
      action: 'add',
      name: this.mntName.trim(),
      type: this.mntType,
      source: this.mntSource.trim(),
      read_only: this.mntReadOnly,
      auto_boot: this.mntAutoBoot,
      bind_to_share: this.mntBindShare,
    };
    if (this.mntBindShare) body['share_subdir'] = (this.mntShareSub || this.mntName).trim();
    if (this.mntType === 'cifs') {
      body['username'] = this.mntUser.trim();
      if (this.mntPassword) body['password'] = this.mntPassword;
    }
    this.api.setMount(body).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.ok) {
          this.mounts = r.mounts || [];
          this.okMsg = '已添加并尝试挂载';
          this.mntPassword = '';
        } else this.error = r.error || '挂载失败';
        if (r.mounts) this.mounts = r.mounts;
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }

  mountAction(action: 'mount' | 'unmount' | 'remove', name: string) {
    if (action === 'remove' && !confirm('确定删除挂载“' + name + '”吗？会先卸载，不会删除源目录。')) return;
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setMount({ action, name }).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.mounts) this.mounts = r.mounts;
        if (r.ok) {
          this.okMsg = action === 'mount' ? '已挂载' : action === 'unmount' ? '已卸载' : '已删除';
        } else this.error = r.error || '操作失败';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }

  toggleAuto(m: MountEntry) {
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.setMount({ action: 'update', name: m.name, auto_boot: !m.auto_boot }).subscribe({
      next: (r) => {
        this.busy = false;
        if (r.mounts) this.mounts = r.mounts;
        if (r.ok) this.okMsg = !m.auto_boot ? '已开启开机自动挂载' : '已关闭开机自动挂载';
        else this.error = r.error || '操作失败';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }

}
