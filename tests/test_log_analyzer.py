# -*- coding: utf-8 -*-
"""log_analyzer 的单元测试：python -m unittest discover -s tests"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import log_analyzer as lg

SAMPLE = [
    '1.1.1.1 - - [12/Nov/2026:09:12:01 +0800] "GET /index.html HTTP/1.1" 200 1000 "-" "UA" 0.012',
    '1.1.1.1 - - [12/Nov/2026:09:12:05 +0800] "GET /api/a HTTP/1.1" 200 500 "-" "UA" 0.050',
    '2.2.2.2 - - [12/Nov/2026:10:00:00 +0800] "GET /api/b?x=1 HTTP/1.1" 404 120 "-" "UA" 0.010',
    '3.3.3.3 - - [12/Nov/2026:11:30:00 +0800] "GET /boom HTTP/1.1" 500 0 "-" "UA" 1.500',
    '坏行',
]


class TestParse(unittest.TestCase):
    def test_full_line(self):
        entry = lg.parse_line(SAMPLE[0])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.ip, "1.1.1.1")
        self.assertEqual(entry.method, "GET")
        self.assertEqual(entry.path, "/index.html")
        self.assertEqual(entry.status, 200)
        self.assertEqual(entry.hour, 9)
        self.assertAlmostEqual(entry.request_time, 0.012)

    def test_query_string_stripped(self):
        entry = lg.parse_line(SAMPLE[2])
        self.assertEqual(entry.path, "/api/b")

    def test_without_request_time(self):
        line = '1.1.1.1 - - [12/Nov/2026:09:12:01 +0800] "GET /x HTTP/1.1" 200 10 "-" "UA"'
        entry = lg.parse_line(line)
        self.assertIsNone(entry.request_time)

    def test_malformed(self):
        self.assertIsNone(lg.parse_line("坏行"))

    def test_timestamp_bad(self):
        with self.assertRaises(ValueError):
            lg.parse_timestamp("nonsense")


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.stats = lg.analyze(SAMPLE)

    def test_counts(self):
        self.assertEqual(self.stats.total, 4)
        self.assertEqual(self.stats.malformed, 1)
        self.assertEqual(len(self.stats.ips), 3)
        self.assertEqual(self.stats.statuses[200], 2)
        self.assertEqual(self.stats.statuses[500], 1)

    def test_hours(self):
        self.assertEqual(self.stats.hours[9], 2)
        self.assertEqual(self.stats.hours[11], 1)

    def test_slow_detection(self):
        self.assertEqual(len(self.stats.slow), 1)
        self.assertEqual(self.stats.slow[0].path, "/boom")

    def test_size_total(self):
        self.assertEqual(self.stats.bytes_total, 1620)


class TestStats(unittest.TestCase):
    def test_percentile(self):
        self.assertAlmostEqual(lg.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertAlmostEqual(lg.percentile([5], 0.95), 5.0)

    def test_percentile_empty(self):
        with self.assertRaises(ValueError):
            lg.percentile([], 0.5)

    def test_human_size(self):
        self.assertEqual(lg.human_size(512), "512 B")
        self.assertEqual(lg.human_size(2048), "2.0 KB")


class TestReport(unittest.TestCase):
    def test_report_sections(self):
        report = lg.build_report(lg.analyze(SAMPLE))
        for heading in ("## 概况", "## 状态码分布", "## Top", "## 响应时间"):
            self.assertIn(heading, report)
        self.assertIn("50.00%", report)  # 404 + 500 各 1 条 / 4 条有效请求

    def test_empty_report(self):
        self.assertIn("没有解析到有效日志行", lg.build_report(lg.analyze([])))


class TestCli(unittest.TestCase):
    def test_writes_file(self):
        logfile = Path("_cli_test.log")
        out = Path("_cli_test.md")
        try:
            logfile.write_text("\n".join(SAMPLE), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = lg.main([str(logfile), "--output", str(out), "--slow-ms", "100"])
            self.assertEqual(code, 0)
            self.assertIn("## 概况", out.read_text(encoding="utf-8"))
        finally:
            logfile.unlink(missing_ok=True)
            out.unlink(missing_ok=True)

    def test_missing_file_returns_2(self):
        code = lg.main(["不存在的日志.log"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
