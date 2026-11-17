import { Routes } from '@angular/router';
import { OverviewComponent } from './pages/overview.component';
import { ScreenPageComponent } from './pages/screen.component';
import { WifiComponent } from './pages/wifi.component';
import { ServicesComponent } from './pages/services.component';
import { HardwareComponent } from './pages/hardware.component';
import { ShareComponent } from './pages/share.component';
import { FilesComponent } from './pages/files.component';

export const routes: Routes = [
  { path: '', redirectTo: 'overview', pathMatch: 'full' },
  { path: 'overview', component: OverviewComponent },
  { path: 'screen', component: ScreenPageComponent },
  { path: 'wifi', component: WifiComponent },
  { path: 'services', component: ServicesComponent },
  { path: 'share', component: ShareComponent },
  { path: 'files', component: FilesComponent },
  { path: 'hardware', component: HardwareComponent },
  { path: '**', redirectTo: 'overview' },
];
