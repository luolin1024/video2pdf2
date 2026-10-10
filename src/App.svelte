<!-- src/App.svelte -->
<script lang="ts">
  import { onMount } from "svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import { request, startCore, onEvent, onCoreExit } from "./lib/ipc";
  import { app, resetRun, STAGES, computePct } from "./lib/state.svelte";
  import RunPanel from "./components/RunPanel.svelte";
  import ResultsCard from "./components/ResultsCard.svelte";

  let settingsOpen = false;
  let coreDown = false;

  async function addFiles() {
    const sel = await open({ multiple: true,
      filters: [{ name: "视频", extensions: ["mp4","mov","mkv","webm","avi","m4v","flv","ts"] }] });
    if (sel) for (const f of [].concat(sel as any)) addVideo(f as string);
  }
  async function addFolder() {
    const dir = await open({ directory: true });
    if (!dir) return;
    const { videos } = await request<{ videos: string[] }>("fs.list_videos", { dir });
    for (const v of videos) addVideo(v);
  }
  function addVideo(p: string) {
    if (!app.videos.includes(p)) app.videos.push(p);
  }
  function removeVideo(p: string) {
    app.videos = app.videos.filter((v) => v !== p);
  }

  async function start() {
    if (!app.videos.length) return;
    resetRun();
    app.phase = "running";
    for (const [k] of STAGES) app.run.stages[k] = "todo";
    try {
      // 选项与 keep_log 以当前持久化设置为准
      const s = await request<{ options: any; app: any }>("settings.get");
      await request("convert.start",
                    { videos: app.videos, options: s.options, app: s.app });
    } catch (e: any) {
      app.phase = "error"; app.err = String(e.message ?? e);
    }
  }
  async function stop() { await request("convert.cancel"); }

  onMount(async () => {
    try { await startCore(); } catch { coreDown = true; }
    onEvent((ev) => {
      switch (ev.event) {
        case "video_start":
          app.run.index = ev.index; app.run.total = ev.total; app.run.name = ev.name;
          for (const [k] of STAGES) app.run.stages[k] = "todo";
          app.run.pages = 0;
          break;
        case "stage":
          app.run.stages[ev.key] = "doing";
          app.run.pct = computePct(app.run.stages);
          break;
        case "stage_done":
          app.run.stages[ev.key] = "done";
          app.run.pct = computePct(app.run.stages);
          break;
        case "frames": app.run.pages = ev.count; break;
        case "video_done":
          app.results.push({ name: ev.name ?? app.run.name,
                             pages: ev.pages ?? 0, summary: !!ev.summary });
          if (ev.outdir) app.outdir = ev.outdir;
          break;
        case "video_error": app.err = `${ev.name}：${ev.error}`; break;
        case "batch_error": app.phase = "error"; app.err = ev.error; break;
        case "batch_done": app.phase = "done"; break;
      }
    });
    onCoreExit(() => { coreDown = true; });
  });
</script>

{#if coreDown}
  <div class="corebar">转换引擎未启动，请重启应用；若持续出现请重新安装。</div>
{/if}

<main class="wrap">
  <header>
    <div class="brand"><span class="logo"></span> Chalkpress</div>
    <button class="gear" title="设置" onclick={() => (settingsOpen = true)}>⚙</button>
  </header>

  {#if app.phase === "idle"}
    <section class="hero">
      <div class="drop" role="button" tabindex="0" onclick={addFiles}>
        <div class="drop-icon">▶</div>
        <div class="drop-title">拖入视频，或点击添加</div>
        <div class="drop-sub">支持 mp4 · mov · mkv · webm 等，可多选或整个文件夹</div>
      </div>
      <button class="ghost" onclick={addFolder}>添加文件夹</button>

      {#if app.videos.length}
        <div class="card">
          {#each app.videos as v (v)}
            <div class="vrow">
              <span class="vname">{v.split(/[\\/]/).pop()}</span>
              <span class="vsize">{v}</span>
              <button class="x" onclick={() => removeVideo(v)}>✕</button>
            </div>
          {/each}
          <div class="vsum">{app.videos.length} 个视频 · 讲义生成在各自视频所在文件夹</div>
        </div>
        <button class="primary" onclick={start}>开始转换</button>
      {/if}
    </section>
  {:else if app.phase === "running"}
    <RunPanel {stop} />
  {:else if app.phase === "done"}
    <ResultsCard />
  {:else}
    <section class="hero">
      <p class="err">✗ {app.err}</p>
      <button class="primary" onclick={() => (app.phase = app.results.length ? "done" : "idle")}>返回</button>
    </section>
  {/if}
</main>

<style>
  .wrap { max-width: 760px; margin: 0 auto; padding: 16px 24px 32px; }
  header { display: flex; align-items: center; justify-content: space-between; }
  .brand { font-weight: 700; font-size: 16px; display: flex; align-items: center; gap: 8px; }
  .logo { width: 22px; height: 22px; border-radius: 7px; background: var(--accent); display: inline-block; }
  .gear { border: 0; background: transparent; font-size: 18px; cursor: pointer; color: var(--ink2); }
  .hero { display: flex; flex-direction: column; align-items: center; gap: 14px; margin-top: 8vh; }
  .drop { width: 100%; background: var(--card); border: 1.5px dashed var(--faint); border-radius: var(--radius);
          padding: 44px 0 38px; text-align: center; cursor: pointer; transition: border-color .15s; }
  .drop:hover { border-color: var(--accent); }
  .drop-icon { width: 44px; height: 44px; border-radius: 12px; background: var(--accent); color: #fff;
               display: flex; align-items: center; justify-content: center; font-size: 20px; margin: 0 auto 10px; }
  .drop-title { font-weight: 600; font-size: 15px; }
  .drop-sub { color: var(--ink2); font-size: 12px; margin-top: 3px; }
  .card { width: 100%; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 16px; }
  .vrow { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--line); }
  .vname { font-weight: 500; }
  .vsize { color: var(--faint); font-size: 11px; margin-left: auto; overflow: hidden;
           text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
  .x { border: 0; background: transparent; color: var(--faint); cursor: pointer; }
  .x:hover { color: var(--red); }
  .vsum { color: var(--ink2); font-size: 12px; padding: 8px 0; }
  .primary { background: var(--accent); color: #fff; border: 0; border-radius: 10px;
             padding: 11px 28px; font-size: 15px; font-weight: 600; cursor: pointer; width: 100%; }
  .primary:hover { background: var(--accent-dk); }
  .ghost { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
           padding: 8px 18px; cursor: pointer; }
  .err { color: var(--red); }
  .corebar { background: var(--red); color: #fff; text-align: center; padding: 6px; font-size: 13px; }
</style>
