import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Clipboard from 'expo-clipboard';
import { useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { RootStackParamList } from '../../app/navigation/types';
import { radius, spacing, useAppColors } from '../../app/theme';
import { Button, Field, InlineNotice, Panel, Screen, ScreenHeader } from '../../shared/ui/primitives';
import { QR_PREFIX } from './rendezvous';

type Props = NativeStackScreenProps<RootStackParamList, 'RingScan'>;

export function RingScanScreen({ navigation }: Props) {
  const colors = useAppColors();
  const [permission, requestPermission] = useCameraPermissions();
  const [text, setText] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const taken = useRef(false);

  function open(value: string) {
    const clean = value.trim();
    if (!clean.startsWith(QR_PREFIX)) {
      setNotice('Это не QR кольца p2pKanban.');
      return;
    }
    if (taken.current) return;
    taken.current = true;
    navigation.replace('RingMeeting', { qrText: clean });
  }

  return (
    <Screen scroll>
      <ScreenHeader title="Сканировать QR" subtitle="кольцо устройств" onBack={() => navigation.goBack()} />
      {notice ? <InlineNotice tone="danger" text={notice} /> : null}

      <Panel style={styles.panel}>
        {permission?.granted ? (
          <View style={[styles.cameraBox, { borderColor: colors.border }]}>
            <CameraView
              style={styles.camera}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
              onBarcodeScanned={({ data }) => open(data)}
            />
          </View>
        ) : (
          <>
            <Text style={[styles.caption, { color: colors.muted }]}>
              {permission && !permission.canAskAgain
                ? 'Доступ к камере запрещён. Разрешите его в настройках Android или вставьте текст QR ниже.'
                : 'Камера нужна только чтобы прочитать QR на экране узла. Снимки не сохраняются.'}
            </Text>
            {permission?.canAskAgain !== false ? (
              <Button label="Разрешить камеру" variant="primary" onPress={() => void requestPermission()} />
            ) : null}
          </>
        )}
      </Panel>

      <Panel style={styles.panel}>
        <Field label="Или вставьте текст QR" value={text} onChangeText={setText} autoCapitalize="none" autoCorrect={false}
          placeholder={`${QR_PREFIX}…`} hint="Узел показывает его под QR: «Скопировать текст QR»." />
        <View style={styles.row}>
          <Button label="Вставить из буфера" compact onPress={() => void Clipboard.getStringAsync().then(setText)} />
          <Button label="Открыть" variant="primary" compact disabled={!text.trim()} onPress={() => open(text)} />
        </View>
      </Panel>
    </Screen>
  );
}

const styles = StyleSheet.create({
  panel: { gap: spacing.md },
  caption: { fontSize: 13, lineHeight: 18 },
  cameraBox: { aspectRatio: 1, borderRadius: radius.md, overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth },
  camera: { flex: 1 },
  row: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
});
