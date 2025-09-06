from __future__ import annotations

import json
import logging

from classpub_cli.logging import JsonLineFormatter


def test_json_line_formatter_outputs_expected_keys():
    fmt = JsonLineFormatter()
    logger = logging.getLogger("test")
    record = logger.makeRecord(
        name="test", level=logging.INFO, fn="x.py", lno=1, msg="hello", args=(), exc_info=None
    )
    s = fmt.format(record)
    obj = json.loads(s)
    assert set(["time", "level", "name", "message", "pid", "thread", "module", "pathname"]) <= set(obj.keys())

