import { Component, OnInit, inject } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, FileEntry, FileList, FileShortcut } from '../api.service';

@Component({
  selector: 'app-files-page',
  imports: [NgIf, NgFor, FormsModule],
  template: `
    <div class="page-head">
      <h2>文件管理</h2>
      <p>可以浏览整台设备的文件系统。请谨慎写入或删除，误操作可能影响系统。</p>
    </div>
    <div class="error-banner" *ngIf="error">{{ error }}</div>
    <div class="msg ok" *ngIf="okMsg">{{ okMsg }}</div>

    <div class="card">
      <div class="row" style="margin-bottom:12px;flex-wrap:wrap">
        <button class="btn ghost" type="button" *ngFor="let s of shortcuts" (click)="goPath(s.path)">{{ s.label }}</button>
      </div>
      <form class="row" style="margin-bottom:12px" (ngSubmit)="goTyped()">
        <input type="text" [(ngModel)]="typedPath" name="typedPath" placeholder="输入绝对路径，例如 /etc" style="max-width:420px;flex:1">
        <button class="btn" type="submit" [disabled]="busy || !typedPath">前往</button>
      </form>
      <div class="crumb">
        <button class="btn ghost" type="button" (click)="goPath('/')">/</button>
        <ng-container *ngFor="let c of crumbs(); let i = index">
          <span class="crumb-sep">/</span>
          <button class="btn ghost" type="button" (click)="goPath(crumbPath(i))">{{ c }}</button>
        </ng-container>
      </div>
      <p class="hint" *ngIf="fmPath">当前：<code>{{ fmPath }}</code><span *ngIf="fmReadOnly"> · 只读</span></p>
      <p class="hint" *ngIf="truncated">目录条目过多，只显示了前 {{ entries.length }} 项。</p>

      <div class="row" style="margin-bottom:12px" *ngIf="!fmReadOnly">
        <input type="text" [(ngModel)]="newDir" name="newDir" placeholder="新目录名称" style="max-width:220px">
        <button class="btn ghost" type="button" [disabled]="busy || !newDir" (click)="makeDir()">新建目录</button>
        <label class="btn ghost" style="margin:0">
          上传文件
          <input type="file" (change)="onUpload($event)" [disabled]="busy" style="display:none">
        </label>
        <label style="display:flex;align-items:center;gap:6px;color:var(--text);margin:0">
          <input type="checkbox" [(ngModel)]="overwrite" name="overwrite"> 允许覆盖同名文件
        </label>
      </div>
      <p class="hint" *ngIf="fmReadOnly">当前路径不可写入（只读文件系统，或位于 /proc、/sys、/dev、/run）。</p>

      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>大小</th>
            <th>修改时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr *ngIf="!entries.length">
            <td colspan="5" class="metric-sub">目录为空或无法列出条目</td>
          </tr>
          <tr *ngFor="let f of entries">
            <td>
              <button *ngIf="f.type === 'dir' || f.type === 'link'" class="linkish" type="button" (click)="enter(f)">{{ f.name }}</button>
              <span *ngIf="f.type !== 'dir' && f.type !== 'link'">{{ f.name }}</span>
            </td>
            <td>{{ typeLabel(f.type) }}</td>
            <td>{{ f.type === 'dir' ? '—' : fmtSize(f.size) }}</td>
            <td>{{ fmtTime(f.mtime) }}</td>
            <td>
              <div class="row" style="justify-content:flex-end" *ngIf="renaming !== f.name">
                <a *ngIf="canDownload(f)" class="btn ghost" [href]="downloadHref(f.name)">下载</a>
                <button class="btn ghost" type="button" [disabled]="busy || fmReadOnly" (click)="startRename(f)">重命名</button>
                <button class="btn bad" type="button" [disabled]="busy || fmReadOnly" (click)="removeEntry(f)">删除</button>
              </div>
              <div class="row" *ngIf="renaming === f.name">
                <input type="text" [(ngModel)]="renameTo" [name]="'rename-'+f.name" style="max-width:160px">
                <button class="btn" type="button" [disabled]="busy || !renameTo" (click)="confirmRename(f)">确定</button>
                <button class="btn ghost" type="button" (click)="renaming=''; renameTo=''">取消</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `
})
export class FilesComponent implements OnInit {
  private api = inject(ApiService);
  error = '';
  okMsg = '';
  busy = false;
  fmPath = '/home/user';
  typedPath = '/home/user';
  fmReadOnly = false;
  truncated = false;
  entries: FileEntry[] = [];
  shortcuts: FileShortcut[] = [];
  newDir = '';
  overwrite = false;
  renaming = '';
  renameTo = '';

  ngOnInit() { this.refresh('/home/user'); }

  refresh(path = this.fmPath) {
    this.busy = true;
    this.api.listFiles(path).subscribe({
      next: (s) => { this.busy = false; this.apply(s); },
      error: () => { this.busy = false; this.error = '无法读取目录。'; }
    });
  }

  apply(s: FileList) {
    if (s.shortcuts) this.shortcuts = s.shortcuts;
    if (s.ok === false) {
      this.error = s.error || '无法读取目录。';
      return;
    }
    this.error = '';
    this.fmPath = s.path || s.resolved || this.fmPath;
    this.typedPath = this.fmPath;
    this.fmReadOnly = !!s.read_only;
    this.truncated = !!s.truncated;
    this.entries = s.entries || [];
  }

  crumbs() {
    if (!this.fmPath || this.fmPath === '/') return [];
    return this.fmPath.split('/').filter(Boolean);
  }
  crumbPath(i: number) {
    return '/' + this.crumbs().slice(0, i + 1).join('/');
  }
  goPath(path: string) {
    this.renaming = '';
    this.okMsg = '';
    this.refresh(path || '/');
  }
  goTyped() {
    const p = (this.typedPath || '').trim();
    if (!p) return;
    this.goPath(p.startsWith('/') ? p : '/' + p);
  }
  enter(f: FileEntry) {
    const next = this.fmPath === '/' ? '/' + f.name : this.fmPath + '/' + f.name;
    this.goPath(next);
  }
  makeDir() {
    const name = this.newDir.trim();
    if (!name) return;
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.mkdir(this.fmPath, name).subscribe({
      next: (s) => {
        this.busy = false;
        this.apply(s);
        if (s.ok !== false) { this.okMsg = '已创建目录'; this.newDir = ''; }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  onUpload(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const file = input.files && input.files[0];
    if (!file) return;
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.uploadFile(this.fmPath, file, this.overwrite).subscribe({
      next: (s) => {
        this.busy = false;
        input.value = '';
        this.apply(s);
        if (s.ok !== false) this.okMsg = '已上传 ' + (s.uploaded || file.name);
      },
      error: () => { this.busy = false; input.value = ''; this.error = '上传失败。'; }
    });
  }
  startRename(f: FileEntry) {
    this.renaming = f.name;
    this.renameTo = f.name;
  }
  confirmRename(f: FileEntry) {
    const dest = this.renameTo.trim();
    if (!dest || dest === f.name) { this.renaming = ''; return; }
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.renameFile(this.fmPath, f.name, dest).subscribe({
      next: (s) => {
        this.busy = false;
        this.apply(s);
        if (s.ok !== false) { this.okMsg = '已重命名'; this.renaming = ''; this.renameTo = ''; }
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  removeEntry(f: FileEntry) {
    const isDir = f.type === 'dir';
    if (isDir) {
      if (!confirm('确定递归删除目录“' + f.name + '”及其全部内容吗？')) return;
    } else if (!confirm('确定删除“' + f.name + '”吗？')) {
      return;
    }
    this.busy = true; this.error = ''; this.okMsg = '';
    this.api.deleteFile(this.fmPath, f.name, isDir, isDir ? 'YES' : undefined).subscribe({
      next: (s) => {
        this.busy = false;
        this.apply(s);
        if (s.ok !== false) this.okMsg = '已删除';
      },
      error: () => { this.busy = false; this.error = '请求失败。'; }
    });
  }
  canDownload(f: FileEntry) {
    return f.type === 'file' || f.type === 'link';
  }
  downloadHref(name: string) {
    const rel = this.fmPath === '/' ? '/' + name : this.fmPath + '/' + name;
    return this.api.downloadUrl(rel);
  }
  typeLabel(t: string) {
    const map: Record<string, string> = {
      dir: '目录', file: '文件', link: '链接', device: '设备', fifo: '管道', socket: '套接字', other: '其他',
    };
    return map[t] || t;
  }
  fmtSize(n: number) {
    if (n < 1024) return n + ' B';
    const units = ['KB', 'MB', 'GB', 'TB'];
    let v = n / 1024, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return v.toFixed(v >= 10 ? 0 : 1) + ' ' + units[i];
  }
  fmtTime(ts: number) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    const p = (x: number) => (x < 10 ? '0' + x : '' + x);
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }
}
