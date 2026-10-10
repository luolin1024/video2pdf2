<!-- src/components/SettingsSheet.svelte -->
<script lang="ts">
  import { openPath } from "@tauri-apps/plugin-opener";
  import { request } from "../lib/ipc";

  let { onClose }: { onClose: () => void } = $props();

  let s = $state<any>(null);
  let saved = $state(false);

  $effect(() => {
    request("settings.get").then((r: any) => {
      // 未配置 llm / 部分缺省时补默认值，避免 bind 到 undefined
      r.llm = { api_base: "", api_key: "", model: "", ...r.llm };
      r.options = { asr_model: null, scene_threshold: null, min_gap: null, ...r.options };
      r.app = { keep_log: false, ...r.app };
      s = r;
    });
  });

  const save = $state({ timer: 0 as any });
  function touch() {
    saved = false;
    clearTimeout(save.timer);
    save.timer = setTimeout(flush, 400);   // 输入防抖，改动即时保存
  }
  async function flush() {
    await request("settings.set", { options: s.options, app: s.app, llm: s.llm });
    saved = true;
  }
</script>

{#if s}
  <div class="mask" onclick={onClose}></div>
  <aside class="sheet">
    <header><h2>设置</h2><button class="x" onclick={onClose}>✕</button></header>
    <p class="hint">改动即时保存{saved ? " · 已保存 ✓" : ""}</p>

    <h3>输出</h3>
    <label>输出语言（AI 总结）
      <select bind:value={s.options.summary_lang} onchange={touch}>
        <option value="zh">简体中文</option><option value="zh-en">中英对照</option><option value="en">English</option>
      </select></label>
    <label>简繁
      <select bind:value={s.options.zh_script} onchange={touch}>
        <option value="auto">自动</option><option value="simplified">简体</option><option value="traditional">繁体</option>
      </select></label>

    <h3>语音识别</h3>
    <label>字幕模型
      <select bind:value={s.options.asr_model} onchange={touch}>
        <option value={null}>自动（推荐）</option><option value="tiny">tiny（最快）</option>
        <option value="small">small（默认）</option><option value="medium">medium（最准）</option>
      </select></label>
    <label class="row">AI 字幕校对
      <input type="checkbox" bind:checked={s.options.auto_correct} onchange={touch} /></label>

    <h3>AI 分析（OpenAI 兼容接口）</h3>
    <label>接口地址<input bind:value={s.llm.api_base} oninput={touch} placeholder="不配置则跳过 AI 步骤" /></label>
    <label>API Key<input type="password" bind:value={s.llm.api_key} oninput={touch} /></label>
    <label>模型<input bind:value={s.llm.model} oninput={touch} /></label>

    <h3>关键帧（高级）</h3>
    <label>场景切换灵敏度
      <select bind:value={s.options.scene_threshold} onchange={touch}>
        <option value={null}>标准</option><option value={0.05}>更多页数（画面琐碎）</option>
        <option value={0.12}>更少页数（课件翻页少）</option>
      </select></label>
    <label>关键帧最小间隔
      <select bind:value={s.options.min_gap} onchange={touch}>
        <option value={null}>2 秒</option><option value={5}>5 秒</option><option value={10}>10 秒</option>
      </select></label>

    <h3>日志</h3>
    <label class="row">保留运行日志
      <input type="checkbox" bind:checked={s.app.keep_log} onchange={touch} /></label>
    <button class="ghost" onclick={() => openPath(s.logs_dir)}>打开日志文件夹</button>

    <h3>关于</h3>
    <p class="about">Chalkpress · 讲座视频 → 讲义 PDF<br />AGPL-3.0 开源 · 商用请联系作者<br />当前版本见窗口标题；更新自动进行</p>
  </aside>
{:else}
  <div class="mask" onclick={onClose}></div>
{/if}

<style>
  .mask { position: fixed; inset: 0; background: rgba(0,0,0,.25); }
  .sheet { position: fixed; top: 0; right: 0; bottom: 0; width: 380px; background: var(--card);
           box-shadow: -8px 0 32px rgba(0,0,0,.12); padding: 18px 22px 32px; overflow-y: auto;
           animation: slide .18s ease-out; }
  @keyframes slide { from { transform: translateX(40px); opacity: 0; } }
  header { display: flex; justify-content: space-between; align-items: center; }
  h2 { margin: 0; font-size: 17px; }
  h3 { font-size: 12px; color: var(--ink2); margin: 20px 0 6px; text-transform: none; }
  label { display: block; font-size: 13px; margin: 10px 0; }
  label.row { display: flex; justify-content: space-between; align-items: center; }
  input[type="text"], input:not([type]), input[type="password"], select {
      width: 100%; margin-top: 4px; padding: 7px 10px; border: 1px solid var(--line);
      border-radius: 8px; font: inherit; background: var(--card); }
  input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  .hint { color: var(--ink2); font-size: 12px; margin: 4px 0 0; }
  .about { color: var(--ink2); font-size: 12px; }
  .x { border: 0; background: transparent; font-size: 16px; cursor: pointer; }
  .ghost { border: 1px solid var(--line); background: var(--card); border-radius: 8px;
           padding: 7px 14px; cursor: pointer; }
</style>
