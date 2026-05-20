/**
 * electron-builder afterPack：关闭「嵌入式 ASAR 完整性校验」fuse，
 * 然后重新 ad-hoc 签名，使 macOS 将本应用识别为完整应用（辅助功能/输入监控授权可用）。
 *
 * 注意：关 fuse 会改 .app 内容，破坏 electron-builder 在打包阶段做的预签名，
 * 所以必须在 fuse 关掉后再重新签名一次，否则 macOS TCC 看到 Identifier=Electron
 * 且 Info.plist=not bound，导致授权不生效。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const out = context.appOutDir;
  if (!out || !fs.existsSync(out)) return;
  const apps = fs.readdirSync(out).filter((f) => f.endsWith('.app'));
  if (!apps.length) return;
  const appPath = path.join(out, apps[0]);

  // 1. 关 ASAR 完整性校验 fuse
  let flipFuses;
  let FuseVersion;
  let FuseV1Options;
  try {
    ({ flipFuses, FuseVersion, FuseV1Options } = require('@electron/fuses'));
  } catch (e) {
    console.warn('[after-pack] skip fuses (install @electron/fuses):', e && e.message);
    return;
  }

  await flipFuses(appPath, {
    version: FuseVersion.V1,
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: false,
  });
  console.log('[after-pack] EnableEmbeddedAsarIntegrityValidation=false', appPath);

  // 2. 关 fuse 改动了 .app → 重新 ad-hoc 签名
  try {
    const infoPlist = path.join(appPath, 'Contents', 'Info.plist');
    const bundleId = fs.readFileSync(infoPlist, 'utf8').match(
      /<key>CFBundleIdentifier<\/key>\s*<string>([^<]+)</
    )?.[1] || 'com.gojocloud.crossscreeninput';
    console.log('[after-pack] re-sign app bundleId=' + bundleId, appPath);

    // 先签内部 frameworks/libs（解决 --deep 在 macOS 14+ 不可靠的问题）
    const frameworksDir = path.join(appPath, 'Contents', 'Frameworks');
    if (fs.existsSync(frameworksDir)) {
      for (const item of fs.readdirSync(frameworksDir)) {
        const itemPath = path.join(frameworksDir, item);
        if (fs.statSync(itemPath).isDirectory() || item.endsWith('.dylib')) {
          try {
            execSync(`codesign --force --sign - "${itemPath}" 2>/dev/null`, { stdio: 'ignore' });
          } catch (_) {}
        }
      }
    }

    // 再签整个 .app（带明确 identifier 确保 TCC 识别）
    execSync(
      `codesign --force --sign - --identifier "${bundleId}" "${appPath}"`,
      { stdio: 'inherit' }
    );
    console.log('[after-pack] ad-hoc re-sign OK');
  } catch (e) {
    console.warn('[after-pack] re-sign failed:', e && e.message);
  }
};
