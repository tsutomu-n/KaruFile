"""Measure conversion in a fresh process, excluding synthetic fixture generation."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess
import sys
import time

from excel_shrink.core import process_workbook


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    p.add_argument("--count", type=int, default=685)
    p.add_argument("--large", action="store_true")
    p.add_argument("--worker", action="store_true")
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    stem = "single-32mp" if args.large else f"images-{args.count}"
    source, output = (args.directory / f"{stem}-{side}.xlsx" for side in ("input", "output"))
    if not args.worker:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
        from fixtures import image_bytes, picture_anchor, write_workbook
        count = 1 if args.large else args.count
        data = image_bytes(size=(8000, 4000) if args.large else (320, 160))
        write_workbook(source, images={f"xl/media/image{i}.jpeg": data for i in range(1, count + 1)},
                       anchors=[picture_anchor(rid=f"rIdImage{i}") for i in range(1, count + 1)])
        subprocess.run([sys.executable, __file__, str(args.directory), "--count", str(args.count), "--worker",
                        *(["--large"] if args.large else [])], check=True)
        return
    started = time.monotonic()
    result = process_workbook(source, output)
    elapsed = time.monotonic() - started
    class Memory(C.Structure):
        _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [(n, C.c_size_t) for n in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    kernel = C.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = W.HANDLE
    psapi = C.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(Memory), W.DWORD]
    memory = Memory(); memory.cb = C.sizeof(memory)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), C.byref(memory), memory.cb):
        raise C.WinError()
    record = dict(status=result.status, images_total=result.images_total, images_changed=result.images_changed,
        elapsed_seconds=elapsed, peak_working_set=memory.PeakWorkingSetSize, private_bytes=memory.PrivateUsage,
        peak_pagefile=memory.PeakPagefileUsage, input_bytes=source.stat().st_size,
        candidate_disk_bytes=output.stat().st_size if output.exists() else 0)
    (args.directory / f"{stem}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record))
    if result.status != "ADOPTED_LOSSY" or result.images_changed != result.images_total:
        raise ValueError("Benchmark did not actually resize every image")


if __name__ == "__main__":
    main()
