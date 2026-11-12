#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nginx 访问日志分析器。

把一份 access.log 变成一份可以直接贴进周报的 Markdown 报表：
请求量、独立 IP、状态码分布、Top 路径、错误率、慢请求和响应时间分位。

输入是 nginx 的 combined 格式，末尾可选带 $request_time：
    127.0.0.1 - - [12/Nov/2026:10:00:01 +0800] "GET /index.html HTTP/1.1" 200 1043 "-" "curl/8.0" 0.012

用法：
    python log_analyzer.py data/sample.log
    python log_analyzer.py data/sample.log --top 5 --slow-ms 500 --output report.md

依赖：仅标准库。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

LINE_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<request>[^"]*)"\s+(?P<status>\d{3})\s+(?P<size>\d+|-)'
    r'(?:\s+"(?P<referer>[^"]*)"\s+"(?P<agent>[^"]*)")?'
    r'(?:\s+(?P<rt>\d+(?:\.\d+)?))?'
)

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


@dataclass(frozen=True)
class Entry:
    ip: str
    hour: int
    method: str
    path: str
    status: int
    size: int
    request_time: float | None


@dataclass
class Stats:
    total: int = 0
    malformed: int = 0
    ips: Counter = field(default_factory=Counter)
    paths: Counter = field(default_factory=Counter)
    statuses: Counter = field(default_factory=Counter)
    methods: Counter = field(default_factory=Counter)
    hours: Counter = field(default_factory=Counter)
    request_times: list[float] = field(default_factory=list)
    slow: list[Entry] = field(default_factory=list)
    bytes_total: int = 0


def parse_timestamp(text: str) -> int:
    """'12/Nov/2026:10:00:01 +0800' -> 小时（0-23），只取小时做分布统计。"""
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError(f"时间格式不认识：{text!r}")
    try:
        hour = int(parts[1])
    except ValueError:
        raise ValueError(f"时间格式不认识：{text!r}") from None
    if not 0 <= hour <= 23:
        raise ValueError(f"小时越界：{text!r}")
    return hour


def parse_line(line: str) -> Entry | None:
    match = LINE_RE.match(line.strip())
    if not match:
        return None

    request = match.group("request").split()
    if len(request) >= 2:
        method, path = request[0], request[1]
    elif len(request) == 1:
        method, path = "-", request[0]
    else:
        method, path = "-", "-"

    path = path.split("?", 1)[0] or "-"
    size_text = match.group("size")
    rt_text = match.group("rt")

    try:
        return Entry(
            ip=match.group("ip"),
            hour=parse_timestamp(match.group("ts")),
            method=method,
            path=path,
            status=int(match.group("status")),
            size=0 if size_text == "-" else int(size_text),
            request_time=None if rt_text is None else float(rt_text),
        )
    except ValueError:
        return None


def analyze(lines: Iterable[str], slow_ms: float = 800.0) -> Stats:
    stats = Stats()
    threshold = slow_ms / 1000.0
    for line in lines:
        entry = parse_line(line)
        if entry is None:
            if line.strip():
                stats.malformed += 1
            continue
        stats.total += 1
        stats.ips[entry.ip] += 1
        stats.paths[entry.path] += 1
        stats.statuses[entry.status] += 1
        stats.methods[entry.method] += 1
        stats.hours[entry.hour] += 1
        stats.bytes_total += entry.size
        if entry.request_time is not None:
            stats.request_times.append(entry.request_time)
            if entry.request_time >= threshold:
                stats.slow.append(entry)
    return stats


def percentile(values: Sequence[float], q: float) -> float:
    """线性插值分位数，q 取 0~1。"""
    if not values:
        raise ValueError("没有耗时数据")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} GB"


def build_report(stats: Stats, top: int = 10, slow_ms: float = 800.0) -> str:
    lines: list[str] = []
    lines.append("# Nginx 访问日志分析报告")
    lines.append("")
    if stats.total == 0:
        lines.append("没有解析到有效日志行。")
        return "\n".join(lines)

    errors = sum(c for s, c in stats.statuses.items() if s >= 400)
    server_errors = sum(c for s, c in stats.statuses.items() if s >= 500)
    error_rate = errors / stats.total * 100

    lines.append("## 概况")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 总请求数 | {stats.total:,} |")
    lines.append(f"| 独立 IP | {len(stats.ips):,} |")
    lines.append(f"| 错误率（4xx + 5xx） | {error_rate:.2f}% |")
    lines.append(f"| 5xx 请求数 | {server_errors:,} |")
    lines.append(f"| 出流量 | {human_size(stats.bytes_total)} |")
    if stats.malformed:
        lines.append(f"| 无法解析的行 | {stats.malformed:,} |")
    lines.append("")

    lines.append("## 状态码分布")
    lines.append("")
    lines.append("| 状态码 | 次数 | 占比 |")
    lines.append("|---|---|---|")
    for status, count in stats.statuses.most_common():
        lines.append(f"| {status} | {count:,} | {count / stats.total * 100:.1f}% |")
    lines.append("")

    lines.append(f"## Top {top} 路径")
    lines.append("")
    lines.append("| 路径 | 请求数 |")
    lines.append("|---|---|")
    for path, count in stats.paths.most_common(top):
        lines.append(f"| `{path}` | {count:,} |")
    lines.append("")

    if stats.request_times:
        lines.append("## 响应时间")
        lines.append("")
        lines.append("| 指标 | 毫秒 |")
        lines.append("|---|---|")
        for label, q in (("P50", 0.50), ("P90", 0.90), ("P95", 0.95), ("P99", 0.99)):
            lines.append(f"| {label} | {percentile(stats.request_times, q) * 1000:.0f} |")
        slow_ratio = len(stats.slow) / len(stats.request_times) * 100
        lines.append(f"| 慢请求（≥{slow_ms:.0f}ms） | {len(stats.slow)} 次，占 {slow_ratio:.1f}% |")
        lines.append("")

    if stats.slow:
        lines.append("## 最慢的 5 个请求")
        lines.append("")
        lines.append("| 耗时(ms) | 状态 | 路径 | IP |")
        lines.append("|---|---|---|---|")
        for entry in sorted(stats.slow, key=lambda e: e.request_time or 0, reverse=True)[:5]:
            lines.append(
                f"| {(entry.request_time or 0) * 1000:.0f} | {entry.status} | "
                f"`{entry.path}` | {entry.ip} |"
            )
        lines.append("")

    lines.append("## 请求量按小时")
    lines.append("")
    peak = max(stats.hours.values())
    for hour in range(24):
        count = stats.hours.get(hour, 0)
        if count == 0:
            continue
        bar = "█" * max(1, round(count / peak * 30))
        lines.append(f"`{hour:02d}:00` {bar} {count}")
    lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="分析 Nginx access.log，输出 Markdown 报告")
    parser.add_argument("logfile", help="日志文件路径，支持 - 从标准输入读")
    parser.add_argument("--top", type=int, default=10, help="Top 路径数量（默认 10）")
    parser.add_argument("--slow-ms", type=float, default=800.0, help="慢请求阈值，毫秒（默认 800）")
    parser.add_argument("--output", help="写入文件，默认打印到标准输出")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.logfile == "-":
            stats = analyze(sys.stdin, slow_ms=args.slow_ms)
        else:
            with open(args.logfile, encoding="utf-8", errors="replace") as fh:
                stats = analyze(fh, slow_ms=args.slow_ms)
    except OSError as exc:
        print(f"读取日志失败：{exc}", file=sys.stderr)
        return 2

    report = build_report(stats, top=args.top, slow_ms=args.slow_ms)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"报告已写入 {args.output}（{stats.total} 行日志）")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
