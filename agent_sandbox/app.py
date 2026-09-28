from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from websockets.asyncio.client import connect as websocket_connect

PKG_ROOT = Path(__file__).resolve().parent
PRJ_ROOT = PKG_ROOT.parent
TEMP_DIR = PRJ_ROOT / "tmp"
LOGS_DIR = PRJ_ROOT / "logs"
STATIC_DIR = PKG_ROOT / "static"
IMAGES_DIR = PRJ_ROOT / "images"
RUNTIME_DIR = TEMP_DIR / "runtime"
START_SCRIPT = PRJ_ROOT / "scripts" / "image-cli.sh"
IMAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{20,80}$")
CONNECTION_LEASE_SECONDS = 45
SSE_KEEPALIVE_SECONDS = 15
PORTS = range(18100, 18200)
HOP_BY_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}
app = FastAPI(title="OpenCode Sandbox Manager")
app.mount("/manager/static", StaticFiles(directory=STATIC_DIR), name="static")
proxy_client = httpx.AsyncClient(timeout=None, follow_redirects=False)
SUBSCRIBERS: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue, str]] = set()
SUBSCRIBERS_LOCK = threading.Lock()


class ImageCreate(BaseModel):
    image_id: Annotated[str | None, Field(default=None, max_length=64)] = None


class SessionRequest(BaseModel):
    session_id: Annotated[str, Field(min_length=20, max_length=80)]


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID.fullmatch(session_id):
        raise HTTPException(422, "ブラウザーセッションIDが正しくありません。")
    return session_id


def validate_image_id(image_id: str) -> str:
    if not IMAGE_ID.fullmatch(image_id):
        raise HTTPException(422, "イメージ ID は英数字、-、_ の1〜64文字にしてください。")
    return image_id


def runtime_path(image_id: str) -> Path:
    return RUNTIME_DIR / f"{image_id}.json"


def read_runtime(image_id: str) -> dict | None:
    path = runtime_path(image_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_runtime(image_id: str, runtime: dict) -> None:
    RUNTIME_DIR.mkdir(exist_ok=True)
    path = runtime_path(image_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(runtime, ensure_ascii=False))
    temporary.replace(path)


def is_running(runtime: dict | None) -> bool:
    if not runtime or not isinstance(runtime.get("pid"), int):
        return False
    try:
        os.kill(runtime["pid"], 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{runtime['pid']}/stat").read_text().rsplit(")", 1)[1].split()[0]
        if state == "Z":
            return False
    except (FileNotFoundError, IndexError):
        return False
    return True


def connection_path(image_id: str) -> Path:
    return RUNTIME_DIR / f"{image_id}.connection.json"


@contextmanager
def connection_guard(image_id: str):
    RUNTIME_DIR.mkdir(exist_ok=True)
    lock_path = RUNTIME_DIR / f"{image_id}.connection.lock"
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_connection_unlocked(image_id: str) -> dict | None:
    path = connection_path(image_id)
    try:
        connection = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(connection, dict) or not isinstance(connection.get("session_id"), str):
        path.unlink(missing_ok=True)
        return None
    if time.time() - float(connection.get("last_seen", 0)) > CONNECTION_LEASE_SECONDS:
        path.unlink(missing_ok=True)
        return None
    return connection


def read_connection(image_id: str) -> dict | None:
    with connection_guard(image_id):
        return read_connection_unlocked(image_id)


def write_connection_unlocked(image_id: str, connection: dict) -> None:
    path = connection_path(image_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(connection))
    temporary.replace(path)


def claim_connection(image_id: str, session_id: str) -> dict:
    validate_session_id(session_id)
    with connection_guard(image_id):
        if not is_running(read_runtime(image_id)):
            raise HTTPException(409, "停止中のイメージは起動してから接続してください。")
        current = read_connection_unlocked(image_id)
        if current and current["session_id"] != session_id:
            raise HTTPException(409, "このイメージには別のセッションが接続中です。")
        connection = {"session_id": session_id, "last_seen": time.time()}
        write_connection_unlocked(image_id, connection)
    return connection


def release_connection(image_id: str, session_id: str) -> bool:
    validate_session_id(session_id)
    with connection_guard(image_id):
        current = read_connection_unlocked(image_id)
        if current and current["session_id"] == session_id:
            connection_path(image_id).unlink(missing_ok=True)
            return True
    return False


def require_connection(image_id: str, session_id: str | None) -> dict:
    validate_image_id(image_id)
    if not session_id:
        raise HTTPException(423, "接続セッションがありません。管理画面から接続してください。")
    validate_session_id(session_id)
    current = read_connection(image_id)
    if not current or current["session_id"] != session_id:
        raise HTTPException(423, "このイメージへの接続権がありません。")
    return current


def notify_image_status_changed() -> None:
    with SUBSCRIBERS_LOCK:
        subscribers = tuple(SUBSCRIBERS)
    for loop, queue, _session_id in subscribers:
        if loop.is_closed():
            continue
        loop.call_soon_threadsafe(signal_subscriber, queue)


def signal_subscriber(queue: asyncio.Queue) -> None:
    while queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    try:
        queue.put_nowait(None)
    except asyncio.QueueFull:
        pass


def release_session_connections(session_id: str) -> None:
    for image_id in image_ids():
        release_connection(image_id, session_id)


def keep_session_connections_alive(session_id: str) -> None:
    now = time.time()
    for image_id in image_ids():
        with connection_guard(image_id):
            connection = read_connection_unlocked(image_id)
            if connection and connection["session_id"] == session_id:
                connection["last_seen"] = now
                write_connection_unlocked(image_id, connection)


def sweep_expired_connections() -> bool:
    changed = False
    for image_id in image_ids():
        path = connection_path(image_id)
        with connection_guard(image_id):
            existed = path.exists()
            read_connection_unlocked(image_id)
            changed = changed or (existed and not path.exists())
    return changed


def image_payload(image_id: str, session_id: str | None = None) -> dict:
    runtime = read_runtime(image_id)
    running = is_running(runtime)
    connection = read_connection(image_id) if running else None
    status = "connected" if connection else "running" if running else "stopped"
    return {
        "id": image_id,
        "status": status,
        "connected_by_me": bool(connection and session_id and connection["session_id"] == session_id),
        "port": runtime.get("port") if running and runtime else None,
        "url": f"/?image_id={quote(image_id)}&session_id={quote(session_id)}" if running and connection and session_id and connection["session_id"] == session_id else None,
        "started_at": runtime.get("started_at") if running and runtime else None,
    }



def image_ids() -> list[str]:
    IMAGES_DIR.mkdir(exist_ok=True)
    return sorted(item.name for item in IMAGES_DIR.iterdir() if item.is_dir() and IMAGE_ID.fullmatch(item.name))


def free_port() -> int:
    used = {data.get("port") for image_id in image_ids() if (data := read_runtime(image_id)) and is_running(data)}
    for port in PORTS:
        if port in used:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise HTTPException(503, "利用可能なOpenCodeポートがありません。")


def proxy_port(image_id: str) -> int:
    validate_image_id(image_id)
    if image_id not in image_ids():
        raise HTTPException(404, "イメージが見つかりません。")
    runtime = read_runtime(image_id)
    if not runtime or not is_running(runtime):
        raise HTTPException(503, "イメージは起動していません。")
    port = runtime.get("port")
    if not isinstance(port, int):
        raise HTTPException(503, "イメージの待受ポートを取得できません。")
    return port


async def proxy_http(request: Request, image_id: str, path: str, *, session_id: str | None = None, select_image: bool = False):
    session_id = session_id or request.cookies.get("opencode_session")
    require_connection(image_id, session_id)
    port = proxy_port(image_id)
    query_items = [(key, value) for key, value in request.query_params.multi_items() if key not in {"image_id", "session_id"}]
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in query_items)
    upstream_origin = f"http://127.0.0.1:{port}"
    upstream_url = f"{upstream_origin}/{path}"
    if query:
        upstream_url += f"?{query}"

    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP_BY_HOP_HEADERS | {"host", "content-length", "cookie"}}
    if "origin" in headers:
        headers["origin"] = upstream_origin
    if "referer" in headers:
        headers["referer"] = upstream_origin + "/"

    upstream_request = proxy_client.build_request(request.method, upstream_url, headers=headers, content=request.stream())
    upstream = await proxy_client.send(upstream_request, stream=True)
    response_headers = {key: value for key, value in upstream.headers.items() if key.lower() not in HOP_BY_HOP_HEADERS | {"set-cookie"}}
    response = StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream.aclose),
    )
    if select_image:
        response.set_cookie("opencode_image", image_id, path="/", httponly=True, samesite="lax")
        response.set_cookie("opencode_session", session_id, path="/", httponly=True, samesite="lax")
    return response


@app.get("/", include_in_schema=False)
async def opencode_or_manager(request: Request):
    selected_id = request.query_params.get("image_id")
    if selected_id:
        return await proxy_http(request, selected_id, "", session_id=request.query_params.get("session_id"), select_image=True)
    if request.headers.get("sec-fetch-dest") == "iframe" and request.cookies.get("opencode_image"):
        return await proxy_http(request, request.cookies["opencode_image"], "", session_id=request.cookies.get("opencode_session"))
    return RedirectResponse("/manager/")


@app.get("/manager/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse( STATIC_DIR / "index.html")


@app.get("/manager/api/images")
def list_images(session_id: str | None = None) -> list[dict]:
    if session_id:
        validate_session_id(session_id)
    return [image_payload(image_id, session_id) for image_id in image_ids()]


@app.get("/manager/api/events", include_in_schema=False)
async def image_status_events(request: Request, session_id: str):
    validate_session_id(session_id)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    subscriber = (loop, queue, session_id)
    with SUBSCRIBERS_LOCK:
        SUBSCRIBERS.add(subscriber)

    async def stream():
        try:
            snapshot = [image_payload(image_id, session_id) for image_id in image_ids()]
            yield f"event: images\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while not await request.is_disconnected():
                try:
                    await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_SECONDS)
                    snapshot = [image_payload(image_id, session_id) for image_id in image_ids()]
                    yield f"event: images\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    await asyncio.to_thread(keep_session_connections_alive, session_id)
                    expired = await asyncio.to_thread(sweep_expired_connections)
                    if expired:
                        snapshot = [image_payload(image_id, session_id) for image_id in image_ids()]
                        yield f"event: images\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                    else:
                        yield ": keepalive\n\n"
        finally:
            with SUBSCRIBERS_LOCK:
                SUBSCRIBERS.discard(subscriber)
                session_still_open = any(subscriber[2] == session_id for subscriber in SUBSCRIBERS)
            if not session_still_open:
                release_session_connections(session_id)
                notify_image_status_changed()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.post("/manager/api/images", status_code=201)
def create_image(body: ImageCreate) -> dict:
    image_id = body.image_id or f"sbox-{int(time.time())}"
    validate_image_id(image_id)
    image_dir = IMAGES_DIR / image_id
    if image_dir.exists():
        raise HTTPException(409, "同じイメージ ID が既にあります。")
    (image_dir / "fs").mkdir(parents=True)
    result = image_payload(image_id)
    notify_image_status_changed()
    return result


@app.post("/manager/api/images/{image_id}/connect")
def connect_image(image_id: str, body: SessionRequest) -> dict:
    validate_image_id(image_id)
    if image_id not in image_ids():
        raise HTTPException(404, "イメージが見つかりません。")
    claim_connection(image_id, body.session_id)
    result = image_payload(image_id, body.session_id)
    notify_image_status_changed()
    return result


@app.post("/manager/api/images/{image_id}/disconnect")
def disconnect_image(image_id: str, body: SessionRequest) -> dict:
    validate_image_id(image_id)
    if image_id not in image_ids():
        raise HTTPException(404, "イメージが見つかりません。")
    release_connection(image_id, body.session_id)
    result = image_payload(image_id)
    notify_image_status_changed()
    return result


@app.post("/manager/api/images/{image_id}/start")
def start_image(image_id: str) -> dict:
    validate_image_id(image_id)
    if image_id not in image_ids():
        raise HTTPException(404, "イメージが見つかりません。")
    runtime = read_runtime(image_id)
    if is_running(runtime):
        return image_payload(image_id)
    port = free_port()
    LOGS_DIR.mkdir(exist_ok=True)
    work_dir = RUNTIME_DIR / f"{image_id}"
    work_dir.mkdir(exist_ok=True)
    with (LOGS_DIR / f"{image_id}.log").open("ab") as log_file:
        process = subprocess.Popen([str(START_SCRIPT), "--id", image_id, "--port", str(port)], cwd=work_dir, stdout=log_file, stderr=subprocess.STDOUT)
    write_runtime(image_id, {"pid": process.pid, "port": port, "started_at": datetime.now(timezone.utc).isoformat()})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not is_running(read_runtime(image_id)):
            runtime_path(image_id).unlink(missing_ok=True)
            raise HTTPException(500, "sandbox の起動に失敗しました。ログを確認してください。")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                result = image_payload(image_id)
                notify_image_status_changed()
                return result
        time.sleep(0.1)
    os.kill(process.pid, signal.SIGTERM)
    runtime_path(image_id).unlink(missing_ok=True)
    raise HTTPException(504, "OpenCode は10秒以内に待受を開始しませんでした。")


@app.post("/manager/api/images/{image_id}/stop")
def stop_image(image_id: str, body: SessionRequest | None = None) -> dict:
    validate_image_id(image_id)
    if image_id not in image_ids():
        raise HTTPException(404, "イメージが見つかりません。")
    session_id = validate_session_id(body.session_id) if body else None
    with connection_guard(image_id):
        current = read_connection_unlocked(image_id)
        if current and current["session_id"] != session_id:
            raise HTTPException(409, "別のセッションが接続中のため停止できません。")
        if current:
            connection_path(image_id).unlink(missing_ok=True)
        runtime = read_runtime(image_id)
        if runtime and is_running(runtime):
            os.kill(runtime["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 5
            while is_running(runtime) and time.monotonic() < deadline:
                time.sleep(0.1)
            if is_running(runtime):
                os.kill(runtime["pid"], signal.SIGKILL)
        runtime_path(image_id).unlink(missing_ok=True)
    result = image_payload(image_id)
    notify_image_status_changed()
    return result


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
async def opencode_http_proxy(path: str, request: Request):
    image_id = request.cookies.get("opencode_image")
    if not image_id:
        raise HTTPException(404, "OpenCodeのイメージが選択されていません。管理画面から起動してください。")
    return await proxy_http(request, image_id, path, session_id=request.cookies.get("opencode_session"))


@app.websocket("/{path:path}")
async def opencode_websocket_proxy(websocket: WebSocket, path: str):
    image_id = websocket.cookies.get("opencode_image")
    if not image_id:
        await websocket.close(code=4404, reason="OpenCode image not selected")
        return
    try:
        require_connection(image_id, websocket.cookies.get("opencode_session"))
        port = proxy_port(image_id)
        query = websocket.scope.get("query_string", b"").decode("latin-1")
        upstream_url = f"ws://127.0.0.1:{port}/{path}"
        if query:
            upstream_url += f"?{query}"
        upstream_origin = f"http://127.0.0.1:{port}"
        headers = [("Origin", upstream_origin)]
        auth = websocket.headers.get("authorization")
        if auth:
            headers.append(("Authorization", auth))
        async with websocket_connect(upstream_url, additional_headers=headers, subprotocols=websocket.scope.get("subprotocols") or [], open_timeout=10) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)

            async def browser_to_server():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def server_to_browser():
                async for message in upstream:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)

            tasks = [asyncio.create_task(browser_to_server()), asyncio.create_task(server_to_browser())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if not task.cancelled():
                    task.exception()
            try:
                await websocket.close()
            except RuntimeError:
                pass
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011, reason="OpenCode proxy failed")
        except RuntimeError:
            pass
