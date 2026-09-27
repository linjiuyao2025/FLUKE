const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');

const projectRoot = path.resolve(__dirname, '..');
const appData = process.env.APPDATA;
if (!appData) throw new Error('找不到 Windows APPDATA 目录。');

const contentDir = path.join(appData, 'Wanxiang Life Workspace', 'content');
const pagePath = path.join(contentDir, 'life-workspace.html');
const manifestPath = path.join(contentDir, 'manifest.json');
const previousPagePath = path.join(contentDir, 'life-workspace.previous.html');
const previousManifestPath = path.join(contentDir, 'manifest.previous.json');

async function writeAtomic(destination, data) {
  const temporary = `${destination}.${process.pid}.tmp`;
  try {
    await fs.writeFile(temporary, data);
    await fs.rename(temporary, destination);
  } finally {
    await fs.rm(temporary, { force: true });
  }
}

async function exists(file) {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  await fs.mkdir(contentDir, { recursive: true });

  if (process.argv.includes('--rollback')) {
    if (await exists(previousPagePath) && await exists(previousManifestPath)) {
      await writeAtomic(pagePath, await fs.readFile(previousPagePath));
      await writeAtomic(manifestPath, await fs.readFile(previousManifestPath));
      console.log('已恢复上一个本地内容版本。关闭并重开万象来信即可生效。');
    } else {
      await fs.rm(manifestPath, { force: true });
      console.log('已停用本地内容更新，软件会使用安装包内置页面。关闭并重开即可生效。');
    }
    return;
  }

  const packageInfo = JSON.parse(await fs.readFile(path.join(projectRoot, 'package.json'), 'utf8'));
  const page = await fs.readFile(path.join(projectRoot, 'life-workspace.html'));
  if (page.length > 5 * 1024 * 1024) throw new Error('页面超过 5 MB，未同步。');
  const manifest = {
    format: 1,
    shellVersion: packageInfo.version,
    sha256: createHash('sha256').update(page).digest('hex')
  };

  if (await exists(pagePath) && await exists(manifestPath)) {
    await fs.copyFile(pagePath, previousPagePath);
    await fs.copyFile(manifestPath, previousManifestPath);
  }
  await writeAtomic(pagePath, page);
  await writeAtomic(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`已同步到 ${contentDir}`);
  console.log('关闭并重开万象来信即可使用新页面，无需重新下载安装包。');
}

main().catch((error) => {
  console.error(`本地内容更新失败：${error.message}`);
  process.exitCode = 1;
});
