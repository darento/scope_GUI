"""The SC-007 log checker used in the hardware check."""

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


def test_counts_commands_since_a_time_and_ignores_replies(tmp_path):
    (tmp_path / "scope_gui.log").write_text(LOG, encoding="utf-8")
    counts = check_log.sent_commands([tmp_path / "scope_gui.log"], "2026-10-27 09:30")
    assert counts == {"C1:VDIV?": 2, "C1:WF? ALL": 1, "*IDN?": 1}


def test_passes_only_when_everything_is_allowlisted(tmp_path, capsys):
    (tmp_path / "scope_gui.log").write_text(LOG, encoding="utf-8")
    args = ["--log-dir", str(tmp_path)]
    assert check_log.main([*args, "--since", "2026-10-27 09:30"]) == 0
    assert "PASS: all 4 commands" in capsys.readouterr().out
    assert check_log.main(args) == 1  # C9:EVIL before 09:30
    assert "C9:EVIL   <-- NOT ALLOWLISTED" in capsys.readouterr().out


def test_no_commands_is_a_failure(tmp_path):
    assert check_log.main(["--log-dir", str(tmp_path)]) == 1
