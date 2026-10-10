import { check, Update } from "@tauri-apps/plugin-updater";

export async function autoUpdate(): Promise<string | null> {
  try {
    const u: Update | null = await check();
    if (!u) return null;
    await u.downloadAndInstall();
    return u.version;
  } catch (e) {
    console.error("updater:", e);
    return null;
  }
}
