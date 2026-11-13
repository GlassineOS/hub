"""SIGTERM stops hubd's server through its cleanup, so design renderers don't outlive it."""
import asyncio
import os
import signal

from hubd import server


class FakeDesigns:
    def __init__(self):
        self.stopped = []

    def running(self):
        return ["design-1"]

    async def stop(self, name):
        self.stopped.append(name)

    async def reap(self):
        pass

    async def tick(self):
        pass


class FakeHubd:
    def __init__(self):
        self.designs = FakeDesigns()

    async def connection(self, reader, writer):
        writer.close()


def test_sigterm_stops_renderers(tmp_path, monkeypatch):
    async def idle(_hubd):
        await asyncio.Event().wait()

    for name in ("_tidy", "_keep_copies", "_ping"):
        monkeypatch.setattr(server, name, idle)
    hubd = FakeHubd()

    async def run():
        task = asyncio.ensure_future(server.serve(hubd, tmp_path / "s" / "hubd.sock"))
        await asyncio.sleep(0.2)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, 5)

    asyncio.run(run())
    assert hubd.designs.stopped == ["design-1"]
