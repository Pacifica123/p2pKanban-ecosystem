import { copyFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { expoCommand, gradleCommand } from './apk-commands.mjs';

const mobileRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageVersion = JSON.parse(
  readFileSync(join(mobileRoot, 'package.json'), 'utf8'),
).version;
const isWindows = process.platform === 'win32';
const require = createRequire(import.meta.url);

function run(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: 'inherit',
    shell: false,
  });
  if (result.error) {
    throw new Error(`Не удалось запустить ${command}: ${result.error.message}`);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const sdkRoot = process.env.ANDROID_HOME || process.env.ANDROID_SDK_ROOT;
if (!sdkRoot || !existsSync(sdkRoot)) {
  console.error(
    'Android SDK не найден. Установите Android Studio + Android SDK 36 и задайте ANDROID_HOME.',
  );
  process.exit(2);
}

// Fail BEFORE prebuild --clean can replace the generated native directory.
let expoCli;
try {
  expoCli = join(dirname(require.resolve('expo/package.json')), 'bin', 'cli');
} catch {
  console.error('Expo не установлен. Выполните npm ci в корне Android-проекта.');
  process.exit(2);
}
if (!existsSync(expoCli)) throw new Error(`Expo CLI не найден: ${expoCli}`);
if (!existsSync(join(sdkRoot, 'platforms', 'android-36', 'android.jar'))) {
  console.error('В Android SDK отсутствует Platform 36. Установите её через SDK Manager.');
  process.exit(2);
}
const java = process.env.JAVA_HOME
  ? join(process.env.JAVA_HOME, 'bin', isWindows ? 'java.exe' : 'java')
  : 'java';
const javaProbe = spawnSync(java, ['-version'], { encoding: 'utf8', shell: false });
const javaVersion = `${javaProbe.stdout || ''}\n${javaProbe.stderr || ''}`;
const javaMajor = Number(javaVersion.match(/version "(\d+)/)?.[1] || 0);
if (javaProbe.error || javaProbe.status !== 0 || javaMajor < 17) {
  console.error('Не найден совместимый JDK. Рекомендуется JDK 17; проверьте JAVA_HOME и java -version.');
  process.exit(2);
}

run(...expoCommand(process.execPath, expoCli), mobileRoot);
run(...gradleCommand(process.platform), join(mobileRoot, 'android'));

const source = join(mobileRoot, 'android', 'app', 'build', 'outputs', 'apk', 'release', 'app-release.apk');
const destination = join(mobileRoot, 'dist', `p2pKanban-${packageVersion}.apk`);
if (!existsSync(source)) {
  console.error(`Gradle завершился без ожидаемого APK: ${source}`);
  process.exit(3);
}
mkdirSync(dirname(destination), { recursive: true });
copyFileSync(source, destination);
console.log(`APK готов: ${destination}`);
