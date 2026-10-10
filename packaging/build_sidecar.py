#!/usr/bin/env python3
"""构建 Tauri sidecar：PyInstaller 打包 chalkpress.ipc，输出到 src-tauri/binaries/。

用法：python packaging/build_sidecar.py [--dev]
--dev 额外产出无 target-triple 后缀的副本（调试用）。
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MODEL_DIR = ROOT / "build" / "model"
OUT = ROOT / "src-tauri" / "binaries"


def target_triple() -> str:
    out = subprocess.check_output(["rustc", "-vV"], text=True)
    return next(l.split(": ", 1)[1].strip() for l in out.splitlines()
                if l.startswith("host:"))


def ensure_model():
    if MODEL_DIR.is_dir() and any(MODEL_DIR.iterdir()):
        return
    print("下载 whisper-small 模型到 build/model ...", file=sys.stderr)
    from huggingface_hub import snapshot_download
    snapshot_download("Systran/faster-whisper-small", local_dir=str(MODEL_DIR))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true")
    args = ap.parse_args()
    ensure_model()
    OUT.mkdir(parents=True, exist_ok=True)
    sep = ";" if sys.platform == "win32" else ":"
    triple = target_triple()
    # ipc.py 用相对导入（from .config import ...），不能作为顶层脚本打包；
    # 改打包一个以包路径导入的入口 stub
    work = ROOT / "build" / "pyi"
    work.mkdir(parents=True, exist_ok=True)
    stub = work / "_sidecar_entry.py"
    stub.write_text("from chalkpress.ipc import main\n\nmain()\n", encoding="utf-8")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
        "--name", f"chalkpress-core-{triple}" if not args.dev else "chalkpress-core-dev",
        "--collect-all", "faster_whisper", "--collect-all", "ctranslate2",
        "--collect-all", "imageio_ffmpeg", "--collect-all", "onnxruntime",
        "--collect-all", "tokenizers", "--collect-all", "av",
        "--add-data", f"{MODEL_DIR}{sep}models/faster-whisper-small",
        "--distpath", str(OUT), "--workpath", str(work),
        "--specpath", str(work), "--paths", str(ROOT),
        str(stub),
    ], check=True, cwd=ROOT)
    # onefile：Tauri externalBin 要求单个可执行文件；启动解压稍慢是可接受的代价


if __name__ == "__main__":
    main()
