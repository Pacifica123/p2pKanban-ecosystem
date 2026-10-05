import { DeviceLinkPanel } from './DeviceLinkPanel';
import { NetworkConnect } from './NetworkConnect';

export function NetworkPage() {
  return <div className="page-shell">
    <header className="page-header"><h2>Сеть и доверенные устройства</h2></header>
    <p>В одной локальной сети укажите IP:порт другого web-узла. После подтверждения
      устройства самостоятельно обмениваются изменениями через настроенные relay.</p>
    <NetworkConnect />
    <DeviceLinkPanel />
    <DeviceLinkPanel destination supplement />
    <p className="muted">Для первого подключения пустого узла откройте страницу входа на новом устройстве.
      Ручная передача JSON остаётся доступной, если прямое LAN-соединение невозможно.</p>
  </div>;
}
