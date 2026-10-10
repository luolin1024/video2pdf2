# tests/test_ipc.py
import io
import json
import time

from chalkpress.ipc import sanitize_progress


def make_server():
    from chalkpress.ipc import IPCServer
    return IPCServer(stdin=io.StringIO(), stdout=io.StringIO())


def lines(server):
    out = server.stdout.getvalue()
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def test_unknown_method_returns_error():
    s = make_server()
    resp = s.handle({"id": 1, "method": "nope"})
    assert resp["id"] == 1 and "unknown method" in resp["error"]


def test_settings_roundtrip(tmp_path, monkeypatch):
    import chalkpress.config as config
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    s = make_server()
    s.handle({"id": 1, "method": "settings.set",
              "params": {"options": {"summary_lang": "en"}, "app": {}}})
    resp = s.handle({"id": 2, "method": "settings.get"})
    assert resp["result"]["options"]["summary_lang"] == "en"
    assert resp["result"]["llm_configured"] is False


def test_convert_start_empty_batch_emits_batch_done():
    s = make_server()
    s.handle({"id": 1, "method": "convert.start", "params": {"videos": []}})
    deadline = time.time() + 5
    while s.worker.is_alive() and time.time() < deadline:
        time.sleep(0.02)
    evs = [m["event"] for m in lines(s) if "event" in m]
    assert evs[-1] == "batch_done"


def test_cancel_sets_event():
    s = make_server()
    s.handle({"id": 1, "method": "convert.cancel"})
    assert s.cancel.is_set()


def test_serve_skips_non_json_lines():
    from chalkpress.ipc import IPCServer
    stdin = io.StringIO('not json\n{"id":1,"method":"nope"}\n\n')
    out = io.StringIO()
    s = IPCServer(stdin=stdin, stdout=out)
    s.serve()
    msgs = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    assert len(msgs) == 1 and "error" in msgs[0]


def test_fs_list_videos(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("x")
    s = make_server()
    resp = s.handle({"id": 1, "method": "fs.list_videos", "params": {"dir": str(tmp_path)}})
    assert resp["result"]["videos"] == [str(tmp_path / "a.mp4")]


def test_sanitize_progress_result_to_dict():
    """Result 数据类不可 JSON 序列化，必须展平为标量字段。"""
    class FakeResult:
        frames = [1, 2, 3]
        summary_md = "# t"
        outdir = None
    ev, kw = sanitize_progress("video_done", {"index": 1, "result": FakeResult()})
    assert ev == "video_done"
    assert "result" not in kw
    assert kw["pages"] == 3 and kw["summary"] is True
    json.dumps(kw)  # 必须可序列化
