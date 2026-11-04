"""The relay: does a Django call actually reach a device and come back?

These tests drive the real consumer over a real WebSocket communicator with a
scripted runner on the other end. No mocks of the channel layer.
"""
from __future__ import annotations

import asyncio

import pytest
from channels.testing import WebsocketCommunicator

from execution.base import Command, SessionHandle
from execution.consumers import RunnerConsumer
from execution.local import LocalRunnerBackend
from execution.models import LocalRunnerDevice
from execution.presence import is_online
from execution.relay import DeviceOffline, RelayError, RunnerRefused, RunnerRelay

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def device(org, profile):
    return LocalRunnerDevice.objects.create(
        organization=org, name="Workstation", fingerprint="d" * 32, paired_by=profile
    )


def _connect(device):
    communicator = WebsocketCommunicator(RunnerConsumer.as_asgi(), "/ws/runner/")
    communicator.scope["device"] = device
    return communicator


def test_exec_round_trip_reaches_the_device(device):
    async def scenario():
        communicator = _connect(device)
        connected, _ = await communicator.connect()
        assert connected is True
        assert is_online(str(device.id)) is True

        seen = {}

        async def scripted_runner():
            frame = await communicator.receive_json_from(timeout=3)
            seen.update(frame)
            await communicator.send_json_to(
                {
                    "type": "result",
                    "id": frame["id"],
                    "ok": True,
                    "data": {
                        "exit_code": 0,
                        "stdout": "hello\n",
                        "stderr": "",
                        "duration_ms": 7,
                    },
                }
            )

        runner_task = asyncio.create_task(scripted_runner())
        data = await RunnerRelay().request(
            str(device.id), {"type": "exec", "argv": ["echo", "hello"]}, timeout=5
        )
        await runner_task
        await communicator.disconnect()
        return data, seen

    data, seen = asyncio.run(scenario())

    assert data["stdout"] == "hello\n"
    assert seen["type"] == "exec"
    assert seen["argv"] == ["echo", "hello"]
    # The protocol version travels with every frame so a stale runner is visible.
    assert seen["v"] == 1


def test_refusal_is_surfaced_not_swallowed(device):
    async def scenario():
        communicator = _connect(device)
        await communicator.connect()

        async def scripted_runner():
            frame = await communicator.receive_json_from(timeout=3)
            await communicator.send_json_to(
                {
                    "type": "result",
                    "id": frame["id"],
                    "ok": False,
                    "error": "approval required: installing dependencies",
                }
            )

        task = asyncio.create_task(scripted_runner())
        try:
            await RunnerRelay().request(
                str(device.id), {"type": "exec", "argv": ["pip", "install", "x"]}, timeout=5
            )
            return None
        except RunnerRefused as exc:
            return str(exc)
        finally:
            await task
            await communicator.disconnect()

    assert "approval required" in asyncio.run(scenario())


def test_offline_device_fails_fast_without_waiting_for_the_timeout(device):
    """A dead laptop must not consume the task's whole timeout budget."""

    async def scenario():
        import time

        started = time.monotonic()
        try:
            await RunnerRelay().request(str(device.id), {"type": "exec"}, timeout=30)
        except DeviceOffline:
            return time.monotonic() - started
        return None

    elapsed = asyncio.run(scenario())
    assert elapsed is not None and elapsed < 1.0


def test_disconnect_wakes_in_flight_callers(device):
    async def scenario():
        communicator = _connect(device)
        await communicator.connect()

        async def hang_up():
            await communicator.receive_json_from(timeout=3)  # swallow the frame
            await communicator.disconnect()

        task = asyncio.create_task(hang_up())
        try:
            await RunnerRelay().request(
                str(device.id), {"type": "exec", "argv": ["sleep", "300"]}, timeout=30
            )
            return None
        except RunnerRefused as exc:
            return str(exc)
        finally:
            await task

    # Not a 30s hang: the consumer signals the caller on disconnect.
    assert "disconnected" in asyncio.run(scenario())


def test_output_frames_are_published_to_the_session_stream(device):
    from execution.stream import subscribe

    async def scenario():
        communicator = _connect(device)
        await communicator.connect()

        chunks = []

        async def listen():
            async for payload in subscribe("sess-1"):
                chunks.append(payload)
                break

        listener = asyncio.create_task(listen())
        await asyncio.sleep(0.05)
        await communicator.send_json_to(
            {"type": "output", "session": "sess-1", "stream": "stdout", "seq": 1, "data": "$ "}
        )
        await asyncio.wait_for(listener, timeout=3)
        await communicator.disconnect()
        return chunks

    chunks = asyncio.run(scenario())
    assert chunks[0]["data"] == "$ "
    assert chunks[0]["stream"] == "stdout"


class _FakeRelay:
    """Records the frames the adapter would put on the wire."""

    def __init__(self, data=None, error=None):
        self.data = data or {}
        self.error = error
        self.calls = []

    def request_sync(self, device_id, frame, timeout=None, require_online=True):
        self.calls.append((device_id, frame, timeout))
        if self.error:
            raise self.error
        return self.data


def _handle():
    return SessionHandle(
        session_id="local-abc", provider="local", workspace="/home/dev/proj", device_id="dev-1"
    )


def test_adapter_maps_a_command_onto_the_wire_protocol():
    relay = _FakeRelay(
        {"exit_code": 2, "stdout": "out", "stderr": "err", "duration_ms": 11, "truncated": True}
    )
    backend = LocalRunnerBackend(relay=relay)

    result = backend.exec(_handle(), Command(argv=["pytest", "-q"], cwd="api", timeout_seconds=30))

    device_id, frame, timeout = relay.calls[0]
    assert device_id == "dev-1"
    assert frame == {
        "type": "exec",
        "argv": ["pytest", "-q"],
        "cwd": "api",
        "timeout_seconds": 30,
        "approval_id": None,
    }
    # Client timeout sits above the runner's so the runner reports the kill.
    assert timeout == 45.0
    assert (result.exit_code, result.stdout, result.stderr, result.truncated) == (
        2, "out", "err", True,
    )


def test_adapter_refuses_to_run_without_a_device():
    backend = LocalRunnerBackend(relay=_FakeRelay())
    with pytest.raises(ValueError):
        backend.create_session.__self__  # sanity: attribute access is fine
        from execution.base import SessionSpec

        backend.create_session(SessionSpec(run_id="r", organization_id="o", workspace_subpath="/x"))


def test_stop_is_idempotent_when_the_device_is_already_gone():
    backend = LocalRunnerBackend(relay=_FakeRelay(error=DeviceOffline("gone")))
    backend.stop(_handle())  # must not raise


def test_files_are_base64_on_the_wire():
    import base64

    payload = base64.b64encode(b"print(1)\n").decode()
    backend = LocalRunnerBackend(relay=_FakeRelay({"content": payload}))
    assert backend.read_file(_handle(), "main.py") == b"print(1)\n"

    writer = _FakeRelay({})
    LocalRunnerBackend(relay=writer).write_file(_handle(), "main.py", b"x")
    assert writer.calls[0][1]["type"] == "fs.write"
    assert base64.b64decode(writer.calls[0][1]["content"]) == b"x"
