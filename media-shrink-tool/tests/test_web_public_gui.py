import os
from pathlib import Path
import subprocess
import sys
import threading
import asyncio

import pytest
from PIL import Image

from media_shrink import gui


def test_controller_selection_progress_and_partial_failure(tmp_path):
    root = tmp_path / "日本語 入力"
    root.mkdir()
    for name in ("one.png", "two.png", "unselected.png"):
        Image.new("RGBA", (20,30), (20,40,60,100)).save(root/name)
    (root/"bad.png").write_bytes(b"bad")
    controller = gui.ConversionController()
    assert controller.start(root, tmp_path/"out", "graphic", ["one.png", "two.png", "bad.png"])
    controller.future.result(timeout=20)
    state = controller.snapshot()
    assert state["processed"] == 3 and state["total"] == 3
    assert not state["running"]
    result = state["result"]
    assert result.success_count == 2 and result.error_count == 1
    assert all(r["output_format"] == "PNG" for r in result.results if r["action"] != "ERROR")
    assert "一部失敗" in gui.result_message(result)
    assert controller.output_to_open() == result.files_dir


def test_double_start_rejected_while_worker_runs(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return None
    monkeypatch.setattr(gui, "run_web_public", slow)
    controller = gui.ConversionController()
    try:
        assert controller.start(tmp_path, None, "photo", ["a.jpg"])
        assert entered.wait(2)
        assert not controller.start(tmp_path, None, "graphic", ["b.png"])
        assert controller.snapshot()["running"]
    finally:
        release.set()
        controller.future.result(timeout=10)


def test_manifest_failure_not_opened(tmp_path):
    from media_shrink.web_public_batch import BatchResult
    controller = gui.ConversionController()
    controller.result = BatchResult(files_dir=tmp_path, manifest_error="failed")
    assert controller.output_to_open() is None
    assert "完了していません" in gui.result_message(controller.result)


def test_preview_and_conversion_share_exclusion(tmp_path):
    controller = gui.ConversionController()
    assert controller.start_preview()
    assert not controller.start_preview()
    assert not controller.start(tmp_path, None, "photo", ["one.jpg"])
    controller.finish_preview()
    assert controller.start_preview()
    controller.finish_preview()
    controller.running = True
    assert not controller.start_preview()


def test_cli_import_does_not_load_nicegui():
    result = subprocess.run([sys.executable, "-c",
        "import media_shrink.cli, sys; assert 'nicegui' not in sys.modules"], capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("origin,allowed", [(None, True),
    ("http://127.0.0.1:8080", True), ("http://localhost:8080", True),
    ("https://evil.test", False), ("null", False), ("http://localhost:9999", False)])
def test_local_origin_boundary(origin, allowed):
    assert gui.local_request_allowed("127.0.0.1:8080", origin, 8080) == allowed
    assert not gui.local_request_allowed("evil.test:8080", origin, 8080)


def test_launcher_uses_prepared_environment():
    launcher = Path(__file__).parents[1] / "run-web-public.cmd"
    content = launcher.read_text(encoding="utf-8-sig")
    assert '%~dp0' in content and '.venv\\Scripts\\python.exe"' in content
    assert ' -m media_shrink gui' in content
    assert 'uv run ' not in content


def test_real_nicegui_page_poll(monkeypatch):
    ui = pytest.importorskip("nicegui.ui")
    callbacks = []
    monkeypatch.setattr(ui, "timer", lambda interval, callback: callbacks.append(callback))
    gui.build_page(gui.ConversionController())
    assert len(callbacks) == 1
    callbacks[0]()


def test_repeated_same_failure_replaces_running_message(tmp_path, monkeypatch):
    ui = pytest.importorskip("nicegui.ui")
    from nicegui import run
    callbacks = []
    monkeypatch.setattr(ui, "timer", lambda interval, callback: callbacks.append(callback))
    async def inline(function, *args):
        return function(*args)
    monkeypatch.setattr(run, "io_bound", inline)
    handlers = {}
    original_on_click = ui.button.on_click
    def capture(self, callback):
        handlers[self.text] = callback
        return original_on_click(self, callback)
    monkeypatch.setattr(ui.button, "on_click", capture)
    root = tmp_path/"input"
    root.mkdir()
    Image.new("RGB", (10,10)).save(root/"one.png")
    class FailingController(gui.ConversionController):
        def start(self, *args):
            self.error = "同じNAS接続エラー"
            return True
    controller = FailingController()
    before = set(ui.context.client.elements)
    gui.build_page(controller)
    elements = [e for id,e in ui.context.client.elements.items() if id not in before]
    input_box = next(e for e in elements if isinstance(e, ui.input) and e.label == "入力フォルダー")
    input_box.value = str(root)
    asyncio.run(handlers["画像を一覧に表示"]())
    for _ in range(2):
        handlers["変換する"]()
        callbacks[0]()
        assert any(isinstance(e, ui.label) and e.text == "同じNAS接続エラー" for e in elements)
        assert not any(isinstance(e, ui.label) and e.text == "変換中です" for e in elements)


def _page_controls(tmp_path, monkeypatch, controller):
    ui = pytest.importorskip("nicegui.ui")
    from nicegui import run
    callbacks, handlers = [], {}
    monkeypatch.setattr(ui, "timer", lambda interval, callback: callbacks.append(callback))
    monkeypatch.setattr(ui, "notify", lambda *args, **kwargs: None)
    async def inline(function, *args):
        return function(*args)
    monkeypatch.setattr(run, "io_bound", inline)
    original = ui.button.on_click
    def capture(self, callback):
        handlers[self.text] = callback
        return original(self, callback)
    monkeypatch.setattr(ui.button, "on_click", capture)
    root = tmp_path/"input"; root.mkdir()
    Image.new("RGB", (10,10)).save(root/"one.png")
    before = set(ui.context.client.elements)
    gui.build_page(controller)
    elements = [e for id,e in ui.context.client.elements.items() if id not in before]
    next(e for e in elements if isinstance(e, ui.input) and e.label == "入力フォルダー").value = str(root)
    asyncio.run(handlers["画像を一覧に表示"]())
    return ui, root, elements, handlers, callbacks[0]


def test_failed_restart_clears_previous_success_counts(tmp_path, monkeypatch):
    controller = gui.ConversionController()
    ui, root, elements, handlers, poll = _page_controls(tmp_path, monkeypatch, controller)
    controller.result = gui.run_web_public(root, tmp_path/"out", gui.WebPublicConfig())
    poll()
    assert any(isinstance(e, ui.label) and "成功 1枚" in str(e.text) for e in elements)
    def failed(*args):
        controller.result = None
        controller.error = "入力フォルダーを読めません"
        return True
    monkeypatch.setattr(controller, "start", failed)
    handlers["変換する"](); poll()
    assert any(isinstance(e, ui.label) and e.text == controller.error for e in elements)
    assert not any(isinstance(e, ui.label) and "成功 1枚" in str(e.text) for e in elements)


def test_preview_clicks_are_serialized_and_failure_releases(tmp_path, monkeypatch):
    controller = gui.ConversionController()
    ui, root, elements, handlers, poll = _page_controls(tmp_path, monkeypatch, controller)
    from nicegui import run
    active = peak = calls = 0
    async def delayed(*args):
        nonlocal active, peak, calls
        active += 1; calls += 1; peak = max(active, peak)
        await asyncio.sleep(.02)
        active -= 1
        raise OSError("synthetic preview failure")
    monkeypatch.setattr(run, "io_bound", delayed)
    async def clicks():
        await asyncio.gather(*(handlers["拡大して確認"]() for _ in range(5)))
    asyncio.run(clicks())
    assert peak == calls == 1
    asyncio.run(handlers["拡大して確認"]())
    assert calls == 2
    assert controller.start_preview()  # no leaked busy state after exceptions
    controller.finish_preview()


def test_cancelled_preview_keeps_lock_until_decode_finishes(tmp_path, monkeypatch):
    controller = gui.ConversionController()
    ui, root, elements, handlers, poll = _page_controls(tmp_path, monkeypatch, controller)
    from nicegui import run
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def decode(*args):
            entered.set()
            await release.wait()
            raise OSError("decoder finished after client cancellation")
        monkeypatch.setattr(run, "io_bound", decode)
        task = asyncio.create_task(handlers["拡大して確認"]())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not controller.start_preview()
        release.set()
        for _ in range(10):
            await asyncio.sleep(0)
            if not controller.snapshot()["preview_running"]:
                break
        assert controller.start_preview()
        controller.finish_preview()
    asyncio.run(scenario())


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd launcher")
def test_launcher_japanese_space_path_port_conflict(tmp_path):
    import socket
    package = Path(__file__).parents[1]
    prepared = tmp_path/"日本語 起動"
    prepared.mkdir()
    launcher = prepared/"run-web-public.cmd"
    launcher.write_bytes((package/launcher.name).read_bytes())
    try:
        (prepared/".venv").symlink_to(package/".venv", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"prepared environment link unavailable: {exc}")
    with socket.socket() as guard:
        try:
            guard.bind(("127.0.0.1",8080))
            guard.listen()
        except OSError:
            pass  # A real local GUI also exercises the port-conflict diagnostic.
        result = subprocess.run(["cmd.exe", "/d", "/c", str(launcher)], input="\n",
            capture_output=True, encoding="utf-8", errors="replace", timeout=15,
            env={**os.environ, "PYTHONUTF8":"1"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "8080" in result.stdout and "使用中" in result.stdout, result.stdout + result.stderr
