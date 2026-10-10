// src/lib/ipc.ts
import { Command } from "@tauri-apps/plugin-shell";

type Pending = { resolve: (v: any) => void; reject: (e: Error) => void };

let cmd: Command<any> | null = null;
let child: any = null;
let seq = 0;
const pending = new Map<number, Pending>();
const eventHandlers = new Set<(ev: any) => void>();
const exitHandlers = new Set<() => void>();

export async function startCore(): Promise<void> {
  if (cmd) return;
  const c = Command.sidecar("binaries/chalkpress-core");
  c.stdout.on("data", (line: string) => {
    for (const l of line.split("\n")) {
      const t = l.trim();
      if (!t) continue;
      let msg: any;
      try { msg = JSON.parse(t); } catch { continue; }  // 非 JSON 行丢弃
      if (msg.event !== undefined) {
        eventHandlers.forEach((h) => h(msg));
      } else {
        const p = pending.get(msg.id);
        pending.delete(msg.id);
        if (p) msg.error ? p.reject(new Error(msg.error)) : p.resolve(msg.result);
      }
    }
  });
  c.stderr.on("data", (l: string) => console.error("[core]", l));
  c.on("close", () => {
    pending.forEach((p) => p.reject(new Error("core 已退出")));
    pending.clear();
    exitHandlers.forEach((h) => h());
    cmd = null; child = null;  // 允许下次 startCore() 重试
  });
  try {
    child = await c.spawn();
    cmd = c;
  } catch (e) {
    cmd = null; child = null; throw e;
  }
}

export function request<T = any>(method: string, params?: object): Promise<T> {
  if (!cmd || !child) return Promise.reject(new Error("core 未启动"));
  const id = ++seq;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    try {
      child.write(JSON.stringify({ id, method, params: params ?? {} }) + "\n");
    } catch (e: any) {
      pending.delete(id);
      reject(e instanceof Error ? e : new Error(String(e)));
    }
  });
}

export function onEvent(h: (ev: any) => void): () => void {
  eventHandlers.add(h);
  return () => eventHandlers.delete(h);
}

export function onCoreExit(h: () => void): () => void {
  exitHandlers.add(h);
  return () => exitHandlers.delete(h);
}
