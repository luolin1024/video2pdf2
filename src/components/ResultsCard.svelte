<!-- src/components/ResultsCard.svelte -->
<script lang="ts">
  import { openPath } from "@tauri-apps/plugin-opener";
  import { app } from "../lib/state.svelte";

  const pages = $derived(app.results.reduce((n, r) => n + r.pages, 0));
</script>

<section class="hero">
  <div class="card">
    <h3>{app.results.length} 个视频完成 🎉</h3>
    <div class="stats">
      <div><b>{app.results.length}</b><span>讲义 PDF</span></div>
      <div><b>{pages}</b><span>讲义页数</span></div>
    </div>
    {#each app.results as r (r.name)}
      <div class="row"><span class="pdf">PDF</span> {r.name} <span class="meta">{r.pages} 页 · AI 总结 {r.summary ? "✓" : "—"}</span></div>
    {/each}
    {#if app.outdir}
      <button class="primary" onclick={() => openPath(app.outdir!)}>打开输出文件夹</button>
    {/if}
  </div>
</section>

<style>
  .hero { margin-top: 8vh; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; }
  .stats { display: flex; gap: 28px; margin: 12px 0; }
  .stats b { font-size: 22px; display: block; }
  .stats span { color: var(--ink2); font-size: 12px; }
  .row { padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
  .pdf { color: var(--red); font-size: 11px; border: 1px solid var(--red); border-radius: 4px; padding: 0 4px; }
  .meta { color: var(--ink2); font-size: 12px; float: right; }
  .primary { margin-top: 14px; background: var(--accent); color: #fff; border: 0;
             border-radius: 10px; padding: 10px 22px; font-weight: 600; cursor: pointer; }
</style>
