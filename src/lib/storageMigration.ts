// 旧版 k-coder 的 localStorage 键统一为 kcoder_ 前缀，现重命名到 kcode_ 前缀。
// 一次性迁移：仅当新键不存在时搬运旧值，随后删除旧键；重复执行无副作用。
// 注意：连字符形式的历史键（如 workbenchStore 的 "k-coder-providers"）由各自模块自行迁移，不在此处理。
const LEGACY_KEY_PREFIX = "kcoder_";
const CURRENT_KEY_PREFIX = "kcode_";

export function migrateLegacyStorageKeys(): void {
  let storage: Storage;
  try {
    storage = window.localStorage;
  } catch {
    return;
  }

  const legacyKeys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key && key.startsWith(LEGACY_KEY_PREFIX)) legacyKeys.push(key);
  }

  for (const legacyKey of legacyKeys) {
    const currentKey = CURRENT_KEY_PREFIX + legacyKey.slice(LEGACY_KEY_PREFIX.length);
    try {
      if (storage.getItem(currentKey) === null) {
        const value = storage.getItem(legacyKey);
        if (value !== null) storage.setItem(currentKey, value);
      }
      storage.removeItem(legacyKey);
    } catch {
      // 迁移失败不阻塞启动：读取侧对旧键仍有回退兼容（见 index.html 首帧脚本）。
    }
  }
}
