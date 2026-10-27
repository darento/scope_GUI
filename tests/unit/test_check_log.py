"""The SC-007 / SC-004 log checker used in the hardware check."""

import check_log

LOG = """\
2026-10-27 09:29:59,001 DEBUG   [scope-io] scope_gui.driver: query C9:EVIL
2026-10-27 09:30:00,001 INFO    [MainThread] scope_gui: scope_gui starting
2026-10-27 09:30:01,002 DEBUG   [scope-io] scope_gui.driver: query C1:VDIV?
2026-10-27 09:30:01,003 DEBUG   [scope-io] scope_gui.driver: reply C1:VDIV 1.00E+00 V
2026-10-27 09:30:01,004 DEBUG   [io] scope_gui.driver: query C1:WF? ALL (binary, timeout 20000 ms)
2026-10-27 09:30:02,005 DEBUG   [scope-io] scope_gui.driver: query *IDN? (recover)
2026-10-27 09:30:03,006 DEBUG   [scope-io] scope_gui.driver: query C1:VDIV?
"""

SYNC_LOG = """\
2026-10-27 09:30:01,002 DEBUG   [scope-io] scope_gui.driver: query TRMD?
2026-10-27 09:30:01,003 DEBUG   [scope-io] scope_gui.driver: write TRMD STOP
2026-10-27 09:30:01,004 DEBUG   [scope-io] scope_gui.driver: write ARM
2026-10-27 09:30:01,005 DEBUG   [scope-io] scope_gui.driver: write FRTR
2026-10-27 09:30:01,006 DEBUG   [scope-io] scope_gui.driver: write ARM
2026-10-27 09:30:01,007 DEBUG   [scope-io] scope_gui.driver: write TRMD AUTO
"""


def run(tmp_path, capsys, text, *extra):
    (tmp_path / "scope_gui.log").write_text(text, encoding="utf-8")
    code = check_log.main(["--log-dir", str(tmp_path), *extra])
    return code, capsys.readouterr().out


def test_counts_commands_since_a_time_and_ignores_replies(tmp_path):
    (tmp_path / "scope_gui.log").write_text(LOG, encoding="utf-8")
    queries, writes = check_log.sent_commands([tmp_path / "scope_gui.log"], "2026-10-27 09:30")
    assert queries == {"C1:VDIV?": 2, "C1:WF? ALL": 1, "*IDN?": 1}
    assert writes == {}


def test_counts_queries_and_control_writes_separately(tmp_path):
    (tmp_path / "scope_gui.log").write_text(SYNC_LOG, encoding="utf-8")
    queries, writes = check_log.sent_commands([tmp_path / "scope_gui.log"])
    assert queries == {"TRMD?": 1}
    assert writes == {"TRMD STOP": 1, "ARM": 2, "FRTR": 1, "TRMD AUTO": 1}


def test_passes_only_when_everything_is_allowlisted(tmp_path, capsys):
    (tmp_path / "scope_gui.log").write_text(LOG, encoding="utf-8")
    args = ["--log-dir", str(tmp_path)]
    assert check_log.main([*args, "--since", "2026-10-27 09:30"]) == 0
    assert "PASS: all 4 commands" in capsys.readouterr().out
    assert check_log.main(args) == 1  # C9:EVIL before 09:30
    assert "C9:EVIL   <-- NOT ALLOWLISTED" in capsys.readouterr().out


def test_read_only_session_reports_zero_control_writes(tmp_path, capsys):
    code, out = run(tmp_path, capsys, LOG, "--since", "2026-10-27 09:30")
    assert code == 0
    assert "PASS: all 4 commands (3 different) are allowlisted; 0 acquisition-control writes" in out
    assert "Acquisition-control" not in out.split("PASS")[0]


def test_control_writes_are_listed_in_their_own_block_after_the_queries(tmp_path, capsys):
    code, out = run(tmp_path, capsys, SYNC_LOG)
    assert code == 0
    assert out.index("TRMD?") < out.index("Acquisition-control writes") < out.index("FRTR")
    assert "2  ARM" in out
    assert "PASS: all 6 commands (5 different) are allowlisted; 5 acquisition-control writes" in out


def test_a_write_outside_the_control_allowlist_fails(tmp_path, capsys):
    text = SYNC_LOG + "2026-10-27 09:30:02,000 DEBUG   [scope-io] scope_gui.driver: write TDIV 1\n"
    code, out = run(tmp_path, capsys, text)
    assert code == 1
    assert "TDIV 1   <-- NOT ALLOWLISTED" in out
    assert "FAIL" in out


def test_a_read_only_query_sent_as_a_write_fails(tmp_path, capsys):
    text = "2026-10-27 09:30:02,000 DEBUG   [scope-io] scope_gui.driver: write C1:VDIV?\n"
    code, out = run(tmp_path, capsys, text)
    assert code == 1
    assert "C1:VDIV?   <-- NOT ALLOWLISTED" in out


def test_a_control_command_sent_as_a_query_fails(tmp_path, capsys):
    text = "2026-10-27 09:30:02,000 DEBUG   [scope-io] scope_gui.driver: query ARM\n"
    code, out = run(tmp_path, capsys, text)
    assert code == 1
    assert "ARM   <-- NOT ALLOWLISTED" in out


def test_no_commands_is_a_failure(tmp_path):
    assert check_log.main(["--log-dir", str(tmp_path)]) == 1
