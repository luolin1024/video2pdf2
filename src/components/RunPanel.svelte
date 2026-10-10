<!-- src/components/RunPanel.svelte -->
<script lang="ts">
  import { app, STAGES } from "../lib/state.svelte";
  let { stop }: { stop: () => void } = $props();
</script>

<section class="hero">
  <div class="card">
    <h3>正在转换 {app.run.index} / {app.run.total}</h3>
    <p class="now">{app.run.name}</p>
    <div class="bar"><div class="fill" style="width: {app.run.total ? (app.run.index - 1) / app.run.total * 100 : 0}%"></div></div>
    <div class="stages">
      {#each STAGES as [key, label], i (key)}
        <span class="stage {app.run.stages[key]}">{app.run.stages[key] === "done" ? "✓" : app.run.stages[key] === "doing" ? "●" : "○"} {label}</span>
        {#if i < STAGES.length - 1}<span class="arrow">→</span>{/if}
      {/each}
    </div>
    <div class="vbar">
      <span>本视频 {app.run.pct}%</span>
      <div class="bar thin"><div class="fill" style="width: {app.run.pct}%"></div></div>
    </div>
    {#if app.results.length || app.run.pages}
      <p class="pages">已生成 {app.run.pages} 页</p>
    {/if}
  </div>
  <button class="ghost" onclick={stop}>停止（当前视频完成后）</button>
</section>

<style>
  .hero { display: flex; flex-direction: column; gap: 14px; margin-top: 8vh; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; }
  h3 { margin: 0 0 4px; }
  .now { color: var(--ink2); font-size: 13px; margin: 0 0 12px; }
  .stages { display: flex; gap: 8px; margin: 14px 0; flex-wrap: wrap; }
  .stage { font-size: 12px; color: var(--faint); }
  .stage.doing { color: var(--ink); font-weight: 600; }
  .stage.done { color: var(--accent-dk); }
  .arrow { color: var(--faint); font-size: 12px; }
  .bar { height: 6px; background: var(--accent-bg); border-radius: 3px; overflow: hidden; }
  .bar.thin { height: 5px; flex: 1; }
  .fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .3s; }
  .vbar { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--ink2); }
  .pages { color: var(--ink2); font-size: 12px; }
  .ghost { align-self: center; background: var(--card); border: 1px solid var(--line);
           border-radius: 10px; padding: 8px 18px; cursor: pointer; }
</style>
