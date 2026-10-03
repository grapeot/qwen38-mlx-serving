from __future__ import annotations

import hashlib
import json
import random
import statistics
import time
import urllib.request
from pathlib import Path

from .core import Settings, api, managed_pid, read_json, require_verified, write_json

CONTEXTS = [2048, 4096, 8192, 16384, 32768, 65536, 131072]


def prompt_for(tokenizer, target: int, seed: int) -> str:
    rng = random.Random(seed)
    prefix = "Unique benchmark record: " + " ".join(str(rng.randrange(10000, 99999)) for _ in range(160))
    if len(tokenizer.encode(prefix).ids) < 256:
        raise RuntimeError("Benchmark random prefix must contain at least 256 tokens")
    instruction = "\nWrite a detailed Python asynchronous bounded LRU cache with expiry, cancellation handling, type annotations, concurrency safety, and tests. Explain each design decision. Continue for at least 1000 tokens. Do not repeat the filler.\n"
    unit = "Reference record: an application stores documents, schedules tasks, and tracks request latency. Its cache maps identifiers to values with expiry timestamps.\n"
    budget = max(0, target - len(tokenizer.encode(prefix + instruction).ids) - 40)
    tokens = tokenizer.encode(unit).ids
    filler = tokenizer.decode((tokens * (budget // len(tokens) + 1))[:budget])
    return prefix + filler + instruction


def stream_request(settings: Settings, body: dict) -> dict:
    before = api(settings.base, "/metrics.json")
    request = urllib.request.Request(settings.base + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    events, usage = [], {}
    text, thinking = "", ""
    first = last = None
    first_characters = 0
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=900) as response:
        for line in response:
            if not line.startswith(b"data: "):
                continue
            payload = line[6:].strip()
            if payload == b"[DONE]":
                break
            event = json.loads(payload)
            now = time.perf_counter()
            events.append(event)
            if event.get("error"):
                raise RuntimeError(f"Streaming error: {event['error']}")
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                content = delta.get("content") or ""
                reason = delta.get("reasoning_content") or ""
                if content or reason:
                    if first is None:
                        first = now
                        first_characters = len(content)
                    last = now
                text += content
                thinking += reason
    elapsed = time.perf_counter() - start
    after = api(settings.base, "/metrics.json")
    if first is None or last is None or last <= first or not text:
        raise RuntimeError("Missing content or measurable decode span")
    output_tokens = usage.get("completion_tokens", 0)
    result = {"request": body, "events": events, "usage": usage, "text": text, "thinking": thinking, "ttft_s": first - start, "elapsed_s": elapsed, "client_prefill_tok_s": usage.get("prompt_tokens", 0) / (first - start), "client_decode_tok_s": output_tokens * (1 - first_characters / len(text)) / (last - first), "metrics_before": before, "metrics_after": after}
    for stage, counter, histogram in [("prefill", "prefill_tokens_total", "prefill_time_seconds"), ("decode", "generation_tokens_total", "decode_time_seconds")]:
        try:
            seconds = after["histograms"][histogram]["sum"] - before["histograms"][histogram]["sum"]
            tokens = after["counters"][counter] - before["counters"][counter]
            result[f"server_{stage}_tok_s"] = tokens / seconds if seconds else None
        except KeyError:
            result[f"server_{stage}_tok_s"] = None
    return result


def benchmark(settings: Settings, contexts: list[int], repeats: int, output_tokens: int, temperature: float) -> dict:
    try:
        from tokenizers import Tokenizer
    except ImportError as error:
        raise RuntimeError("Install the benchmark extra for tokenizers") from error
    if repeats < 1 or output_tokens < 2 or not contexts:
        raise ValueError("Positive repetitions, contexts and at least two output tokens required")
    if any(c < 512 or c + output_tokens + 128 > settings.profile["context_window"] for c in contexts):
        raise ValueError("Requested benchmark exceeds configured input+output context")
    if not managed_pid(settings):
        raise RuntimeError("Benchmark requires this wrapper's managed server")
    record = read_json(settings.record)
    if not record.get("cold_cache"):
        raise RuntimeError("Restart with start --cold-cache before benchmark")
    if record.get("model") != str(settings.model):
        raise RuntimeError("Managed server uses a different model directory")
    if record.get("base") != settings.base or record.get("profile") != settings.profile or record.get("revision") != settings.model_manifest["revision"]:
        raise RuntimeError("Benchmark settings differ from the running server; use its profile and port")
    require_verified(settings)
    tokenizer = Tokenizer.from_file(str(settings.model / "tokenizer.json"))
    model = api(settings.base, "/v1/models")["data"][0]["id"]
    directory = settings.state / "benchmarks" / str(time.time_ns())
    directory.mkdir(parents=True)
    runs, last_context = [], {}
    for repeat in range(repeats):
        for context in contexts:
            time.sleep(max(0, 60 - (time.monotonic() - last_context.get(context, -1e9))))
            last_context[context] = time.monotonic()
            seed = 1000 + repeat * 10 + context
            prompt = prompt_for(tokenizer, context, seed)
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": output_tokens, "stream": True, "stream_options": {"include_usage": True}, "temperature": temperature, "top_p": .95, "top_k": 20, "seed": seed, "enable_thinking": False, "chat_template_kwargs": {"enable_thinking": False}, "ignore_eos": True, "enable_pld": False}
            result = stream_request(settings, body)
            result.update(target_tokens=context, repeat=repeat + 1, wire_sha256=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest())
            raw = directory / f"{context}-r{repeat + 1}.json"
            write_json(raw, result)
            if result["usage"].get("completion_tokens") != output_tokens or result["usage"].get("prompt_tokens_details", {}).get("cached_tokens") != 0 or result["thinking"]:
                raise RuntimeError(f"Protocol failure; raw response retained in {raw}")
            if len(tokenizer.encode(result["text"]).ids) < .9 * output_tokens:
                raise RuntimeError(f"Too few visible tokens; inspect {raw}")
            runs.append(result)
            print("Measured", context, repeat + 1, result["client_prefill_tok_s"], result["client_decode_tok_s"], flush=True)
            time.sleep(15)
    rows = []
    for context in contexts:
        group = [r for r in runs if r["target_tokens"] == context]
        row = {"target_tokens": context, "actual_prompt_tokens": [r["usage"]["prompt_tokens"] for r in group], "runs": len(group)}
        for metric in ["client_prefill_tok_s", "client_decode_tok_s", "server_prefill_tok_s", "server_decode_tok_s"]:
            values = [r[metric] for r in group if r.get(metric) is not None]
            row[metric] = {"median": statistics.median(values), "min": min(values), "max": max(values)} if values else None
        rows.append(row)
    summary = {"schema_version": 1, "tool": "qwen38-mlx-serving-local-synthetic", "model": model, "repo": settings.model_manifest["repo"], "revision": settings.model_manifest["revision"], "profile": record["profile"], "rows": rows, "protocol": {"temperature": temperature, "top_p": .95, "top_k": 20, "output_tokens": output_tokens, "thinking": False, "prefix_cache_entries": 0, "prompt": "random-prefix-LRU-implementation-v1", "comparable_to_llmprobe": False}, "artifact_directory": str(directory)}
    write_json(directory / "summary.json", summary)
    return summary


def plot(input_path: Path, output_path: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    summary = read_json(input_path)
    rows = summary["rows"]
    figure, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for axis, metric, title in zip(axes, ["client_prefill_tok_s", "client_decode_tok_s"], ["Prefill: input / TTFT", "Decode: client delivery"]):
        values = [row[metric] for row in rows]
        median = [v["median"] for v in values]
        errors = [[v["median"] - v["min"] for v in values], [v["max"] - v["median"] for v in values]]
        axis.errorbar(range(len(rows)), median, yerr=errors, marker="o", capsize=3)
        axis.set_xticks(range(len(rows)), [f"{row['target_tokens'] / 1024:g}K\n{row['actual_prompt_tokens'][0]} actual" for row in rows], fontsize=8)
        axis.set_title(title)
        axis.set_ylabel("tokens / second")
        axis.set_ylim(bottom=0)
        axis.grid(alpha=.2)
    protocol = summary["protocol"]
    figure.suptitle(f"{summary['model']} | {summary['revision'][:12]}\nT={protocol['temperature']}, output={protocol['output_tokens']}, cold cache | {protocol.get('prompt', summary['tool']).split(' corpus')[0]}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)
    return {"plot": str(output_path)}
