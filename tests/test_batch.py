"""Tests for batch_execute functionality."""

from __future__ import annotations

from cup.actions.executor import ActionResult

# ---------------------------------------------------------------------------
# Batch execution logic (mirrors Session.batch_execute without needing an adapter)
# ---------------------------------------------------------------------------


def _batch_execute(actions, execute_fn, press_keys_fn):
    """Simulate Session.batch_execute with injected action functions."""
    results = []
    for spec in actions:
        action = spec.get("action", "")
        if action == "press_keys":
            keys = spec.get("keys", "")
            if not keys:
                results.append(
                    ActionResult(
                        success=False,
                        message="",
                        error="press_keys action requires 'keys' parameter",
                    )
                )
                break
            result = press_keys_fn(keys)
        else:
            element_id = spec.get("element_id", "")
            if not element_id:
                results.append(
                    ActionResult(
                        success=False,
                        message="",
                        error=f"Element action '{action}' requires 'element_id' parameter",
                    )
                )
                break
            params = {k: v for k, v in spec.items() if k not in ("element_id", "action")}
            result = execute_fn(element_id, action, **params)
        results.append(result)
        if not result.success:
            break
    return results


_ok = lambda msg="OK": ActionResult(success=True, message=msg)
_fail = lambda err="Failed": ActionResult(success=False, message="", error=err)


class TestBatchExecute:
    def test_all_succeed(self):
        results = _batch_execute(
            [
                {"element_id": "e1", "action": "click"},
                {"action": "press_keys", "keys": "enter"},
                {"element_id": "e2", "action": "type", "value": "hello"},
            ],
            execute_fn=lambda eid, action, **p: _ok(f"{action} {eid}"),
            press_keys_fn=lambda keys: _ok(f"Pressed {keys}"),
        )
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_stops_on_first_failure(self):
        call_count = [0]

        def execute(eid, action, **params):
            call_count[0] += 1
            if eid == "e2":
                return _fail("Not found")
            return _ok()

        results = _batch_execute(
            [
                {"element_id": "e1", "action": "click"},
                {"element_id": "e2", "action": "click"},  # fails
                {"element_id": "e3", "action": "click"},  # never reached
            ],
            execute_fn=execute,
            press_keys_fn=lambda keys: _ok(),
        )
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False
        assert call_count[0] == 2

    def test_empty_actions_list(self):
        results = _batch_execute(
            [],
            execute_fn=lambda *a, **k: _ok(),
            press_keys_fn=lambda *a: _ok(),
        )
        assert results == []

    def test_press_keys_without_keys_param(self):
        results = _batch_execute(
            [{"action": "press_keys"}],
            execute_fn=lambda *a, **k: _ok(),
            press_keys_fn=lambda *a: _ok(),
        )
        assert len(results) == 1
        assert results[0].success is False
        assert "keys" in results[0].error.lower()

    def test_element_action_without_element_id(self):
        results = _batch_execute(
            [{"action": "click"}],
            execute_fn=lambda *a, **k: _ok(),
            press_keys_fn=lambda *a: _ok(),
        )
        assert len(results) == 1
        assert results[0].success is False
        assert "element_id" in results[0].error.lower()

    def test_params_forwarded(self):
        received = {}

        def execute(eid, action, **params):
            received.update(params)
            return _ok()

        _batch_execute(
            [{"element_id": "e1", "action": "type", "value": "hello"}],
            execute_fn=execute,
            press_keys_fn=lambda *a: _ok(),
        )
        assert received == {"value": "hello"}

    def test_mixed_element_and_press_keys(self):
        log = []

        def execute(eid, action, **params):
            log.append(("execute", eid, action))
            return _ok()

        def press_keys(keys):
            log.append(("press_keys", keys))
            return _ok()

        results = _batch_execute(
            [
                {"element_id": "e1", "action": "click"},
                {"action": "press_keys", "keys": "tab"},
                {"element_id": "e2", "action": "type", "value": "world"},
            ],
            execute_fn=execute,
            press_keys_fn=press_keys,
        )
        assert len(results) == 3
        assert log == [
            ("execute", "e1", "click"),
            ("press_keys", "tab"),
            ("execute", "e2", "type"),
        ]
