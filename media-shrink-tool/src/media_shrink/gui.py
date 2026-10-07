"""担当者PCだけで動く掲載用マスター画面。画像処理はweb_publicへ委譲する。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import asyncio
import os
import socket
import threading

from .utils import human_size
from .web_public import WebPublicConfig, run_web_public
from .web_public_batch import default_output, select_images


class ConversionController:
    """UIから独立した実行状態。タブ切断は実行中のfutureを取り消さない。"""
    def __init__(self):
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-public-gui")
        self.running = False
        self.preview_running = False
        self.processed = 0
        self.total = 0
        self.result = None
        self.error = None
        self.future = None

    def start(self, input_dir, output_dir, kind, selected_files):
        with self._lock:
            if self.running or self.preview_running:
                return False
            self.running, self.processed, self.total = True, 0, len(selected_files)
            self.result, self.error = None, None
        self.future = self._executor.submit(self._work, Path(input_dir), output_dir,
                                            kind, list(selected_files))
        return True

    def start_preview(self):
        with self._lock:
            if self.running or self.preview_running:
                return False
            self.preview_running = True
            return True

    def finish_preview(self):
        with self._lock:
            self.preview_running = False

    def _on_result(self, row):
        with self._lock:
            self.processed += 1

    def _work(self, input_dir, output_dir, kind, selected_files):
        try:
            result = run_web_public(input_dir, output_dir, WebPublicConfig(kind),
                selected_files=selected_files, on_result=self._on_result)
            with self._lock:
                self.result = result
        except Exception as exc:
            with self._lock:
                self.error = f"実行できませんでした: {exc}"
        finally:
            with self._lock:
                self.running = False

    def snapshot(self):
        with self._lock:
            return dict(running=self.running, preview_running=self.preview_running,
                        processed=self.processed, total=self.total,
                        result=self.result, error=self.error)

    def output_to_open(self):
        state = self.snapshot()
        result = state["result"]
        if state["running"] or not result or result.manifest_error or not result.success_count:
            return None
        directory = result.files_dir
        if directory is None or not directory.is_dir():
            return None
        # Recheck the exact current-run path before handing it to the OS.
        from .web_public_batch import _no_links
        _no_links(directory)
        if directory.name != "files" or directory.parent.name != result.run_id:
            return None
        return directory


def result_message(result):
    if result.manifest_error:
        return "完了していません。" + result.manifest_error
    if result.error_count and result.success_count:
        return "一部失敗。成功した画像のみ入っています"
    if result.error_count:
        return "変換できた画像はありません。失敗理由を確認してください"
    return "変換が完了しました。今回の画像を確認して入稿してください"


def local_request_allowed(host, origin, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    return host in hosts and (origin is None or origin in {"http://" + x for x in hosts})


def _choose_directory(initial):
    import tkinter as tk
    from tkinter import filedialog
    window = tk.Tk()
    window.withdraw()
    window.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(parent=window, title="入力フォルダーを選択", initialdir=initial or None)
    finally:
        window.destroy()


def _preview(root, relative, width):
    # No static directory mount: only selected, bounded, decoded pixels reach the browser.
    from .web_public import _prepare, MAX_BYTES
    _, sources = select_images(root, [relative])
    if sources[0].stat().st_size > MAX_BYTES:
        raise ValueError("プレビューの入力上限を超えています")
    image, _, _, _ = _prepare(sources[0], WebPublicConfig("graphic"))
    image.thumbnail((width, width))
    return image


def build_page(controller):
    from nicegui import ui, run

    ui.colors(primary="#245d52", secondary="#466a83", negative="#a32d35")
    ui.add_css('body { background: #f4f6f5; color: #20352e; } .q-table th {font-weight: 600;}')
    loaded_root = None
    displayed_result = None
    shown_error = None
    scan_busy = False
    preview_dialog = None
    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-5"):
        with ui.row().classes("items-baseline gap-4"):
            ui.label("KaruFile").classes("text-sm font-bold tracking-widest")
            ui.label("Web掲載用マスター").classes("text-3xl font-semibold")
        ui.label("写真や図版を選び、ホームページ入稿用の画像を作成します。原本はそのまま残ります。")
        ui.label("写り込んだ住所・看板・顔・車両番号は除去されません。入稿前に確認してください。").classes("text-sm text-slate-600")
        with ui.card().classes("w-full p-5 gap-3"):
            ui.label("1　画像を選ぶ").classes("text-lg font-semibold")
            with ui.row().classes("w-full items-center"):
                input_box = ui.input("入力フォルダー", placeholder="フォルダーを選択、またはNASのパスを貼り付け").classes("grow")
                async def choose():
                    try:
                        chosen = await run.io_bound(_choose_directory, input_box.value)
                        if chosen:
                            input_box.value = chosen
                    except Exception:
                        ui.notify("選択ダイアログを開けません。入力欄へフォルダーパスを貼り付けてください", type="warning")
                picker = ui.button("フォルダーを選択", on_click=choose).props("outline")
            async def scan():
                nonlocal loaded_root, scan_busy
                if scan_busy or controller.snapshot()["running"]:
                    return
                scan_busy = True
                scan_button.disable()
                table.rows, table.selected = [], []
                loaded_root = None
                try:
                    if not input_box.value.strip():
                        raise ValueError("入力フォルダーを指定してください")
                    root, sources = await run.io_bound(select_images, Path(input_box.value.strip()))
                    loaded_root = root
                    table.rows = [{"path": p.relative_to(root).as_posix()} for p in sources]
                    table.selected = list(table.rows)
                    table.update()
                    output_box.value = str(default_output(root))
                except Exception as exc:
                    ui.notify(str(exc), type="negative")
                finally:
                    scan_busy = False
                    scan_button.enable()
            scan_button = ui.button("画像を一覧に表示", on_click=scan)
            table = ui.table(columns=[{"name": "path", "label": "画像ファイル", "field": "path", "align": "left"}],
                             rows=[], row_key="path", selection="multiple", pagination=10).classes("w-full")
            def select_all():
                table.selected = list(table.rows)
                table.update()
            def clear_selection():
                table.selected = []
                table.update()
            async def preview(large=False):
                nonlocal preview_dialog
                if loaded_root is None or not table.selected:
                    ui.notify("確認する画像を選択してください", type="warning")
                    return
                if not controller.start_preview():
                    return
                selected = table.selected[0]["path"]
                poll()
                decode_task = None
                try:
                    decode_task = asyncio.create_task(run.io_bound(
                        _preview, loaded_root, selected, 1400 if large else 280))
                    pixels = await asyncio.shield(decode_task)
                    if pixels is None:
                        return  # NiceGUI is shutting down
                    if preview_dialog is not None and not preview_dialog.is_deleted:
                        preview_dialog.delete()
                    with ui.dialog() as dialog, ui.card().classes("max-w-5xl"):
                        ui.label(selected)
                        ui.image(pixels).style("width: min(80vw, 1100px)" if large else "width: 280px")
                        ui.label("選択した一覧の先頭画像です。原本の見た目を確認してください。").classes("text-sm")
                        ui.button("閉じる", on_click=dialog.close)
                    preview_dialog = dialog
                    dialog.on("hide", dialog.delete)
                    dialog.open()
                except Exception:
                    ui.notify("この画像のプレビューを作成できません", type="warning")
                finally:
                    if decode_task is not None and not decode_task.done():
                        # Client cancellation must not unlock a still-running decoder thread.
                        def decoded(task):
                            if not task.cancelled():
                                task.exception()  # consume a failure after the UI task ended
                            controller.finish_preview()
                        decode_task.add_done_callback(decoded)
                    else:
                        controller.finish_preview()
                    poll()
            with ui.row():
                all_button = ui.button("全選択", on_click=select_all).props("flat")
                clear_button = ui.button("全解除", on_click=clear_selection).props("flat")
                preview_button = ui.button("選択画像を確認", on_click=lambda: preview(False)).props("outline")
                enlarge_button = ui.button("拡大して確認", on_click=lambda: preview(True)).props("flat")
        with ui.card().classes("w-full p-5 gap-3"):
            ui.label("2　用途と保存先").classes("text-lg font-semibold")
            kind = ui.radio({"photo": "Web掲載写真", "graphic": "透過画像・図版"}, value="photo").props("inline")
            ui.label("写真はJPEG、図版は透過を保持したPNG。横幅は最大1400pxです。").classes("text-sm text-slate-600")
            output_box = ui.input("出力ルート（必要な場合のみ変更）").classes("w-full")
            def start():
                nonlocal shown_error
                if loaded_root is None or Path(os.path.abspath(input_box.value.strip())) != loaded_root:
                    ui.notify("入力フォルダーの画像一覧を表示し直してください", type="warning")
                    return
                selected = [r["path"] for r in table.selected]
                if not selected:
                    ui.notify("1枚以上選択してください", type="warning")
                    return
                if controller.start(loaded_root, Path(output_box.value.strip()) if output_box.value.strip() else None,
                                    kind.value, selected):
                    shown_error = None
                    result_table.rows = []
                    result_table.update()
                    output_label.text = ""
                    counts.text = ""
                    summary.text = "変換中です"
                    poll()
            convert = ui.button("変換する", on_click=start).classes("px-8")
            progress = ui.linear_progress(value=0).classes("w-full")
            progress_text = ui.label("画像を選択してください").classes("text-sm")
        with ui.card().classes("w-full p-5 gap-3"):
            ui.label("3　今回の結果").classes("text-lg font-semibold")
            summary = ui.label("変換結果がここに表示されます")
            counts = ui.label("")
            output_label = ui.label("").classes("break-all text-sm")
            result_table = ui.table(columns=[
                {"name": "path", "label": "元画像", "field": "path", "align": "left"},
                {"name": "status", "label": "結果", "field": "status", "align": "left"},
                {"name": "message", "label": "警告・失敗理由", "field": "message", "align": "left"}],
                rows=[], row_key="path", pagination=10).classes("w-full")
            def open_output():
                try:
                    folder = controller.output_to_open()
                    if folder and os.name == "nt":
                        os.startfile(str(folder))
                    else:
                        ui.notify("表示された今回の出力パスを開いてください")
                except OSError:
                    ui.notify("出力フォルダーを開けません。接続を確認してください", type="negative")
            open_button = ui.button("今回の出力フォルダーを開く", on_click=open_output).props("outline")
            open_button.disable()
    def poll():
        nonlocal displayed_result, shown_error
        state = controller.snapshot()
        busy = state["running"]
        preview_busy = state["preview_running"]
        for element in (convert, picker, input_box, output_box, kind, all_button, clear_button):
            element.set_enabled(not busy and not preview_busy and not scan_busy)
        for element in (preview_button, enlarge_button):
            element.set_enabled(not busy and not preview_busy and not scan_busy)
        table.props(f'loading={str(busy or preview_busy or scan_busy).lower()}')
        scan_button.set_enabled(not busy and not preview_busy and not scan_busy)
        if state["result"] is None and (busy or state["error"]):
            counts.text = ""
            output_label.text = ""
            if displayed_result is not None:
                displayed_result = None
                result_table.rows = []
                result_table.update()
        if state["total"]:
            progress.value = state["processed"] / state["total"]
            progress_text.text = f"処理済み {state['processed']} / {state['total']} 枚" + ("　変換中" if busy else "")
        open_button.set_enabled(not busy and bool(state["result"] and state["result"].success_count and not state["result"].manifest_error))
        if state["error"] and state["error"] != shown_error:
            summary.text = shown_error = state["error"]
        result = state["result"]
        if result is not None and result is not displayed_result:
            displayed_result = result
            summary.text = result_message(result)
            counts.text = (f"成功 {result.success_count}枚（うち警告 {result.warning_count}枚） / 失敗 {result.error_count}枚　"
                           f"成功分 {human_size(result.source_bytes)} → {human_size(result.output_bytes)}")
            if result.files_dir and not result.manifest_error:
                output_label.text = str(result.files_dir)
            warning_names = {"SRGB_ASSUMED": "sRGBとして扱いました", "OUTPUT_LARGER_THAN_SOURCE": "原本より容量が増えました"}
            result_table.rows = [{"path": r["source_path"],
                "status": {"CONVERTED": "変換済み", "SKIPPED_COMPLETE": "前回画像を再利用", "ERROR": "失敗"}[r["action"]],
                "message": r["error"]["message"] if r["error"] else " / ".join(warning_names.get(w,w) for w in r["warnings"])} for r in result.results]
            result_table.update()
    ui.timer(0.15, poll)


def main():
    from nicegui import ui, app
    from nicegui import core
    from starlette.responses import PlainTextResponse

    port = 8080
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        print("GUIを起動できません。127.0.0.1:8080が使用中です。起動済みKaruFileを確認し、解決しない場合はSEへ連絡してください")
        return 1
    controller = ConversionController()
    core.sio.eio.cors_allowed_origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    @app.middleware("http")
    async def local_only(request, call_next):
        if not local_request_allowed(request.headers.get("host"), request.headers.get("origin"), port):
            return PlainTextResponse("Local browser only", status_code=403)
        return await call_next(request)
    @ui.page("/")
    def index():
        build_page(controller)
    ui.run(host="127.0.0.1", port=port, show=True, reload=False, on_air=False,
           title="KaruFile | Web掲載用マスター", language="ja", favicon="🖼️")
    return 0
