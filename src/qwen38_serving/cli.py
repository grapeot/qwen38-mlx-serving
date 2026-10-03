import argparse
import json
import os
import subprocess
from pathlib import Path

from . import core


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="qwen38")
    def common(target):
        for option in ["data-dir", "state-dir", "profile", "engine", "model-dir"]:
            target.add_argument("--" + option, default=argparse.SUPPRESS)
        target.add_argument("--port", type=int, default=argparse.SUPPRESS)
    common(root)
    subcommands = root.add_subparsers(dest="action", required=True)
    for name in ["doctor", "install-engine", "download", "verify", "start", "stop", "status", "check", "benchmark", "plot"]:
        child = subcommands.add_parser(name)
        common(child)
        if name in ["install-engine", "download"]:
            child.add_argument("--plan", action="store_true")
        if name == "download":
            child.add_argument("--transport", choices=["hf", "http", "aria2"], default="hf")
        if name == "start":
            child.add_argument("--cold-cache", action="store_true")
        if name == "benchmark":
            child.add_argument("--contexts", default="2048,4096,8192,16384,32768,65536,131072")
            child.add_argument("--repeats", type=int, default=3)
            child.add_argument("--output-tokens", type=int, default=192)
            child.add_argument("--temperature", type=float, default=1)
        if name == "plot":
            child.add_argument("--input", required=True, type=Path)
            child.add_argument("--output", required=True, type=Path)
    return root


def settings_for(args) -> core.Settings:
    home = Path.home()
    data = Path(getattr(args, "data_dir", os.environ.get("QWEN38_DATA_DIR", home / ".local/share/qwen38-serving"))).expanduser().resolve()
    state = Path(getattr(args, "state_dir", os.environ.get("QWEN38_STATE_DIR", home / ".local/state/qwen38-serving"))).expanduser().resolve()
    profile = core.read_json(Path(getattr(args, "profile", core.ROOT / "profiles/m5-max-128gb.json")))
    if hasattr(args, "port"):
        profile["port"] = args.port
    if not 1 <= profile["port"] <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if profile["host"] != "127.0.0.1":
        raise ValueError("This profile supports loopback serving only")
    engine = getattr(args, "engine", os.environ.get("QWEN38_ENGINE"))
    model = getattr(args, "model_dir", None)
    return core.Settings(data, state, profile, core.load_manifest(core.ROOT / "manifests/model.json"), core.read_json(core.ROOT / "manifests/engine.json"), Path(model).expanduser().resolve() if model else None, Path(engine).expanduser().resolve() if engine else None)


def run(args) -> dict:
    settings = settings_for(args)
    if args.action == "doctor":
        return core.doctor(settings)
    if args.action == "install-engine":
        return core.install_engine(settings, args.plan)
    if args.action == "download":
        return core.download_plan(settings, args.transport) if args.plan else core.download(settings, args.transport)
    if args.action == "verify":
        return core.verify(settings)
    if args.action == "start":
        return core.start(settings, args.cold_cache)
    if args.action == "stop":
        return core.stop(settings)
    if args.action == "status":
        return {"pid": core.managed_pid(settings), "record": core.read_json(settings.record) if settings.record.exists() else None, "configured_endpoint": settings.base + "/v1"}
    if args.action == "check":
        return core.check(settings)
    from . import benchmark
    if args.action == "benchmark":
        return benchmark.benchmark(settings, [int(value) for value in args.contexts.split(",")], args.repeats, args.output_tokens, args.temperature)
    return benchmark.plot(args.input, args.output)


def main():
    args = parser().parse_args()
    try:
        result = run(args)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"{type(error).__name__}: {error}") from error
    print(json.dumps(result, ensure_ascii=False, indent=2))
