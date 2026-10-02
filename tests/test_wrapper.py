import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qwen38_serving import core
from qwen38_serving.benchmark import stream_request
from qwen38_serving.cli import parser, settings_for


class Response(io.BytesIO):
    def __init__(self, data=b"", status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        self.profile = core.read_json(core.ROOT / "profiles/m5-max-128gb.json")
        self.manifest = core.load_manifest(core.ROOT / "manifests/model.json")
        self.settings = core.Settings(self.path / "data", self.path / "state", self.profile, copy.deepcopy(self.manifest), core.read_json(core.ROOT / "manifests/engine.json"))

    def entry(self, data, path="sample.bin"):
        return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def tiny_model(self):
        self.settings.model.mkdir(parents=True)
        data = b"model"
        (self.settings.model / "sample.bin").write_bytes(data)
        self.settings.model_manifest["files"] = [self.entry(data)]
        self.settings.model_manifest["total_bytes"] = len(data)

    def test_manifest_is_complete_and_canonical_table_is_pinned(self):
        manifest = self.manifest
        self.assertEqual(len(manifest["files"]), 113)
        self.assertEqual(sum(f["size"] for f in manifest["files"]), manifest["total_bytes"])
        table = next(f for f in manifest["files"] if f["path"] == "ngram_table.bin")
        self.assertEqual(table["size"], 32000153976)
        self.assertEqual(table["sha256"], "c8ab74bc343408cf3923d7d64b3698fbeb3e78c07ce7f85a650a8278731251d2")
        self.assertEqual(len([f for f in manifest["files"] if f["path"].endswith(".safetensors")]), 101)

    def test_plan_uses_no_network_and_creates_no_directory(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network called")), patch("subprocess.run", side_effect=AssertionError("Command called")):
            result = core.download_plan(self.settings)
            engine = core.install_engine(self.settings, plan=True)
        self.assertFalse(self.settings.data.exists())
        self.assertFalse(result["network_used"])
        self.assertFalse(engine["network_used"])
        self.assertIn(self.manifest["revision"], result["hf_command"])

    def test_git_blob_digest_and_symlink_rejection(self):
        path = self.path / "config.json"
        data = b'{}\n'
        path.write_bytes(data)
        entry = {"size": len(data), "git_blob_sha1": hashlib.sha1(b"blob 3\0" + data).hexdigest()}
        self.assertTrue(core.check_file(path, entry))
        link = self.path / "link.json"
        link.symlink_to(path)
        self.assertFalse(core.check_file(link, entry))

    def test_verify_detects_modified_same_length_file(self):
        self.tiny_model()
        core.verify(self.settings)
        core.require_verified(self.settings)
        (self.settings.model / "sample.bin").write_bytes(b"other")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            core.require_verified(self.settings)
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            core.verify(self.settings)

    def test_missing_ngram_blocks_verified_marker(self):
        self.tiny_model()
        self.settings.model_manifest["files"].append(self.entry(b"table", "ngram_table.bin"))
        with self.assertRaisesRegex(RuntimeError, "ngram_table.bin"):
            core.verify(self.settings)
        self.assertFalse((self.settings.model / ".qwen38-verified.json").exists())

    def test_resume_http_range(self):
        path = self.path / "file.bin"
        path.with_name("file.bin.part").write_bytes(b"abc")
        with patch("urllib.request.urlopen", return_value=Response(b"def", 206, {"Content-Range": "bytes 3-5/6"})) as network:
            core.fetch("https://example.com/file", path, self.entry(b"abcdef"))
        self.assertEqual(network.call_args.args[0].get_header("Range"), "bytes=3-")
        self.assertEqual(path.read_bytes(), b"abcdef")

    def test_range_ignored_restarts_file(self):
        path = self.path / "file.bin"
        path.with_name("file.bin.part").write_bytes(b"abc")
        with patch("urllib.request.urlopen", return_value=Response(b"abcdef")):
            core.fetch("https://example.com/file", path, self.entry(b"abcdef"))
        self.assertEqual(path.read_bytes(), b"abcdef")

    def test_bad_content_range_does_not_corrupt_partial(self):
        path = self.path / "file.bin"
        partial = path.with_name("file.bin.part")
        partial.write_bytes(b"abc")
        with patch("urllib.request.urlopen", return_value=Response(b"def", 206, {"Content-Range": "bytes 0-2/6"})):
            with self.assertRaisesRegex(RuntimeError, "Content-Range"):
                core.fetch("https://example.com/file", path, self.entry(b"abcdef"))
        self.assertEqual(partial.read_bytes(), b"abc")

    def test_bad_checksum_does_not_promote_to_model_file(self):
        path = self.path / "file.bin"
        with patch("urllib.request.urlopen", return_value=Response(b"wrong!")):
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                core.fetch("https://example.com/file", path, self.entry(b"abcdef"))
        self.assertFalse(path.exists())

    def test_cli_global_options_work_on_both_sides_of_command(self):
        for argv in [["--port", "11235", "status"], ["status", "--port", "11235"]]:
            settings = settings_for(parser().parse_args(argv))
            self.assertEqual(settings.profile["port"], 11235)

    def record(self, pid=123):
        core.write_json(self.settings.record, {"pid": pid, "argv": [str(self.settings.engine)], "port": 11234})

    def test_unrelated_pid_is_never_signaled(self):
        self.record()
        other = subprocess.CompletedProcess([], 0, stdout="S /usr/bin/other --port 11234", stderr="")
        with patch("subprocess.run", return_value=other), patch("os.kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "refusing"):
                core.stop(self.settings)
        kill.assert_not_called()

    def test_stop_wait_does_not_require_terminating_argv(self):
        self.record()
        own = subprocess.CompletedProcess([], 0, stdout=f"S {self.settings.engine} --port 11234", stderr="")
        exiting = subprocess.CompletedProcess([], 0, stdout="S", stderr="")
        gone = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with patch("subprocess.run", side_effect=[own, exiting, gone]), patch("os.kill") as kill, patch("time.sleep"):
            core.stop(self.settings)
        kill.assert_called_once()
        self.assertFalse(self.settings.record.exists())

    def test_pid_port_match_is_not_a_numeric_prefix_match(self):
        self.record()
        record = core.read_json(self.settings.record)
        record["port"] = 1123
        core.write_json(self.settings.record, record)
        other = subprocess.CompletedProcess([], 0, stdout=f"S {self.settings.engine} --port 11234", stderr="")
        with patch("subprocess.run", return_value=other), patch("os.kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "refusing"):
                core.stop(self.settings)
        kill.assert_not_called()

    def test_occupied_port_is_not_disturbed(self):
        with patch("platform.system", return_value="Darwin"), patch("platform.machine", return_value="arm64"), patch("socket.socket") as socket, patch("subprocess.Popen") as launch:
            socket.return_value.__enter__.return_value.connect_ex.return_value = 0
            with self.assertRaisesRegex(RuntimeError, "Port occupied"):
                core.start(self.settings)
        launch.assert_not_called()

    def test_start_has_no_output_cap_and_cold_cache_is_explicit(self):
        self.tiny_model()
        core.verify(self.settings)
        self.settings.engine.parent.mkdir(parents=True)
        self.settings.engine.touch()
        child = MagicMock(pid=424242)
        child.poll.return_value = None
        with patch("platform.system", return_value="Darwin"), patch("platform.machine", return_value="arm64"), patch("socket.socket") as socket, patch("subprocess.Popen", return_value=child) as launch, patch("urllib.request.urlopen", return_value=Response()):
            socket.return_value.__enter__.return_value.connect_ex.return_value = 1
            record = core.start(self.settings, cold_cache=True)
        argv = launch.call_args.args[0]
        self.assertEqual(argv[argv.index("--prefix-cache-entries") + 1], "0")
        self.assertEqual(argv[argv.index("--mtp-history-window") + 1], "8192")
        self.assertNotIn("--max-tokens", argv)
        self.assertEqual(record["engine_env"]["MLX_SERVE_MTP_FORCE_DEPTH"], "3")

    def test_download_refuses_to_mutate_loaded_model(self):
        with patch.object(core, "managed_pid", return_value=123), patch("subprocess.run") as command:
            with self.assertRaisesRegex(RuntimeError, "Stop"):
                core.download(self.settings, "hf")
        command.assert_not_called()

    def test_hf_download_is_revision_pinned_and_uses_dedicated_cache(self):
        with patch.object(core, "managed_pid", return_value=None), patch("shutil.which", return_value="/bin/hf"), patch("subprocess.run") as command, patch.object(core, "verify", return_value={"verified": True}):
            result = core.download(self.settings, "hf")
        argv = command.call_args.args[0]
        environment = command.call_args.kwargs["env"]
        self.assertIn(self.manifest["revision"], argv)
        self.assertEqual(environment["HF_HUB_CACHE"], str(self.settings.data / "hf-cache/hub"))
        self.assertEqual(environment["HF_XET_CACHE"], str(self.settings.data / "hf-cache/xet"))
        self.assertTrue(result["verified"])

    def test_stream_delivery_excludes_first_frame_share(self):
        events = [
            {"choices": [{"delta": {"content": "abcd"}}]},
            {"choices": [{"delta": {"content": "efgh"}}]},
            {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 8}},
        ]
        data = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events) + b"data: [DONE]\n\n"
        metrics = {"counters": {}, "histograms": {}}
        with patch("urllib.request.urlopen", return_value=Response(data)), patch("time.perf_counter", side_effect=[0, 1, 2, 3, 4]), patch("qwen38_serving.benchmark.api", return_value=metrics):
            result = stream_request(self.settings, {"messages": []})
        self.assertEqual(result["ttft_s"], 1)
        self.assertEqual(result["client_prefill_tok_s"], 100)
        self.assertEqual(result["client_decode_tok_s"], 4)
        self.assertEqual(result["text"], "abcdefgh")

    def test_tool_protocol_roundtrip_uses_matching_call_id(self):
        call = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_test", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"杭州"}'}}]}
        def reply(text):
            return {"choices": [{"message": {"role": "assistant", "content": text}}]}
        responses = [{"data": [{"id": "test-model"}]}, reply("任务取消"), {"choices": [{"message": call}]}, reply("23 摄氏度"), reply("493")]
        with patch.object(core, "api", side_effect=responses) as api:
            result = core.check(self.settings)
        self.assertTrue(result["passed"])
        body = api.call_args_list[3].args[2]
        self.assertEqual(body["messages"][-1]["tool_call_id"], "call_test")
        self.assertTrue(api.call_args_list[-1].args[2]["enable_thinking"])


if __name__ == "__main__":
    unittest.main()
