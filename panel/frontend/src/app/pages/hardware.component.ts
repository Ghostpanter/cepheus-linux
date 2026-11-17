import { Component, OnInit, inject } from '@angular/core';
import { NgIf } from '@angular/common';
import { ApiService, HardwareState } from '../api.service';

@Component({
  selector: 'app-hardware',
  imports: [NgIf],
  template: `
    <div class="page-head">
      <h2>硬件</h2>
      <p>只显示当前能确认的状态，不会提供无法生效的开启按钮。</p>
    </div>
    <div class="error-banner" *ngIf="error">{{ error }}</div>
    <div class="grid grid-2" *ngIf="hw">
      <div class="card">
        <h3>GPU</h3>
        <div class="metric">{{ hw.gpu.status }}</div>
        <dl class="kv" style="margin-top:12px">
          <dt>设备</dt><dd>{{ hw.gpu.devices.length ? hw.gpu.devices.join(', ') : '—' }}</dd>
          <dt>当前频率</dt><dd>{{ hw.gpu.frequency_hz ? formatHz(hw.gpu.frequency_hz) : '—' }}</dd>
          <dt>调速器</dt><dd>{{ hw.gpu.governor || '—' }}</dd>
          <dt>可用频率</dt>
          <dd>{{ freqList(hw.gpu.available_frequencies) }}</dd>
        </dl>
      </div>
      <div class="card">
        <h3>摄像头</h3>
        <div class="hw-note">{{ hw.camera.status }}</div>
      </div>
      <div class="card">
        <h3>传感器</h3>
        <div class="hw-note">{{ hw.sensors.status }}</div>
      </div>
      <div class="card">
        <h3>NFC</h3>
        <div class="hw-note">{{ hw.nfc.status }}</div>
      </div>
    </div>
  `
})
export class HardwareComponent implements OnInit {
  private api = inject(ApiService);
  hw: HardwareState | null = null;
  error = '';
  ngOnInit() {
    this.api.hardware().subscribe({
      next: (h) => this.hw = h,
      error: () => { this.error = '无法读取硬件状态。'; }
    });
  }
  formatHz(hz: number) {
    if (hz >= 1_000_000) return `${(hz / 1_000_000).toFixed(hz % 1_000_000 === 0 ? 0 : 1)} MHz`;
    if (hz >= 1_000) return `${Math.round(hz / 1_000)} kHz`;
    return `${hz} Hz`;
  }
  freqList(freq: number[]) {
    return freq.length ? freq.map((hz) => this.formatHz(hz)).join(' / ') : '—';
  }
}
