"""Tests for async (non-blocking) delegation dispatch (#9).

When the parent agent carries an `_async_delegate_sink` callable AND it is a
top-level agent (depth 0), `delegate_task` must dispatch the child on a
background thread and return immediately with {status:"dispatched", task_id},
calling the sink with the result payload when the child finishes. CLI/cron
(no sink) and nested orchestrators (depth>0) keep the synchronous path.
"""

import json
import threading
import time
import unittest
from unittest.mock import patch

from tools.delegate_tool import delegate_task, _get_async_delegation_enabled
from tests.tools.test_delegate import _make_mock_parent


class TestAsyncDelegation(unittest.TestCase):
    def _parent_with_sink(self, depth=0):
        parent = _make_mock_parent(depth=depth)
        sink_calls = []
        done = threading.Event()

        def _sink(payload):
            sink_calls.append(payload)
            done.set()

        parent._async_delegate_sink = _sink
        return parent, sink_calls, done

    @patch("tools.delegate_tool._run_single_child")
    def test_dispatch_returns_immediately_and_sink_fires(self, mock_run):
        # The child run blocks on a gate the test controls, so dispatch must
        # return WITHOUT the child having finished — no wall-clock flakiness.
        release = threading.Event()

        def _gated(*a, **k):
            release.wait(timeout=3.0)
            return {
                "task_index": 0,
                "status": "completed",
                "summary": "async done",
                "api_calls": 1,
                "duration_seconds": 0.0,
            }

        mock_run.side_effect = _gated
        parent, sink_calls, done = self._parent_with_sink()

        result = json.loads(delegate_task(goal="do async thing", parent_agent=parent))

        # Dispatch returned while the child is still gated (not finished).
        self.assertFalse(done.is_set(), "dispatch blocked on the child run")
        self.assertEqual(result["status"], "dispatched")
        self.assertTrue(result["task_id"].startswith("dt_"))
        self.assertEqual(len(result["dispatched"]), 1)
        self.assertEqual(result["dispatched"][0]["goal"], "do async thing")
        self.assertNotIn("results", result)

        # Release the gate; the sink fires once the background child completes.
        release.set()
        self.assertTrue(done.wait(timeout=3.0), "sink was never called")
        self.assertEqual(len(sink_calls), 1)
        payload = sink_calls[0]
        self.assertEqual(payload["task_id"], result["task_id"])
        self.assertEqual(payload["results"][0]["summary"], "async done")
        # goal folded into the result entry for the completion ping
        self.assertEqual(payload["results"][0]["goal"], "do async thing")

    @patch("tools.delegate_tool._run_single_child")
    def test_no_sink_runs_synchronously(self, mock_run):
        mock_run.return_value = {
            "task_index": 0,
            "status": "completed",
            "summary": "sync done",
            "api_calls": 1,
            "duration_seconds": 0.0,
        }
        parent = _make_mock_parent()  # no _async_delegate_sink
        # MagicMock would auto-create the attr; ensure it's a non-callable.
        parent._async_delegate_sink = None
        result = json.loads(delegate_task(goal="sync thing", parent_agent=parent))
        self.assertIn("results", result)
        self.assertNotIn("status", result)
        self.assertEqual(result["results"][0]["summary"], "sync done")

    @patch("tools.delegate_tool._get_max_spawn_depth", return_value=3)
    @patch("tools.delegate_tool._run_single_child")
    def test_nested_depth_ignores_sink(self, mock_run, _depth):
        # A depth>0 agent (a subagent itself) must synthesise inline even if a
        # sink leaked onto it — async is top-level only.
        mock_run.return_value = {
            "task_index": 0,
            "status": "completed",
            "summary": "nested sync",
            "api_calls": 1,
            "duration_seconds": 0.0,
        }
        parent, sink_calls, _done = self._parent_with_sink(depth=1)
        result = json.loads(delegate_task(goal="nested", parent_agent=parent))
        self.assertIn("results", result)
        self.assertEqual(result["results"][0]["summary"], "nested sync")
        self.assertEqual(sink_calls, [])

    @patch("tools.delegate_tool._run_single_child")
    def test_kill_switch_forces_sync(self, mock_run):
        mock_run.return_value = {
            "task_index": 0,
            "status": "completed",
            "summary": "forced sync",
            "api_calls": 1,
            "duration_seconds": 0.0,
        }
        parent, sink_calls, _done = self._parent_with_sink()
        with patch(
            "tools.delegate_tool._get_async_delegation_enabled", return_value=False
        ):
            result = json.loads(delegate_task(goal="x", parent_agent=parent))
        self.assertIn("results", result)
        self.assertEqual(sink_calls, [])

    @patch("tools.delegate_tool._run_single_child")
    def test_sink_exception_does_not_crash_dispatch(self, mock_run):
        mock_run.return_value = {
            "task_index": 0,
            "status": "completed",
            "summary": "ok",
            "api_calls": 1,
            "duration_seconds": 0.0,
        }
        parent = _make_mock_parent()
        boom = threading.Event()

        def _bad_sink(payload):
            boom.set()
            raise RuntimeError("sink blew up")

        parent._async_delegate_sink = _bad_sink
        result = json.loads(delegate_task(goal="x", parent_agent=parent))
        self.assertEqual(result["status"], "dispatched")
        # The thread invoked the sink (and swallowed its exception).
        self.assertTrue(boom.wait(timeout=3.0))

    def test_async_enabled_default_and_env(self):
        self.assertTrue(_get_async_delegation_enabled({}))
        self.assertFalse(_get_async_delegation_enabled({"async_enabled": False}))
        self.assertTrue(_get_async_delegation_enabled({"async_enabled": "yes"}))


if __name__ == "__main__":
    unittest.main()
