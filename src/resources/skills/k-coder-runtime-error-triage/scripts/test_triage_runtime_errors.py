import argparse
import contextlib
import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import triage_runtime_errors as triage


def failure(output="", command="cargo test 2>&1 | Select-Object -Last 40", **fields):
    return {
        "level": "error",
        "event": "tool_failed",
        "timestampMs": 1000,
        "fields": {
            "output": output,
            "arguments": {"command": command},
            **fields,
        },
    }


class ClassificationTests(unittest.TestCase):
    def test_real_test_failures_take_precedence_over_noise_and_commands(self):
        for output in (
            "Finished test profile\ntest result: FAILED. 971 passed; 16 failed",
            "thread 'fixture' panicked at src/lib.rs:10:1",
            "AssertionError: expected matching state",
            "assertion `left == right` failed\nNativeCommandError",
            "FAILED tests/test_fixture.py",
            "error: test failed, to rerun pass --lib",
        ):
            with self.subTest(output=output):
                rule, _ = triage.classify_record_with_observations(failure(output))
                self.assertEqual(rule["id"], "R1")
                self.assertEqual(rule["verdict"], "review")

    def test_pipeline_progress_is_not_automatic_success(self):
        for command in ("cargo check", "cargo check 2>&1 | Select-Object -Last 40"):
            rule, _ = triage.classify_record_with_observations(
                failure("Finished dev profile\nNativeCommandError", command)
            )
            self.assertEqual(rule["id"], "N14")
            self.assertEqual(rule["verdict"], "review")

    def test_command_keywords_do_not_classify_the_output(self):
        record = failure(
            "Finished dev profile",
            "rg 'plugin is not enabled|test result: FAILED|workspace path changed' .",
            tool="run_command",
        )
        rule, _ = triage.classify_record_with_observations(record)
        self.assertEqual(rule["id"], "N14")

    def test_empty_nonzero_output_is_unknown_not_syntax_noise(self):
        rule, _ = triage.classify_record_with_observations(
            failure("command produced no output and exited with code 101.", "cargo test")
        )
        self.assertEqual(rule["verdict"], "review")

    def test_plugin_rule_requires_both_error_markers(self):
        rule, _ = triage.classify_record_with_observations(
            failure("plugin alpha is not enabled", "plugin call")
        )
        self.assertEqual(rule["id"], "N2")
        rule, _ = triage.classify_record_with_observations(
            failure("plugin crashed", "plugin call")
        )
        self.assertEqual(rule["verdict"], "review")

    def test_historical_signals_require_source_and_version_review(self):
        record = {
            "event": "mobile.gateway.restore_failed",
            "fields": {"message": "Cannot assign requested address"},
        }
        rule, _ = triage.classify_record_with_observations(record)
        self.assertEqual(rule["verdict"], "review")
        rule, observations = triage.classify_record_with_observations(
            failure("old output \ufffd\ufffd\ufffd", "git status")
        )
        self.assertEqual(rule["verdict"], "review")
        self.assertEqual(observations[0]["id"], "B2")
        self.assertEqual(observations[0]["verdict"], "review")
        _, observations = triage.classify_record_with_observations(
            failure("clean output", "rg '\ufffd\ufffd\ufffd' .")
        )
        self.assertEqual(observations, [])

    def test_python_shift_or_literal_is_not_a_heredoc(self):
        for command in ("python -c 'print(1 << 2)'", "rg '<<PY' ."):
            rule, _ = triage.classify_record_with_observations(failure("failed", command))
            self.assertEqual(rule["verdict"], "review")
        rule, _ = triage.classify_record_with_observations(failure(
            "PowerShell 不支持 Bash 的 python - <<'PY' heredoc。命令尚未执行。",
            "python - <<'PY'",
        ))
        self.assertEqual(rule["id"], "N15")

    def test_historical_no_matches_requires_result_and_version_review(self):
        rule, _ = triage.classify_record_with_observations(failure(
            "no matches (exit code 1)", "rg AbsentMarker .",
        ))
        self.assertEqual(rule["id"], "N16")
        self.assertEqual(rule["verdict"], "review")
        for output in (
            "no matches (exit code 1)\ntest result: FAILED",
            "no matches (exit code 1)\nregex parse error",
        ):
            with self.subTest(output=output):
                rule, _ = triage.classify_record_with_observations(failure(output))
                self.assertNotEqual(rule["id"], "N16")
        rule, _ = triage.classify_record_with_observations(failure(
            "Finished dev profile", "rg 'no matches (exit code 1)' .",
        ))
        self.assertEqual(rule["id"], "N14")

    def test_apply_patch_loop_requires_session_level_root_cause_review(self):
        record = {
            "level": "error",
            "event": "turn_failed",
            "fields": {
                "message": (
                    "apply_patch_loop: apply_patch failed for e2e/workbench.spec.ts; "
                    "the last patch conflict matched 0 locations"
                ),
                "threadId": "fixture-thread",
            },
        }
        rule, _ = triage.classify_record_with_observations(record)
        self.assertEqual(rule["id"], "N5")
        self.assertEqual(rule["verdict"], "review")

    def test_successful_recovery_is_not_classified_as_apply_patch_loop(self):
        rule, _ = triage.classify_record_with_observations(
            failure("patch conflicts with the workspace: hunk matched 0 locations")
        )
        self.assertEqual(rule["id"], "N4")
        self.assertEqual(rule["verdict"], "not-bug")

    def test_recovery_hint_cannot_mask_real_test_failure(self):
        output = (
            "PowerShell 将原生 stderr 呈现为错误记录。保留真实退出码。\n"
            "NativeCommandError\ntest result: FAILED. 3 passed; 1 failed"
        )
        rule, _ = triage.classify_record_with_observations(failure(output))
        self.assertEqual(rule["id"], "R1")
        self.assertEqual(rule["verdict"], "review")

    def test_null_fields_and_arguments_do_not_crash(self):
        for record in (
            {"event": "tool_failed", "fields": None},
            {"event": "tool_failed", "fields": {"arguments": None}},
            {"event": "tool_failed", "fields": {"arguments": "legacy text"}},
            {"event": None, "fields": []},
        ):
            with self.subTest(record=record):
                triage.classify_record_with_observations(record)


class SessionTests(unittest.TestCase):
    def test_null_metadata_preserves_failed_fact(self):
        for metadata in (None, [], "legacy", {}):
            summary = triage.print_session_event(
                1000, "tool_result",
                {"name": "run_command", "result": {
                    "success": False, "output": None, "metadata": metadata,
                }},
            )
            self.assertIn("success=False exit=None", summary)
            self.assertNotIn("success=True", summary)

    def test_session_preserves_no_matches_success_and_original_exit(self):
        summary = triage.print_session_event(
            1000, "tool_result",
            {"name": "run_command", "result": {
                "success": True, "output": "no matches (exit code 1)",
                "metadata": {"exitCode": 1, "resultKind": "no_matches"},
            }},
        )
        self.assertIn("success=True exit=1", summary)

    def test_null_optional_payloads_do_not_crash(self):
        for event, data in (
            ("tool_result", {"result": None}),
            ("user_message", {"message": None}),
            ("assistant_message", {"message": {"content": None}}),
            ("provider_call_usage", {"usage": None, "details": None}),
            ("assistant_tool_calls", {"calls": None}),
            ("assistant_tool_calls", {"calls": [None, {"arguments": None}]}),
            ("turn_failed", None),
        ):
            with self.subTest(event=event):
                triage.print_session_event(1000, event, data)

    def test_null_and_nonstring_message_text_preserves_valid_content(self):
        content = [
            None,
            {"type": "text", "text": None},
            {"type": "text", "text": 7},
            {"type": "text", "text": {"legacy": True}},
            {"type": "text"},
            {"type": "text", "text": "valid message"},
        ]
        for event in ("user_message", "assistant_message"):
            with self.subTest(event=event):
                summary = triage.print_session_event(
                    1000, event, {"message": {"content": content}},
                )
                self.assertIn("valid message", summary)
                self.assertNotIn("None", summary)
                self.assertNotIn("legacy", summary)

    def test_cli_session_accepts_legacy_null_metadata(self):
        self._assert_cli_session_handles_legacy_records(None)
        self._assert_cli_session_handles_legacy_records(5)

    def _assert_cli_session_handles_legacy_records(self, minutes):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "fixture.jsonl").write_text(
                'null\nnot json\n' + json.dumps({
                    "type": "tool_result", "createdAtMs": 1000,
                    "data": {"name": "run_command", "result": {
                        "success": False, "output": "test result: FAILED",
                        "metadata": None,
                    }},
                }) + '\n', encoding="utf-8",
            )
            output = io.StringIO()
            with patch.object(triage, "SESSION_DIR", directory), contextlib.redirect_stdout(output):
                code = triage.cmd_session(argparse.Namespace(
                    thread="fixture", minutes=minutes, since_ms=None,
                ))
            self.assertEqual(code, 0)
            self.assertIn("success=False exit=None", output.getvalue())
            self.assertIn("test result: FAILED", output.getvalue())

    def test_cli_classify_keeps_review_observations_out_of_bug_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "runtime.jsonl")
            records = [failure("test result: FAILED"), failure("old \ufffd\ufffd\ufffd")]
            path.write_text(
                'null\n[]\n' + '\n'.join(json.dumps(r) for r in records) + '\n',
                encoding="utf-8",
            )
            output = io.StringIO()
            with patch.object(triage, "LOG_PATH", str(path)), contextlib.redirect_stdout(output):
                code = triage.cmd_classify(argparse.Namespace(all=True, minutes=1440, verbose=False))
            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertIn("0 类 / 0 条", text)
            self.assertIn("[R1]", text)
            self.assertIn("[B2]", text)
            self.assertIn("待人工判定：2 条", text)
            self.assertNotIn("没有需要修复的产品缺陷", text)
            self.assertNotIn("伴随缺陷", text)

    def test_cli_classify_separates_unmatched_errors_by_event_and_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "runtime.jsonl")
            records = [
                {
                    "level": "error",
                    "event": "tool_failed",
                    "timestampMs": 1000,
                    "fields": {
                        "tool": "browser_navigate",
                        "output": "Browser process exited with status 21",
                    },
                },
                {
                    "level": "error",
                    "event": "tool_failed",
                    "timestampMs": 2000,
                    "fields": {
                        "tool": "update_plan",
                        "output": "plan may contain at most one active step",
                    },
                },
            ]
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with patch.object(triage, "LOG_PATH", str(path)), contextlib.redirect_stdout(output):
                code = triage.cmd_classify(
                    argparse.Namespace(all=True, minutes=1440, verbose=False)
                )

            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertIn("待人工判定：2 类 / 2 条", text)
            self.assertIn("tool_failed / browser_navigate", text)
            self.assertIn("tool_failed / update_plan", text)


class RuntimeRootTests(unittest.TestCase):
    def test_apply_paths_resolves_root_and_log_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "runtime-data")
            Path(root, "logs").mkdir(parents=True)
            Path(root, "sessions").mkdir()
            log = root / "logs" / "runtime.jsonl"
            log.write_text("", encoding="utf-8")

            triage.apply_paths(argparse.Namespace(runtime_root=str(root), log_path=None))
            self.assertEqual(triage.LOG_PATH, str(log))
            self.assertEqual(triage.SESSION_DIR, str(root / "sessions"))
            self.assertEqual(triage.RUNTIME_ROOT, str(root))

            other = Path(directory, "elsewhere.jsonl")
            other.write_text("", encoding="utf-8")
            triage.apply_paths(argparse.Namespace(runtime_root=None, log_path=str(other)))
            self.assertEqual(triage.LOG_PATH, str(other))
            self.assertIsNone(triage.SESSION_DIR)
            self.assertEqual(triage.RUNTIME_ROOT, directory)

            standard = Path(directory, "std", "logs", "runtime.jsonl")
            standard.parent.mkdir(parents=True)
            standard.write_text("", encoding="utf-8")
            triage.apply_paths(argparse.Namespace(runtime_root=None, log_path=str(standard)))
            self.assertEqual(triage.SESSION_DIR, str(Path(directory, "std", "sessions")))
            self.assertEqual(triage.RUNTIME_ROOT, str(Path(directory, "std")))

            triage.LOG_PATH = triage.DEFAULT_LOG_PATH
            triage.SESSION_DIR = triage.DEFAULT_SESSION_DIR
            triage.RUNTIME_ROOT = triage.DEFAULT_RUNTIME_ROOT

    def test_apply_paths_rejects_missing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory, "absent"))
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    triage.apply_paths(argparse.Namespace(runtime_root=missing, log_path=None))
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(triage.LOG_PATH, triage.DEFAULT_LOG_PATH)

    def test_apply_paths_rejects_missing_log_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "runtime-data")
            root.mkdir()
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    triage.apply_paths(argparse.Namespace(
                        runtime_root=str(root), log_path=None,
                    ))
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(triage.LOG_PATH, triage.DEFAULT_LOG_PATH)
            self.assertEqual(triage.SESSION_DIR, triage.DEFAULT_SESSION_DIR)
            self.assertEqual(triage.RUNTIME_ROOT, triage.DEFAULT_RUNTIME_ROOT)

    def test_session_path_requires_root_when_layout_is_nonstandard(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory, "runtime.jsonl")
            log.write_text("", encoding="utf-8")
            triage.apply_paths(argparse.Namespace(runtime_root=None, log_path=str(log)))
            self.assertIsNone(triage.SESSION_DIR)
            self.assertIsNone(triage.session_path("t1"))

            triage.LOG_PATH = triage.DEFAULT_LOG_PATH
            triage.SESSION_DIR = triage.DEFAULT_SESSION_DIR
            triage.RUNTIME_ROOT = triage.DEFAULT_RUNTIME_ROOT

    def test_cli_errors_tolerates_bom_and_reports_bad_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            now_ms = int(datetime.datetime.now().timestamp() * 1000)
            root = Path(directory, "runtime-data")
            (root / "logs").mkdir(parents=True)
            # utf-8-sig：模拟 PowerShell Set-Content -Encoding utf8 写出的带 BOM 文件
            (root / "logs" / "runtime.jsonl").write_text(
                json.dumps({
                    "level": "error", "event": "tool_failed", "timestampMs": now_ms,
                    "fields": {"threadId": "t1", "output": "boom"},
                }) + "\ntruncated-line\n",
                encoding="utf-8-sig",
            )
            output = io.StringIO()
            with patch.object(triage, "LOG_PATH", str(root / "logs" / "runtime.jsonl")), \
                 patch.object(triage, "SESSION_DIR", str(root / "sessions")), \
                 contextlib.redirect_stdout(output):
                code = triage.cmd_errors(argparse.Namespace(minutes=30, verbose=False))
            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertIn("thread t1", text)
            self.assertIn("1 行无法解析", text)

    def test_cli_errors_honours_runtime_root(self):
        with tempfile.TemporaryDirectory() as directory:
            now_ms = int(datetime.datetime.now().timestamp() * 1000)
            root = Path(directory, "runtime-data")
            sessions = root / "sessions"
            sessions.mkdir(parents=True)
            (root / "logs").mkdir()
            (root / "logs" / "runtime.jsonl").write_text(
                json.dumps({
                    "level": "error", "event": "tool_failed", "timestampMs": now_ms,
                    "fields": {"threadId": "t1", "output": "boom"},
                }) + "\n",
                encoding="utf-8",
            )
            Path(sessions, "t1.jsonl").write_text(
                json.dumps({"type": "user_message", "createdAtMs": now_ms - 60_000,
                            "data": {"message": {"content": []}}}) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with patch.object(triage, "LOG_PATH", str(root / "logs" / "runtime.jsonl")), \
                 patch.object(triage, "SESSION_DIR", str(sessions)), \
                 contextlib.redirect_stdout(output):
                code = triage.cmd_errors(argparse.Namespace(minutes=30, verbose=False))
            self.assertEqual(code, 0)
            self.assertIn("thread t1", output.getvalue())
            self.assertIn("会话最近活跃", output.getvalue())


if __name__ == "__main__":
    unittest.main()
