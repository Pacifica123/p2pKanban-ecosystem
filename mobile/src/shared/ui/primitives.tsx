import type { PropsWithChildren, ReactNode } from 'react';
import {
  ActivityIndicator,
  ImageBackground,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { radius, spacing, useAppColors } from '../../app/theme';
import { useAppearance } from '../../features/appearance/AppearanceProvider';

export function Screen({
  children,
  scroll = false,
  contentStyle,
  backgroundColor,
  backgroundImage,
}: PropsWithChildren<{
  scroll?: boolean;
  contentStyle?: ViewStyle;
  backgroundColor?: string;
  backgroundImage?: string | null;
}>) {
  const colors = useAppColors();
  const dense = useAppearance().preferences.density === 'compact';
  const content = scroll ? (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={[styles.screenContent, dense && styles.screenContentDense, contentStyle]}
    >
      {children}
    </ScrollView>
  ) : (
    <View style={[
      styles.screenContent,
      dense && styles.screenContentDense,
      styles.screenContentFill,
      contentStyle,
    ]}>{children}</View>
  );

  const body = backgroundImage ? (
    <ImageBackground
      source={{ uri: backgroundImage }}
      resizeMode="cover"
      style={styles.backgroundImage}
    >
      {content}
    </ImageBackground>
  ) : content;

  return (
    <SafeAreaView style={[
      styles.safeArea,
      { backgroundColor: backgroundColor || colors.background },
    ]}>
      {body}
    </SafeAreaView>
  );
}

export function ScreenHeader({
  title,
  subtitle,
  onBack,
  action,
  palette,
}: {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  action?: ReactNode;
  palette?: { text: string; muted: string; border: string };
}) {
  const colors = useAppColors();
  const resolved = palette || colors;
  const dense = useAppearance().preferences.density === 'compact';
  return (
    <View style={[styles.header, dense && styles.headerDense, { borderBottomColor: colors.border }]}>
      {onBack ? (
        <Pressable
          onPress={onBack}
          accessibilityRole="button"
          accessibilityLabel="Назад"
          style={({ pressed }) => [
            styles.headerBack,
            { borderColor: resolved.border, opacity: pressed ? 0.65 : 1 },
          ]}
        >
          <Text style={[styles.headerBackText, { color: resolved.text }]}>‹</Text>
        </Pressable>
      ) : null}
      <View style={styles.headerTitle}>
        <Text style={[styles.headerTitleText, { color: resolved.text }]} numberOfLines={1}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={[styles.headerSubtitle, { color: resolved.muted }]} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      {action ? <View style={styles.headerAction}>{action}</View> : null}
    </View>
  );
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  label,
  onPress,
  variant = 'secondary',
  disabled = false,
  loading = false,
  compact = false,
  accessibilityLabel,
  foregroundColor,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  compact?: boolean;
  accessibilityLabel?: string;
  foregroundColor?: string;
}) {
  const colors = useAppColors();
  const dense = useAppearance().preferences.density === 'compact';
  const palette = {
    primary: {
      background: colors.accent,
      border: colors.accent,
      text: colors.background,
    },
    secondary: {
      background: colors.surface,
      border: colors.border,
      text: colors.text,
    },
    ghost: {
      background: 'transparent',
      border: 'transparent',
      text: colors.muted,
    },
    danger: {
      background: colors.dangerSoft,
      border: colors.dangerSoft,
      text: colors.danger,
    },
  }[variant];

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel || label}
      style={({ pressed }) => [
        styles.button,
        dense && styles.buttonDense,
        compact && styles.buttonCompact,
        {
          backgroundColor: palette.background,
          borderColor: palette.border,
          opacity: disabled || loading ? 0.45 : pressed ? 0.72 : 1,
        },
      ]}
    >
      {loading ? <ActivityIndicator size="small" color={palette.text} /> : null}
      <Text style={[styles.buttonText, { color: foregroundColor || palette.text }]} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

export function Field({
  label,
  hint,
  multiline,
  ...props
}: TextInputProps & { label: string; hint?: string }) {
  const colors = useAppColors();
  const dense = useAppearance().preferences.density === 'compact';
  return (
    <View style={styles.field}>
      <Text style={[styles.fieldLabel, { color: colors.text }]}>{label}</Text>
      <TextInput
        {...props}
        multiline={multiline}
        placeholderTextColor={colors.muted}
        selectionColor={colors.accent}
        style={[
          styles.input,
          dense && styles.inputDense,
          multiline && styles.inputMultiline,
          {
            color: colors.text,
            backgroundColor: colors.surface,
            borderColor: colors.border,
          },
          props.style,
        ]}
      />
      {hint ? <Text style={[styles.hint, { color: colors.muted }]}>{hint}</Text> : null}
    </View>
  );
}

export function Panel({
  children,
  style,
}: PropsWithChildren<{ style?: ViewStyle }>) {
  const colors = useAppColors();
  const dense = useAppearance().preferences.density === 'compact';
  return (
    <View
      style={[
        styles.panel,
        dense && styles.panelDense,
        { backgroundColor: colors.surface, borderColor: colors.border },
        style,
      ]}
    >
      {children}
    </View>
  );
}

export function StateView({
  title,
  description,
  busy = false,
  action,
}: {
  title: string;
  description?: string;
  busy?: boolean;
  action?: ReactNode;
}) {
  const colors = useAppColors();
  return (
    <View style={styles.state}>
      {busy ? <ActivityIndicator color={colors.accent} /> : null}
      <Text style={[styles.stateTitle, { color: colors.text }]}>{title}</Text>
      {description ? (
        <Text style={[styles.stateDescription, { color: colors.muted }]}>{description}</Text>
      ) : null}
      {action}
    </View>
  );
}

export function InlineNotice({
  text,
  tone = 'neutral',
}: {
  text: string;
  tone?: 'neutral' | 'danger' | 'success' | 'warning';
}) {
  const colors = useAppColors();
  const palette = {
    neutral: { background: colors.surfaceMuted, text: colors.muted },
    danger: { background: colors.dangerSoft, text: colors.danger },
    success: { background: colors.accentSoft, text: colors.success },
    warning: { background: colors.surfaceMuted, text: colors.warning },
  }[tone];

  return (
    <View style={[styles.notice, { backgroundColor: palette.background }]}>
      <Text style={[styles.noticeText, { color: palette.text }]}>{text}</Text>
    </View>
  );
}

export function FormModal({
  visible,
  title,
  children,
  onClose,
}: PropsWithChildren<{ visible: boolean; title: string; onClose: () => void }>) {
  const colors = useAppColors();
  const { preferences } = useAppearance();
  return (
    <Modal
      visible={visible}
      transparent
      animationType={preferences.reduceMotion ? 'none' : 'fade'}
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : spacing.sm}
        style={[styles.modalBackdrop, { backgroundColor: colors.overlay }]}
      >
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <View style={[styles.modalSheet, { backgroundColor: colors.background }]}>
          <View style={styles.modalHeader}>
            <Text style={[styles.modalTitle, { color: colors.text }]}>{title}</Text>
            <Button label="Закрыть" variant="ghost" compact onPress={onClose} />
          </View>
          <ScrollView
            keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={[
              styles.modalBody,
              preferences.density === 'compact' && styles.modalBodyDense,
            ]}
          >
            {children}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export function SectionTitle({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  const colors = useAppColors();
  return (
    <View style={styles.sectionTitleRow}>
      <Text style={[styles.sectionTitle, { color: colors.text }]}>{title}</Text>
      {detail ? <Text style={[styles.sectionDetail, { color: colors.muted }]}>{detail}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  backgroundImage: {
    flex: 1,
  },
  screenContent: {
    padding: spacing.md,
    gap: spacing.md,
  },
  screenContentDense: {
    padding: spacing.sm,
    gap: spacing.sm,
  },
  screenContentFill: {
    flex: 1,
  },
  header: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingBottom: spacing.sm,
  },
  headerDense: {
    minHeight: 48,
    paddingBottom: spacing.xs,
  },
  headerBack: {
    width: 38,
    height: 38,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderRadius: radius.sm,
  },
  headerBackText: {
    fontSize: 30,
    lineHeight: 31,
    fontWeight: '400',
  },
  headerTitle: {
    flex: 1,
    minWidth: 0,
  },
  headerTitleText: {
    fontSize: 20,
    fontWeight: '700',
  },
  headerSubtitle: {
    marginTop: 2,
    fontSize: 12,
  },
  headerAction: {
    alignItems: 'flex-end',
  },
  button: {
    minHeight: 46,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderRadius: radius.sm,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  buttonCompact: {
    minHeight: 36,
    paddingHorizontal: spacing.sm,
  },
  buttonDense: {
    minHeight: 40,
    paddingHorizontal: spacing.sm,
  },
  buttonText: {
    fontSize: 15,
    fontWeight: '700',
  },
  field: {
    gap: spacing.xs,
  },
  fieldLabel: {
    fontSize: 14,
    fontWeight: '700',
  },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 16,
  },
  inputMultiline: {
    minHeight: 116,
    textAlignVertical: 'top',
  },
  inputDense: {
    minHeight: 42,
    paddingVertical: spacing.xs,
  },
  hint: {
    fontSize: 12,
    lineHeight: 17,
  },
  panel: {
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  panelDense: {
    padding: spacing.sm,
  },
  state: {
    flex: 1,
    minHeight: 220,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    padding: spacing.lg,
  },
  stateTitle: {
    textAlign: 'center',
    fontSize: 19,
    fontWeight: '700',
  },
  stateDescription: {
    textAlign: 'center',
    fontSize: 14,
    lineHeight: 20,
  },
  notice: {
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
  },
  noticeText: {
    fontSize: 13,
    lineHeight: 18,
  },
  modalBackdrop: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalSheet: {
    maxHeight: '88%',
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingTop: spacing.sm,
  },
  modalHeader: {
    minHeight: 50,
    paddingHorizontal: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  modalTitle: {
    flex: 1,
    fontSize: 20,
    fontWeight: '700',
  },
  modalBody: {
    padding: spacing.md,
    paddingBottom: spacing.xl,
    gap: spacing.md,
  },
  modalBodyDense: {
    padding: spacing.sm,
    paddingBottom: spacing.lg,
    gap: spacing.sm,
  },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
  },
  sectionDetail: {
    fontSize: 12,
  },
});
