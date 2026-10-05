import { join } from 'node:path';

// Executable paths and cwd stay argv/path values, including spaces, Cyrillic,
// ampersands and parentheses. Only the fixed Gradle batch name reaches cmd.
export function expoCommand(node, expoCli) {
  return [node, [expoCli, 'prebuild', '--platform', 'android', '--clean', '--no-install']];
}

export function gradleCommand(platform, env = process.env) {
  if (platform !== 'win32') return ['sh', ['./gradlew', 'assembleRelease']];
  const cmd = env.ComSpec || env.COMSPEC || join(env.SystemRoot || 'C:\\Windows', 'System32', 'cmd.exe');
  return [cmd, ['/d', '/s', '/c', 'gradlew.bat assembleRelease']];
}
