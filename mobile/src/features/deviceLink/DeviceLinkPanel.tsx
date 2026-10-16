import { useEffect, useRef, useState } from 'react';
import { Alert, Text, View } from 'react-native';
import { useAppColors } from '../../app/theme';
import { Button, ErrorDetails, Field, InlineNotice, Panel } from '../../shared/ui/primitives';
import { useAuth } from '../auth/AuthProvider';
import {
  approveDevice,
  approveNearbyDevice,
  fetchNearbyRequest,
  deviceFingerprint,
  preparationInfo,
  prepareDeviceLink,
  probePreparedRelays,
} from './service';
import { checkRequest } from './protocol';
import { isSyncCanceled } from '../../shared/lib/uiBudget';
export function DeviceLinkPanel() {
  const colors = useAppColors(),
    { user } = useAuth();
  const [expanded, setExpanded] = useState(false),
    [request, setRequest] = useState(''),
    [nearbyAddress, setNearbyAddress] = useState(''),
    [busy, setBusy] = useState(false),
    [status, setStatus] = useState(''),
    [failure, setFailure] = useState<unknown>(undefined),
    [fingerprint, setFingerprint] = useState('');
  // One operation at a time; leaving Settings or «Отменить» stops it between steps.
  const operation = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; operation.current?.abort(); };
  }, []);
  async function refresh() {
    const key = await deviceFingerprint();
    const info = await preparationInfo();
    if (!mounted.current) return;
    setFingerprint(key);
    setStatus(
      info
        ? `Подготовлено ${info.boards} досок · ${info.exportedAt}. Право до ${new Date(info.expiresAt * 1000).toLocaleDateString()}.`
        : 'Подключение ещё не подготовлено.',
    );
  }
  useEffect(() => {
    if (expanded) void refresh().catch((e) => {
      if (!mounted.current) return;
      setStatus(e instanceof Error ? e.message : String(e)); setFailure(e);
    });
  }, [expanded]);
  async function run(action: (signal: AbortSignal) => Promise<unknown>) {
    if (operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setFailure(undefined);
    try {
      await action(controller.signal);
    } catch (e) {
      if (!mounted.current) return;
      if (controller.signal.aborted || isSyncCanceled(e)) setStatus('Отменено.');
      else {
        setStatus(e instanceof Error ? e.message : String(e));
        setFailure(e);
      }
    } finally {
      if (operation.current === controller) operation.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  function cancel() {
    operation.current?.abort();
  }
  function confirm() {
    try {
      const checked = checkRequest(JSON.parse(request));
      Alert.alert(
        'Разрешить самостоятельный узел?',
        `Сверьте полный отпечаток запроса на ноутбуке:\n${checked.id}\n\nБудут переданы ваши пространства владельца, данные и право подключать другие устройства от вашего имени. Телефон не станет посредником.`,
        [
          { text: 'Отмена', style: 'cancel' },
          {
            text: 'Совпадает · разрешить',
            onPress: () => {
              void run(async (signal) => {
                if (!user) throw new Error('Нужен аккаунт.');
                setStatus('Готовим разрешение… Можно отменить.');
                if (nearbyAddress.trim()) await approveNearbyDevice(request, user.id, nearbyAddress, signal);
                else await approveDevice(request, user.id, undefined, signal);
                if (!mounted.current) return;
                setStatus(
                  nearbyAddress.trim() ? 'Разрешение доставлено ноутбуку. После подключения телефон больше не нужен.' : 'Передайте зашифрованный файл ноутбуку до истечения 10 минут.',
                );
              });
            },
          },
        ],
      );
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <Panel>
      <Button
        label="Подключить другое устройство"
        onPress={() => {
          // Folding the panel is "I changed my mind": the running step stops too.
          if (expanded) cancel();
          setExpanded(!expanded);
        }}
      />
      {expanded && (
        <View style={{ gap: 12 }}>
          <Text style={{ color: colors.text }}>
            Доступ и локальные реплики дополняются через relay. После первой
            подготовки владелец может подключить ноутбук без PC-node. На
            ноутбуке нужен p2pKanban v2. Для первого подключения нужна пустая
            база; для новых досок — режим дополнения.
          </Text>
          <Button
            label="Обновить доступ через доступный узел"
            disabled={busy}
            onPress={() => {
              void run(async (signal) => {
                await prepareDeviceLink({ refresh: true, signal });
                await refresh();
              });
            }}
          />
          <Button label="Проверить relay без ПК" disabled={busy}
            onPress={() => { void run(async () => {
              const report = await probePreparedRelays();
              if (mounted.current) setStatus(report);
            }); }} />
          {busy ? <Button label="Отменить" variant="ghost" onPress={cancel} /> : null}
          <InlineNotice text={status} tone="neutral" />
          {failure !== undefined ? <ErrorDetails message={status} error={failure} operation="Подключение устройства" /> : null}
          <Text selectable style={{ color: colors.text }}>
            Ключ этого устройства — сверьте на ноутбуке:\n{fingerprint}
          </Text>
          <Field label="IP:порт ноутбука в локальной сети" value={nearbyAddress}
            onChangeText={setNearbyAddress} editable={!busy} placeholder="192.168.1.42:8080" />
          <Button label="Получить запрос с ноутбука" disabled={busy || !nearbyAddress.trim()}
            onPress={() => { void run(async (signal) => {
              setStatus('Спрашиваем ноутбук… Можно отменить.');
              const pending = await fetchNearbyRequest(nearbyAddress, signal);
              if (!mounted.current) return;
              setRequest(JSON.stringify(pending));
              setStatus('Запрос найден. Сверьте отпечаток с экраном ноутбука и разрешите.');
            }); }} />
          <Field
            label="Запрос с ноутбука (JSON)"
            multiline
            value={request}
            onChangeText={setRequest}
            editable={!busy}
          />
          <Button
            label="Проверить и разрешить"
            disabled={busy || !request.trim()}
            onPress={confirm}
          />
          <Text style={{ color: colors.muted }}>
            Файл зашифрован, пароли и master secrets не передаются. Структура и
            комментарии берутся из подготовленного снимка; карточки и чек-листы
            — из локальной копии. При изменении прав обновите подготовку.
          </Text>
        </View>
      )}
    </Panel>
  );
}
