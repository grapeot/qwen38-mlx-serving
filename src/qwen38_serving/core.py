from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_file(path: Path, entry: dict) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != entry["size"]:
        return False
    if "sha256" in entry:
        return sha256(path) == entry["sha256"]
    digest = hashlib.sha1(b"blob " + str(entry["size"]).encode() + b"\0")
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest() == entry["git_blob_sha1"]


def load_manifest(path: Path) -> dict:
    document = read_json(path)
    for entry in document["files"]:
        name = Path(entry["path"])
        if name.is_absolute() or ".." in name.parts:
            raise ValueError(f"Unsafe manifest path: {name}")
    return document


@dataclasses.dataclass
class Settings:
    data: Path
    state: Path
    profile: dict
    model_manifest: dict
    engine_manifest: dict
    model_override: Path | None = None
    engine_override: Path | None = None

    @property
    def model(self) -> Path:
        return self.model_override or self.data / "models" / self.model_manifest["directory"]

    @property
    def engine(self) -> Path:
        manifest = self.engine_manifest
        return self.engine_override or self.data / "engines" / manifest["version"] / manifest["archive_directory"] / manifest["binary"]

    @property
    def base(self) -> str:
        return f"http://{self.profile['host']}:{self.profile['port']}"

    @property
    def record(self) -> Path:
        return self.state / "server.json"


def file_stamps(settings: Settings) -> dict:
    result = {}
    for entry in settings.model_manifest["files"]:
        path = settings.model / entry["path"]
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Missing regular model file: {path}")
        stat = path.stat()
        result[entry["path"]] = [stat.st_size, stat.st_mtime_ns]
    return result


def manifest_digest(settings: Settings) -> str:
    return hashlib.sha256(json.dumps(settings.model_manifest, sort_keys=True).encode()).hexdigest()


def verify(settings: Settings) -> dict:
    failures = []
    for entry in settings.model_manifest["files"]:
        path = settings.model / entry["path"]
        if not check_file(path, entry):
            failures.append(entry["path"])
    if failures:
        raise RuntimeError("Model verification failed: " + ", ".join(failures))
    result = {"manifest_sha256": manifest_digest(settings), "files": file_stamps(settings), "verified_at": time.time()}
    write_json(settings.model / ".qwen38-verified.json", result)
    return {"verified": True, "files": len(result["files"]), "bytes": settings.model_manifest["total_bytes"]}


def require_verified(settings: Settings) -> None:
    marker = settings.model / ".qwen38-verified.json"
    if not marker.is_file():
        raise RuntimeError("Model has not been verified; run verify first")
    previous = read_json(marker)
    if previous.get("manifest_sha256") != manifest_digest(settings) or previous.get("files") != file_stamps(settings):
        raise RuntimeError("Model or manifest changed since verification; run verify again")


def fetch(url: str, destination: Path, entry: dict) -> None:
    if check_file(destination, entry):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    for attempt in range(3):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == entry["size"] and check_file(partial, entry):
            partial.replace(destination)
            return
        if offset >= entry["size"]:
            raise RuntimeError(f"Invalid partial file; inspect before retry: {partial}")
        headers = {"User-Agent": "qwen38-mlx-serving/0.1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                status = response.status
                if status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {offset}-"):
                        raise RuntimeError(f"Incorrect HTTP Content-Range: {content_range}")
                elif status != 200:
                    raise RuntimeError(f"Unexpected HTTP status: {status}")
                mode = "ab" if offset and status == 206 else "wb"
                with partial.open(mode) as output:
                    while block := response.read(8 * 1024 * 1024):
                        output.write(block)
            if not check_file(partial, entry):
                raise RuntimeError(f"Downloaded checksum/size mismatch: {partial}")
            partial.replace(destination)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def download_plan(settings: Settings) -> dict:
    manifest = settings.model_manifest
    command = ["hf", "download", manifest["repo"], "--revision", manifest["revision"], "--local-dir", str(settings.model)]
    return {"repo": manifest["repo"], "revision": manifest["revision"], "files": len(manifest["files"]), "bytes": manifest["total_bytes"], "destination": str(settings.model), "hf_command": command, "network_used": False}


def download(settings: Settings, transport: str) -> dict:
    if managed_pid(settings):
        raise RuntimeError("Stop the managed server before modifying its model files")
    manifest = settings.model_manifest
    settings.model.mkdir(parents=True, exist_ok=True)
    if transport == "hf":
        executable = shutil.which("hf")
        neighbor = Path(sys.executable).parent / "hf"
        if executable is None and neighbor.is_file():
            executable = str(neighbor)
        if executable is None:
            raise RuntimeError("hf CLI unavailable; install the download extra or use --transport http")
        command = download_plan(settings)["hf_command"]
        command[0] = executable
        env = os.environ.copy()
        env.update(HF_HOME=str(settings.data / "hf-cache"), HF_HUB_CACHE=str(settings.data / "hf-cache/hub"), HF_XET_CACHE=str(settings.data / "hf-cache/xet"), HF_XET_HIGH_PERFORMANCE="1")
        subprocess.run(command, env=env, check=True)
    else:
        def retrieve(entry):
            url = f"https://huggingface.co/{manifest['repo']}/resolve/{manifest['revision']}/{entry['path']}"
            fetch(url, settings.model / entry["path"], entry)
            print("Verified", entry["path"], flush=True)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(retrieve, manifest["files"]))
    return verify(settings)


def install_engine(settings: Settings, plan: bool = False) -> dict:
    manifest = settings.engine_manifest
    if plan:
        return {**manifest, "destination": str(settings.engine), "network_used": False}
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Engine installation requires macOS arm64")
    if managed_pid(settings):
        raise RuntimeError("Stop the managed server before updating its engine")
    archive = settings.data / "downloads" / f"mlx-serve-{manifest['version']}.tar.gz"
    fetch(manifest["url"], archive, manifest)
    directory = settings.data / "engines" / manifest["version"]
    directory.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(directory, filter="data")
    binary = directory / manifest["archive_directory"] / manifest["binary"]
    if not binary.is_file():
        raise RuntimeError("Engine archive did not contain the expected executable")
    return {"installed": str(binary), "archive_sha256": manifest["sha256"]}


def managed_pid(settings: Settings) -> int | None:
    if not settings.record.exists():
        return None
    record = read_json(settings.record)
    pid = int(record["pid"])
    response = subprocess.run(["ps", "-p", str(pid), "-o", "stat=,args="], capture_output=True, text=True)
    fields = response.stdout.split(maxsplit=1)
    if response.returncode or not fields or fields[0].startswith("Z"):
        return None
    expected = record["argv"][0]
    port_argument = rf"(?:^|\s)--port\s+{record['port']}(?:\s|$)"
    if not fields[-1].startswith(expected + " ") or not re.search(port_argument, fields[-1]):
        raise RuntimeError(f"PID {pid} no longer belongs to this wrapper; refusing to signal it")
    return pid


@contextlib.contextmanager
def lifecycle_lock(settings: Settings):
    settings.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (settings.state / "lifecycle.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def api(base: str, endpoint: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(base + endpoint, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(2048).decode(errors="replace")
        raise RuntimeError(f"HTTP {error.code} {endpoint}: {detail}") from error


def start(settings: Settings, cold_cache: bool = False) -> dict:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Serving requires macOS arm64")
    with lifecycle_lock(settings):
        if managed_pid(settings):
            raise RuntimeError("Managed server already running")
        with socket.socket() as connection:
            connection.settimeout(1)
            if connection.connect_ex((settings.profile["host"], settings.profile["port"])) == 0:
                raise RuntimeError("Port occupied; existing service was left untouched")
        require_verified(settings)
        if not settings.engine.is_file():
            raise RuntimeError("Engine missing; run install-engine first")
        profile = settings.profile
        command = [str(settings.engine), "--model", str(settings.model), "--serve", "--host", profile["host"], "--port", str(profile["port"]), "--ctx-size", str(profile["context_window"]), "--no-vision", "--metrics", "--max-resident-mem", profile["max_resident_mem"], "--prefix-cache-mem", profile["prefix_cache_mem"], "--prefix-cache-entries", "0" if cold_cache else str(profile["prefix_cache_entries"]), "--max-concurrent", "1", *profile["args"]]
        env = os.environ.copy()
        env.update(profile["env"])
        logfile = settings.state / "server.log"
        with logfile.open("a") as log:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        record = {"pid": child.pid, "port": profile["port"], "base": settings.base, "argv": command, "engine_env": profile["env"], "cold_cache": cold_cache, "profile": profile, "revision": settings.model_manifest["revision"], "model": str(settings.model), "started_at": time.time()}
        write_json(settings.record, record)
        for _ in range(180):
            if child.poll() is not None:
                raise RuntimeError(f"Server exited; inspect {logfile}")
            try:
                with urllib.request.urlopen(settings.base + "/health", timeout=2) as health:
                    if health.status == 200:
                        return record
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(1)
        raise RuntimeError(f"Readiness timed out; process retained for inspection: {logfile}")


def stop(settings: Settings) -> dict:
    with lifecycle_lock(settings):
        pid = managed_pid(settings)
        if pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(80):
                state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
                if state.returncode or not state.stdout.strip() or state.stdout.strip().startswith("Z"):
                    break
                time.sleep(.5)
            else:
                raise RuntimeError("Server did not exit after SIGTERM; no additional signal sent")
        settings.record.unlink(missing_ok=True)
        return {"stopped": True, "pid": pid}


def doctor(settings: Settings) -> dict:
    disk = settings.data
    while not disk.exists():
        disk = disk.parent
    result = {"python_version": platform.python_version(), "platform": platform.system(), "architecture": platform.machine(), "engine_exists": settings.engine.is_file(), "model_directory": str(settings.model), "data_directory": str(settings.data), "runtime_directory": str(settings.state), "download_bytes": settings.model_manifest["total_bytes"], "free_disk_bytes": shutil.disk_usage(disk).free, "profile_minimum_memory_gib": settings.profile["minimum_memory_gib"], "network_used": False}
    if platform.system() == "Darwin":
        for key in ["hw.memsize", "iogpu.wired_limit_mb"]:
            response = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True)
            result[key] = response.stdout.strip() if response.returncode == 0 else "unavailable"
    return result


def check(settings: Settings) -> dict:
    model = api(settings.base, "/v1/models")["data"][0]["id"]
    def chat(messages, **extra):
        body = {"model": model, "messages": messages, "temperature": 0, "stream": False, "max_tokens": 512, "enable_thinking": False}
        body.update(extra)
        response = api(settings.base, "/v1/chat/completions", body)
        return response["choices"][0]["message"]
    chinese = chat([{"role": "user", "content": "用中文简要解释 asyncio 的任务取消机制。"}])["content"]
    if not any("\u4e00" <= letter <= "\u9fff" for letter in chinese):
        raise RuntimeError("Chinese generation check failed")
    tools = [{"type": "function", "function": {"name": "get_weather", "description": "Read weather for a city", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"], "additionalProperties": False}}}]
    messages = [{"role": "user", "content": "请调用 get_weather 查询杭州天气，然后告诉我温度。"}]
    call = chat(messages, tools=tools, tool_choice={"type": "function", "function": {"name": "get_weather"}})
    calls = call.get("tool_calls", [])
    if len(calls) != 1 or calls[0]["function"]["name"] != "get_weather":
        raise RuntimeError("Tool-call schema check failed")
    city = json.loads(calls[0]["function"]["arguments"]).get("city")
    if city not in ["杭州", "Hangzhou"]:
        raise RuntimeError(f"Tool argument check failed: {city}")
    messages.extend([call, {"role": "tool", "tool_call_id": calls[0]["id"], "content": '{"temperature_c":23,"source":"synthetic protocol test"}'}])
    answer = chat(messages, tools=tools)["content"]
    if "23" not in answer:
        raise RuntimeError("Tool-result roundtrip failed")
    arithmetic = chat([{"role": "user", "content": "计算 19×23+7×8，只输出最终整数。"}], enable_thinking=True, reasoning_budget_tokens=128)["content"].strip()
    if arithmetic != "493":
        raise RuntimeError(f"Thinking-on arithmetic check failed: {arithmetic}")
    result = {"passed": True, "model": model, "chinese": chinese, "tool_roundtrip": True, "arithmetic": arithmetic, "synthetic_tool_data": True}
    write_json(settings.state / "checks" / f"{time.time_ns()}.json", result)
    return result
