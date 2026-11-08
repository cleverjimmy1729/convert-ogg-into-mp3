#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
写在前面

尊重原创版权，转换完后仅个人使用，禁止用于任何商业用途！！！
本脚本的用途是将.ogg文件转为.mp3文件，使用deeseek辅助编程

使用方法
STEP1 将这个脚本存在桌面上，文件名命名为 ogg2mp3_batch
STEP2 Win+R 打开 powershell
STEP3 cd (桌面路径)
STEP4 python ogg2mp3_batch.py -i "带转换的路径" -o "转换后要保存到的路径" -r -j 8
STEP5 等待转换完成 :-)


"""

import argparse
import concurrent.futures
import glob
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------- ffmpeg 定位
def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    if sys.platform.startswith("win"):
        for c in [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
        ]:
            if os.path.isfile(c):
                return c
    raise FileNotFoundError(
        "找不到 ffmpeg，请先安装并加入 PATH：\n"
        "  Windows: https://www.gyan.dev/ffmpeg/builds/\n"
        "  macOS  : brew install ffmpeg\n"
        "  Linux  : sudo apt install ffmpeg"
    )


_FFMPEG = None


def ffmpeg_path():
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = find_ffmpeg()
    return _FFMPEG


# ---------------------------------------------------------------- 小工具
def clean_path(s: str) -> str:
    return s.strip().strip('"').strip("'").strip()


def collect_ogg_files(inputs, recursive=False):
    """
    支持：单文件 / 目录 / 通配符。
    返回 [(Path, base_dir)]，base_dir 用于计算相对输出路径。
    """
    result, seen = [], set()

    def add(p: Path, base: Path):
        rp = p.resolve()
        if rp in seen:
            return
        seen.add(rp)
        result.append((p, base))

    for raw in inputs:
        s = clean_path(raw)
        if not s:
            continue

        # 通配符
        if any(ch in s for ch in "*?["):
            for m in glob.glob(s, recursive=recursive):
                mp = Path(m)
                if mp.is_file() and mp.suffix.lower() == ".ogg":
                    add(mp, mp.parent)
            continue

        p = Path(s).expanduser()

        if p.is_file():
            if p.suffix.lower() != ".ogg":
                print(f"[跳过] 非 OGG 文件：{p}")
                continue
            add(p, p.parent)
        elif p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            for mp in it:
                if mp.is_file() and mp.suffix.lower() == ".ogg":
                    add(mp, p)
        else:
            print(f"[警告] 路径不存在：{p}")

    return result


def map_output(src: Path, base: Path, out_dir: Path, flat: bool) -> Path:
    if flat:
        return out_dir / (src.stem + ".mp3")
    try:
        rel = src.relative_to(base)
    except ValueError:
        rel = Path(src.name)
    return (out_dir / rel).with_suffix(".mp3")


# ---------------------------------------------------------------- 单文件转换
def convert_one(src: Path, out: Path, bitrate: str, skip_existing: bool):
    if skip_existing and out.exists():
        return "skip"

    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_path(),
        "-loglevel", "error",
        "-y",
        "-i", str(src),
        "-vn",                        # 忽略封面图等非音频流
        "-codec:a", "libmp3lame",
        "-b:a", bitrate,
        str(out),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip() or "ffmpeg 返回非零退出码")
    return "ok"


# ---------------------------------------------------------------- 主流程
def main() -> int:
    parser = argparse.ArgumentParser(
        description="批量把 OGG 转成 MP3（支持目录 / 通配符 / 并行）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-i", "--input", nargs="+", required=True,
                        help="输入：文件 / 目录 / 通配符，可写多个")
    parser.add_argument("-o", "--output", required=True, help="输出目录")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="递归扫描子目录")
    parser.add_argument("-j", "--jobs", type=int, default=0,
                        help="并行任务数，0=自动（CPU 核心数，上限 8）")
    parser.add_argument("-b", "--bitrate", default="192k",
                        help="MP3 码率，如 128k / 192k / 320k（默认 192k）")
    parser.add_argument("--skip-existing", action="store_true",
                        help="目标 MP3 已存在时跳过（增量转换用）")
    parser.add_argument("--flat", action="store_true",
                        help="全部平铺到输出目录，不保留子目录结构")
    args = parser.parse_args()

    # 收集文件
    pairs = collect_ogg_files(args.input, recursive=args.recursive)
    if not pairs:
        print("没有找到任何 .ogg 文件")
        return 1

    out_dir = Path(clean_path(args.output)).expanduser()

    # 生成任务
    tasks = [(src, map_output(src, base, out_dir, args.flat)) for src, base in pairs]

    # 冲突检测（同一输出被两个源文件占用）
    seen_out = {}
    for src, out in tasks:
        key = str(out.resolve())
        if key in seen_out:
            print(f"[错误] 输出冲突：\n  {seen_out[key]}\n  {src}\n都指向 {out}")
            print("提示：去掉 --flat，或换一个输出目录")
            return 1
        seen_out[key] = src

    jobs = args.jobs if args.jobs > 0 else min(os.cpu_count() or 4, 8)
    total = len(tasks)

    print(f"找到 {total} 个 OGG 文件")
    print(f"输出目录：{out_dir}")
    print(f"并行任务：{jobs}    码率：{args.bitrate}")
    print("-" * 60)

    ok = skipped = 0
    failed = []
    done = 0
    t0 = time.time()
    bar_width = 30

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            futures = {
                ex.submit(convert_one, src, out, args.bitrate, args.skip_existing): (src, out)
                for src, out in tasks
            }

            for fut in concurrent.futures.as_completed(futures):
                src, out = futures[fut]
                done += 1
                try:
                    status = fut.result()
                    if status == "ok":
                        ok += 1
                    else:
                        skipped += 1
                except Exception as e:
                    failed.append((src, str(e)))

                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                filled = int(bar_width * done / total)
                bar = "#" * filled + "-" * (bar_width - filled)
                sys.stdout.write(
                    f"\r[{bar}] {done}/{total}  "
                    f"成功 {ok}  跳过 {skipped}  失败 {len(failed)}  "
                    f"ETA {eta:4.0f}s"
                )
                sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\n[中断] 用户取消")
        return 130

    print()
    print("-" * 60)
    print(f"完成！成功 {ok}，跳过 {skipped}，失败 {len(failed)}，"
          f"耗时 {time.time() - t0:.1f}s")

    if failed:
        print("\n失败列表：")
        for src, msg in failed[:20]:
            print(f"  × {src}")
            print(f"      {msg}")
        if len(failed) > 20:
            print(f"  … 还有 {len(failed) - 20} 个，省略")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
