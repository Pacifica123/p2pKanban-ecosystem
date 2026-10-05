import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { radius, spacing, useAppColors, useResolvedTheme } from '../../app/theme';
import type {
  BoardAppearanceSettings,
  CardPreviewMode,
  Density,
  UpdateBoardAppearanceRequest,
  WallpaperKind,
} from '../../shared/types/api';
import {
  Button,
  Field,
  FormModal,
  InlineNotice,
  SectionTitle,
} from '../../shared/ui/primitives';
import {
  boardThemePresets,
  boardWallpaperPresets,
  resolveBoardPalette,
  validHex,
} from './boardTheme';

function Choice<T extends string>({
  label,
  value,
  selected,
  swatch,
  onPress,
}: {
  label: string;
  value: T;
  selected: T;
  swatch?: string;
  onPress: (value: T) => void;
}) {
  const colors = useAppColors();
  const active = value === selected;
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: active }}
      onPress={() => onPress(value)}
      style={({ pressed }) => [
        styles.choice,
        {
          backgroundColor: active ? colors.accentSoft : colors.surface,
          borderColor: active ? colors.accent : colors.border,
          opacity: pressed ? 0.66 : 1,
        },
      ]}
    >
      {swatch ? <View style={[styles.swatch, { backgroundColor: swatch }]} /> : null}
      <Text style={[styles.choiceText, { color: active ? colors.accent : colors.text }]}>
        {label}
      </Text>
    </Pressable>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  const colors = useAppColors();
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      onPress={() => onChange(!value)}
      style={({ pressed }) => [styles.toggle, { opacity: pressed ? 0.66 : 1 }]}
    >
      <Text style={[styles.toggleLabel, { color: colors.text }]}>{label}</Text>
      <View style={[
        styles.toggleTrack,
        { backgroundColor: value ? colors.accent : colors.surfaceMuted },
      ]}>
        <View style={[
          styles.toggleThumb,
          {
            backgroundColor: value ? colors.background : colors.muted,
            transform: [{ translateX: value ? 16 : 0 }],
          },
        ]} />
      </View>
    </Pressable>
  );
}

const wallpaperKinds: Array<{ value: WallpaperKind; label: string }> = [
  { value: 'none', label: 'По схеме' },
  { value: 'accent', label: 'От акцента' },
  { value: 'preset', label: 'Готовый' },
  { value: 'solid', label: 'Цвет' },
  { value: 'gradient', label: 'Градиент' },
  { value: 'image', label: 'Изображение' },
];

function wallpaperFor(kind: WallpaperKind) {
  if (kind === 'none' || kind === 'accent') return { kind, value: null };
  if (kind === 'preset') return { kind, value: 'aurora' };
  if (kind === 'solid') return { kind, value: '#0f172a' };
  if (kind === 'gradient') {
    return { kind, value: 'linear-gradient(135deg, #1e293b, #0f172a)' };
  }
  return { kind, value: '' };
}

export function BoardAppearanceModal({
  visible,
  appearance,
  online,
  saving,
  error,
  onClose,
  onSave,
}: {
  visible: boolean;
  appearance: BoardAppearanceSettings;
  online: boolean;
  saving: boolean;
  error?: string | null;
  onClose: () => void;
  onSave: (input: UpdateBoardAppearanceRequest) => Promise<void>;
}) {
  const colors = useAppColors();
  const mode = useResolvedTheme();
  const [draft, setDraft] = useState(appearance);

  useEffect(() => {
    if (visible) setDraft(appearance);
  }, [appearance, visible]);

  const accent = typeof draft.customProperties.accentColor === 'string'
    ? draft.customProperties.accentColor
    : '';
  const preview = useMemo(() => resolveBoardPalette(draft, mode), [draft, mode]);
  const wallpaperNeedsValue = !['none', 'accent'].includes(draft.wallpaper.kind);
  const wallpaperValue = draft.wallpaper.value || '';
  const invalidAccent = Boolean(accent && !validHex(accent));
  const invalidWallpaper = wallpaperNeedsValue && !wallpaperValue.trim();
  const invalidImage = draft.wallpaper.kind === 'image'
    && !/^https?:\/\//i.test(wallpaperValue.trim());

  async function save() {
    if (invalidAccent || invalidWallpaper || invalidImage) return;
    await onSave({
      themePreset: draft.themePreset,
      wallpaper: draft.wallpaper,
      columnDensity: draft.columnDensity,
      cardPreviewMode: draft.cardPreviewMode,
      showCardDescription: draft.showCardDescription,
      showCardDates: draft.showCardDates,
      showChecklistProgress: draft.showChecklistProgress,
      customProperties: draft.customProperties,
    });
  }

  return (
    <FormModal visible={visible} title="Вид доски" onClose={onClose}>
      <InlineNotice
        text="Эти настройки общие с вебом и видны участникам доски. Мобильный интерфейс адаптирует CSS-градиенты к плоскому цвету."
        tone="neutral"
      />

      <View style={[styles.preview, {
        backgroundColor: preview.background,
        borderColor: preview.accent,
      }]}>
        <View style={[styles.previewColumn, { backgroundColor: preview.column }]}>
          <Text style={[styles.previewTitle, { color: preview.text }]}>Колонка</Text>
          <View style={[styles.previewCard, { backgroundColor: preview.card, borderColor: preview.border }]}>
            <Text style={[styles.previewCardText, { color: preview.text }]}>Пример карточки</Text>
            <View style={[styles.previewAccent, { backgroundColor: preview.accent }]} />
          </View>
        </View>
      </View>

      <View style={styles.section}>
        <SectionTitle title="Цветовая схема" />
        <View style={styles.choices}>
          {boardThemePresets.map((preset) => {
            const palette = resolveBoardPalette({ ...draft, themePreset: preset.id }, mode);
            return (
              <Choice
                key={preset.id}
                label={preset.label}
                value={preset.id}
                selected={draft.themePreset}
                swatch={palette.accent}
                onPress={(themePreset) => setDraft((current) => ({ ...current, themePreset }))}
              />
            );
          })}
        </View>
      </View>

      <View style={styles.section}>
        <SectionTitle title="Акцент" />
        <View style={styles.choices}>
          <Choice
            label="Из схемы"
            value="preset"
            selected={accent ? 'custom' : 'preset'}
            onPress={() => setDraft((current) => {
              const customProperties = { ...current.customProperties };
              delete customProperties.accentColor;
              return { ...current, customProperties };
            })}
          />
          <Choice
            label="Свой цвет"
            value="custom"
            selected={accent ? 'custom' : 'preset'}
            onPress={() => setDraft((current) => ({
              ...current,
              customProperties: { ...current.customProperties, accentColor: '#60a5fa' },
            }))}
          />
        </View>
        {accent ? (
          <Field
            label="HEX-цвет"
            value={accent}
            autoCapitalize="none"
            onChangeText={(value) => setDraft((current) => ({
              ...current,
              customProperties: { ...current.customProperties, accentColor: value },
            }))}
            hint={invalidAccent ? 'Нужен цвет вида #60a5fa.' : undefined}
          />
        ) : null}
      </View>

      <View style={styles.section}>
        <SectionTitle title="Фон" />
        <View style={styles.choices}>
          {wallpaperKinds.map((item) => (
            <Choice
              key={item.value}
              label={item.label}
              value={item.value}
              selected={draft.wallpaper.kind}
              onPress={(kind) => setDraft((current) => ({
                ...current,
                wallpaper: wallpaperFor(kind),
              }))}
            />
          ))}
        </View>
        {draft.wallpaper.kind === 'preset' ? (
          <View style={styles.choices}>
            {boardWallpaperPresets.map((preset) => (
              <Choice
                key={preset}
                label={preset}
                value={preset}
                selected={draft.wallpaper.value || 'aurora'}
                onPress={(value) => setDraft((current) => ({
                  ...current,
                  wallpaper: { kind: 'preset', value },
                }))}
              />
            ))}
          </View>
        ) : wallpaperNeedsValue ? (
          <Field
            label={draft.wallpaper.kind === 'image'
              ? 'HTTPS-ссылка'
              : draft.wallpaper.kind === 'solid'
                ? 'HEX-цвет'
                : 'CSS-градиент'}
            value={wallpaperValue}
            autoCapitalize="none"
            onChangeText={(value) => setDraft((current) => ({
              ...current,
              wallpaper: { ...current.wallpaper, value },
            }))}
            hint={invalidImage
              ? 'Нужна публичная ссылка http:// или https://.'
              : draft.wallpaper.kind === 'gradient'
                ? 'На Android берётся первый HEX-цвет, веб сохраняет полный градиент.'
                : undefined}
          />
        ) : null}
      </View>

      <View style={styles.section}>
        <SectionTitle title="Карточки" />
        <Text style={[styles.label, { color: colors.muted }]}>Плотность колонок</Text>
        <View style={styles.choices}>
          {([
            ['comfortable', 'Свободная'],
            ['compact', 'Компактная'],
          ] as Array<[Density, string]>).map(([value, label]) => (
            <Choice
              key={value}
              label={label}
              value={value}
              selected={draft.columnDensity}
              onPress={(columnDensity) => setDraft((current) => ({ ...current, columnDensity }))}
            />
          ))}
        </View>
        <Text style={[styles.label, { color: colors.muted }]}>Превью</Text>
        <View style={styles.choices}>
          {([
            ['compact', 'Компактное'],
            ['expanded', 'Расширенное'],
          ] as Array<[CardPreviewMode, string]>).map(([value, label]) => (
            <Choice
              key={value}
              label={label}
              value={value}
              selected={draft.cardPreviewMode}
              onPress={(cardPreviewMode) => setDraft((current) => ({ ...current, cardPreviewMode }))}
            />
          ))}
        </View>
        <Toggle
          label="Показывать описание"
          value={draft.showCardDescription}
          onChange={(showCardDescription) => setDraft((current) => ({
            ...current, showCardDescription,
          }))}
        />
        <Toggle
          label="Показывать даты"
          value={draft.showCardDates}
          onChange={(showCardDates) => setDraft((current) => ({ ...current, showCardDates }))}
        />
        <Toggle
          label="Прогресс чек-листа"
          value={draft.showChecklistProgress}
          onChange={(showChecklistProgress) => setDraft((current) => ({
            ...current, showChecklistProgress,
          }))}
        />
      </View>

      {!online ? (
        <InlineNotice
          text="Изменение сохранится на телефоне и уйдёт на узел через relay, когда появится связь."
          tone="warning"
        />
      ) : null}
      {error ? <InlineNotice text={error} tone="danger" /> : null}
      <Button
        label="Сохранить оформление"
        variant="primary"
        loading={saving}
        disabled={invalidAccent || invalidWallpaper || invalidImage}
        onPress={() => void save()}
      />
    </FormModal>
  );
}

const styles = StyleSheet.create({
  section: { gap: spacing.sm },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  choice: {
    minHeight: 40,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    borderWidth: 1,
    borderRadius: radius.sm,
  },
  choiceText: { fontSize: 13, fontWeight: '700' },
  swatch: { width: 14, height: 14, borderRadius: 3 },
  preview: { minHeight: 118, padding: spacing.sm, borderWidth: 1, borderRadius: radius.md },
  previewColumn: { flex: 1, gap: spacing.xs, padding: spacing.sm, borderRadius: radius.sm },
  previewTitle: { fontSize: 13, fontWeight: '800' },
  previewCard: { gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderRadius: radius.sm },
  previewCardText: { fontSize: 13, fontWeight: '700' },
  previewAccent: { width: '62%', height: 4, borderRadius: 99 },
  label: { fontSize: 12, fontWeight: '700' },
  toggle: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  toggleLabel: { flex: 1, fontSize: 14, fontWeight: '600' },
  toggleTrack: { width: 40, height: 24, padding: 3, borderRadius: 12 },
  toggleThumb: { width: 18, height: 18, borderRadius: 9 },
});
