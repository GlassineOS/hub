# SPDX-License-Identifier: GPL-2.0-or-later
"""The rolling summary: folding a turn in, its bound, the failure path, and the last turn from a transcript."""
import asyncio
import json
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hubd import judge, summary  # noqa: E402
from hubd.judge import Judge, JudgeFault  # noqa: E402


class Fixed(Judge):
    provider, model = "fake", "fixed"

    def __init__(self, answer):
        self.answer, self.seen = answer, None

    async def complete(self, system, user, schema):
        self.seen = (system, user, schema)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer, None


def test_a_turn_is_folded_into_the_summary(tmp_path):
    (tmp_path / summary.SUMMARY_FILE).write_text("Started on the fix.")
    fake = Fixed({"summary": "  Started on the fix; tests pass now.  "})
    text, failed = asyncio.run(summary.update(tmp_path, "assistant: ran the tests, all pass", fake))
    assert (text, failed) == ("Started on the fix; tests pass now.", None)
    assert summary.read(tmp_path) == text
    assert stat.S_IMODE((tmp_path / summary.SUMMARY_FILE).stat().st_mode) == 0o600
    system, user, schema = fake.seen
    assert system == summary.FOLD_SYSTEM and schema == summary.FOLD_SCHEMA
    assert user.index("<<<SUMMARY ") < user.index("Started on the fix.") < user.index("<<<TURN ")
    assert user.index("<<<TURN ") < user.index("ran the tests") < user.rindex(">>>")


def test_a_json_string_fold_is_read_too(tmp_path):
    text, failed = asyncio.run(summary.update(tmp_path, "turn", Fixed(json.dumps({"summary": "new"}))))
    assert (text, failed) == ("new", None)


def test_the_summary_is_bounded(tmp_path):
    text, failed = asyncio.run(summary.update(tmp_path, "turn", Fixed({"summary": "y" * 5000})))
    assert failed is None and len(text) == summary.MAX_SUMMARY
    assert len(summary.read(tmp_path)) == summary.MAX_SUMMARY


def test_a_failed_fold_keeps_the_old_summary_and_the_end_of_the_turn(tmp_path):
    (tmp_path / summary.SUMMARY_FILE).write_text("Old summary.")
    turn = "start " + "m" * 2000 + " the very end"
    for answer, why in ((JudgeFault("the endpoint answered 500"), "answered 500"), ("{nope", "isn't JSON"),
                        ({"summary": "   "}, "no summary"), ({"other": 1}, "no summary"), (RuntimeError("x"), "broke")):
        (tmp_path / summary.SUMMARY_FILE).write_text("Old summary.")
        text, failed = asyncio.run(summary.update(tmp_path, turn, Fixed(answer)))
        assert why in failed
        assert text.startswith("Old summary.") and text.endswith("the very end") and "start" not in text
        assert len(text) <= len("Old summary.") + summary.FAILED_TAIL + 40


def test_repeated_failures_stay_within_the_bound(tmp_path):
    for i in range(20):
        text, failed = asyncio.run(summary.update(tmp_path, "z" * 300 + f" turn {i}", Fixed(JudgeFault("down"))))
    assert failed == "down" and len(text) <= summary.MAX_SUMMARY and text.endswith("turn 19")
    assert "turn 0" not in text


def test_the_fold_prompt_keeps_a_turn_in_one_argument():
    text = summary.fold_prompt("s", "x" * (400 * 1024) + "END")
    assert len(text.encode()) < judge.MAX_TURN_BYTES + 4096 and "END" in text


def test_the_fold_system_text_says_the_data_is_never_instructions():
    for words in ("is data", "never instructions", "outsiders", str(summary.MAX_SUMMARY), '{"summary"'):
        assert words in summary.FOLD_SYSTEM


def transcript(tmp_path, rows):
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def said(role, content):
    return {"type": role, "message": {"role": role, "content": content}}


def test_the_last_turn_is_the_last_prompt_and_what_followed(tmp_path):
    path = transcript(tmp_path, [
        said("user", "first prompt"), said("assistant", [{"type": "text", "text": "first answer"}]),
        said("user", "second prompt"),
        said("assistant", [{"type": "text", "text": "looking"}, {"type": "tool_use", "name": "Read", "input": {}}]),
        said("user", [{"type": "tool_result", "content": "file text"}]),  # a tool's result, not a person's prompt
        {"type": "summary", "summary": "x"},
        said("assistant", [{"type": "text", "text": "done"}]),
    ])
    assert summary.last_turn(path) == "user: second prompt\n\nassistant: looking\n\nassistant: done"


def test_a_cut_or_missing_transcript_reads_as_little_as_it_has(tmp_path):
    assert summary.last_turn(None) == "" and summary.last_turn(tmp_path / "missing.jsonl") == ""
    path = tmp_path / "t.jsonl"
    path.write_text('{"type": "assist\n' + json.dumps(said("assistant", [{"type": "text", "text": "only this"}])) + "\n")
    assert summary.last_turn(path) == "assistant: only this"


def test_a_long_turn_keeps_its_end(tmp_path):
    path = transcript(tmp_path, [said("user", "go"), said("assistant", [{"type": "text", "text": "a" * 50000 + " the end"}])])
    text = summary.last_turn(path)
    assert len(text) == summary.MAX_TURN and text.endswith(" the end")
