import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export interface Overview {
  hostname: string;
  uptime: { seconds: number };
  load: { load1: string; load5: string; load15: string };
  memory: { total: number; used: number; available: number };
  disk: { total: number; used: number; available: number; mount: string };
  wifi: { ssid: string | null; device: string | null; ipv4: string | null; connected: boolean };
  wireguard_ipv4: string | null;
  wlan_ipv4: string | null;
  usb_ipv4: string | null;
  services: {
    ssh: { active: boolean; enabled: string };
    docker: { active: boolean; enabled: string };
    node_exporter: { active: boolean; enabled: string };
    wireguard: { active: boolean; enabled: string };
  };
  screen: ScreenState;
}

export type ScreenMode = 'off' | 'console' | 'monitor';
export type ScreenAction = 'on' | 'off' | 'console' | 'monitor' | 'boot-monitor' | 'burnin' | 'kiosk-settings';

export interface ScreenState {
  on: boolean | null;
  brightness: string | null;
  bl_power: string | null;
  screen_off_boot: string;
  screen_off_active: boolean;
  mode: ScreenMode;
  kiosk_active: boolean;
  kiosk_boot: string;
  burnin_protect?: boolean;
  orbit?: boolean;
  orbit_px?: number;
  rest_enabled?: boolean;
  rest_interval_sec?: number;
  rest_duration_sec?: number;
  kiosk_brightness?: number;
  kiosk_resting?: boolean;
}

export interface WifiCurrent {
  ssid: string | null;
  device: string | null;
  ipv4: string | null;
  connected: boolean;
}

export interface WifiNet {
  ssid: string;
  signal: number;
  security: string;
  in_use: boolean;
}

export interface ServicesState {
  ssh: { active: boolean; enabled: string };
  docker: { active: boolean; enabled: string; installed: boolean };
  node_exporter: { active: boolean; enabled: string };
  wireguard: { active: boolean; enabled: string; configured: boolean };
  screen_off: { active: boolean; enabled: string };
  docker_proxy: string | null;
  sys_proxy: string | null;
  hostname: string;
}

export interface ShareState {
  path: string;
  share_name: string;
  workgroup: string;
  username: string;
  read_only: boolean;
  ftp_anonymous_read: boolean;
  samba: {
    installed: boolean;
    active: boolean;
    enabled: string;
    nmbd_active: boolean;
    nmbd_enabled: string;
    password_set: boolean;
    ports: { tcp: number[]; udp: number[] };
  };
  ftp: {
    installed: boolean;
    active: boolean;
    enabled: string;
    anonymous_read: boolean;
    ports: { tcp: number[]; pasv: number[] };
  };
  connect: {
    samba_wg: string;
    samba_wg_uri: string;
    ftp_wg: string;
    samba_wifi: string | null;
    samba_wifi_uri: string | null;
    ftp_wifi: string | null;
    wg_ipv4: string;
    wlan_ipv4: string | null;
  };
}

export interface MountEntry {
  name: string;
  type: 'cifs' | 'nfs' | 'bind' | string;
  source: string;
  target: string;
  read_only: boolean;
  auto_boot: boolean;
  bind_to_share: boolean;
  share_subdir: string;
  share_bind: string | null;
  share_bound: boolean;
  username: string;
  has_credentials: boolean;
  mounted: boolean;
}

export interface MountsState {
  ok: boolean;
  mnt_root: string;
  mounts: MountEntry[];
}

export interface FileShortcut {
  id: string;
  label: string;
  path: string;
}

export interface FileEntry {
  name: string;
  type: 'dir' | 'file' | 'link' | 'device' | 'fifo' | 'socket' | 'other';
  size: number;
  mtime: number;
}

export interface FileList {
  ok: boolean;
  error?: string | null;
  requires_confirm?: boolean;
  uploaded?: string;
  path?: string;
  resolved?: string;
  read_only?: boolean;
  truncated?: boolean;
  entries?: FileEntry[];
  shortcuts?: FileShortcut[];
}

export interface HardwareState {
  gpu: {
    ready: boolean;
    status: string;
    devices: string[];
    frequency_hz: number | null;
    governor: string | null;
    available_frequencies: number[];
  };
  camera: { ready: boolean; status: string };
  sensors: { ready: boolean; status: string };
  nfc: { ready: boolean; status: string };
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  overview() { return this.http.get<Overview>('/api/overview'); }
  screen() { return this.http.get<ScreenState>('/api/screen'); }
  setScreen(action: ScreenAction, enabled?: boolean, extra?: {
    kiosk_brightness?: number;
    rest_interval_sec?: number;
    rest_duration_sec?: number;
    orbit?: boolean;
    rest_enabled?: boolean;
  }) {
    const body: {
      action: ScreenAction;
      enabled?: boolean;
      kiosk_brightness?: number;
      rest_interval_sec?: number;
      rest_duration_sec?: number;
      orbit?: boolean;
      rest_enabled?: boolean;
    } = { action };
    if (enabled !== undefined) body.enabled = enabled;
    if (extra?.kiosk_brightness !== undefined) body.kiosk_brightness = extra.kiosk_brightness;
    if (extra?.rest_interval_sec !== undefined) body.rest_interval_sec = extra.rest_interval_sec;
    if (extra?.rest_duration_sec !== undefined) body.rest_duration_sec = extra.rest_duration_sec;
    if (extra?.orbit !== undefined) body.orbit = extra.orbit;
    if (extra?.rest_enabled !== undefined) body.rest_enabled = extra.rest_enabled;
    return this.http.post<{ ok: boolean; error?: string | null; screen: ScreenState; output?: string }>('/api/screen', body);
  }
  wifi() { return this.http.get<{ current: WifiCurrent }>('/api/wifi'); }
  scanWifi() { return this.http.get<{ networks: WifiNet[]; current: WifiCurrent }>('/api/wifi/scan'); }
  connectWifi(ssid: string, password: string, hidden: boolean) {
    return this.http.post<{ ok: boolean; error?: string | null; current: WifiCurrent }>('/api/wifi/connect', { ssid, password, hidden });
  }
  services() { return this.http.get<ServicesState>('/api/services'); }
  setService(name: string, enabled: boolean, confirm?: string) {
    return this.http.post<{ ok: boolean; error?: string | null; requires_yes?: boolean; services: ServicesState; output?: string }>(
      '/api/services',
      { name, enabled, confirm }
    );
  }
  setHostname(hostname: string) {
    return this.http.post<{ ok: boolean; error?: string | null; hostname: string }>('/api/hostname', { hostname });
  }
  setProxy(kind: 'docker' | 'sys', url: string) {
    return this.http.post<{ ok: boolean; error?: string | null; services: ServicesState }>('/api/proxy', { kind, url });
  }
  hardware() { return this.http.get<HardwareState>('/api/hardware'); }
  share() { return this.http.get<ShareState>('/api/share'); }
  saveShare(body: Partial<ShareState>) {
    return this.http.post<{ ok: boolean; error?: string | null; share: ShareState }>('/api/share', body);
  }
  setSamba(body: { enabled?: boolean; password?: string; username?: string }) {
    return this.http.post<{ ok: boolean; error?: string | null; share: ShareState }>('/api/share/samba', body);
  }
  setFtp(body: { enabled?: boolean; ftp_anonymous_read?: boolean }) {
    return this.http.post<{ ok: boolean; error?: string | null; share: ShareState }>('/api/share/ftp', body);
  }
  mounts() { return this.http.get<MountsState>('/api/mounts'); }
  setMount(body: Record<string, unknown>) {
    return this.http.post<{ ok: boolean; error?: string | null; mounts: MountEntry[] }>('/api/mounts', body);
  }
  listFiles(path: string) {
    return this.http.get<FileList>('/api/files', { params: { path } });
  }
  mkdir(path: string, name: string) {
    return this.http.post<FileList>('/api/files/mkdir', { path, name });
  }
  renameFile(path: string, src: string, dest: string) {
    return this.http.post<FileList>('/api/files/rename', { path, src, dest });
  }
  deleteFile(path: string, name: string, recursive = false, confirm?: string) {
    return this.http.post<FileList>('/api/files/delete', { path, name, recursive, confirm });
  }
  uploadFile(path: string, file: File, overwrite: boolean) {
    const fd = new FormData();
    fd.append('path', path);
    fd.append('overwrite', overwrite ? '1' : '0');
    fd.append('file', file, file.name);
    return this.http.post<FileList>('/api/files/upload', fd);
  }
  downloadUrl(path: string) {
    return '/api/files/download?path=' + encodeURIComponent(path);
  }
}

