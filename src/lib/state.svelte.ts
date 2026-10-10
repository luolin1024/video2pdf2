// src/lib/state.svelte.ts
export type Phase = "idle" | "running" | "done" | "error";

export const app = $state({
  videos: [] as string[],
  phase: "idle" as Phase,
  err: "",
  run: {
    index: 0, total: 0, name: "", pages: 0, pct: 0,
    stages: {} as Record<string, "todo" | "doing" | "done">,
  },
  results: [] as { name: string; pages: number; summary: boolean }[],
  outdir: null as string | null,
});

export const STAGES = [
  ["asr", "语音转写"], ["correct", "字幕校对"], ["frames", "关键帧对齐"],
  ["summary", "AI 总结"], ["pdf", "生成 PDF"],
] as const;

// 各阶段权重（本视频进度百分比），与旧 GUI 一致
export const WEIGHTS: Record<string, number> = {
  asr: 45, correct: 10, frames: 25, summary: 12, pdf: 8,
};

export function resetRun() {
  app.run = { index: 0, total: 0, name: "", pages: 0, pct: 0, stages: {} };
  app.results = [];
  app.err = "";
}

// 本视频进度由阶段状态推导：完成阶段全额、进行中阶段记一半
export function computePct(stages: Record<string, string>): number {
  let w = 0;
  for (const [k, weight] of Object.entries(WEIGHTS)) {
    if (stages[k] === "done") w += weight;
    else if (stages[k] === "doing") w += weight / 2;
  }
  return Math.min(100, Math.round(w));
}
