# log-analyzer

> 把一份 Nginx 的 `access.log`，变成一份能直接贴进周报的 Markdown 报表。

线上出问题时，第一件事是看日志。但 `tail -f` 只能看当下，`awk` 写起来每次都不一样。
这个脚本把常见的几种统计固化成一条命令：请求量、独立 IP、状态码分布、Top 路径、
错误率、响应时间分位、慢请求，顺便画出按小时的请求分布。

## 功能

- **一行命令出报告**：Markdown 表格，贴进周报或 Wiki 即可
- **概况**：总请求数、独立 IP、错误率、5xx 数量、出流量
- **Top 路径**：按请求数排序，自动去掉 query string
- **响应时间**：P50 / P90 / P95 / P99，以及超过阈值的慢请求
- **慢请求明细**：最慢的 5 个请求，带状态码和来源 IP
- **小时分布**：终端里的小柱状图，一眼看出流量高峰
- 纯标准库，兼容 `nginx combined` 格式，末尾有 `$request_time` 时额外统计耗时

## 用法

```bash
python log_analyzer.py data/sample.log
python log_analyzer.py data/sample.log --top 5 --slow-ms 500
python log_analyzer.py /var/log/nginx/access.log --output report.md
tail -n 1000 /var/log/nginx/access.log | python log_analyzer.py -
```

| 参数 | 说明 |
|---|---|
| `logfile` | 日志路径，写 `-` 表示从标准输入读 |
| `--top` | Top 路径数量，默认 10 |
| `--slow-ms` | 慢请求阈值（毫秒），默认 800 |
| `--output` | 写入文件，默认打印到终端 |

## 示例报告

```markdown
## 概况

| 指标 | 数值 |
|---|---|
| 总请求数 | 11 |
| 独立 IP | 6 |
| 错误率（4xx + 5xx） | 45.45% |
| 5xx 请求数 | 2 |
| 出流量 | 33.0 KB |

## 响应时间

| 指标 | 毫秒 |
|---|---|
| P50 | 12 |
| P90 | 1842 |
| P95 | 1872 |
| P99 | 1897 |
| 慢请求（≥800ms） | 2 次，占 18.2% |

## 请求量按小时

`09:00` ██████████████████████████████ 5
`10:00` ████████████ 2
`14:00` ████████████ 2
`20:00` ████████████ 2
```

## 日志格式

默认按 nginx 的 `combined` 解析：

```
$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
```

如果在 `log_format` 末尾加了 `$request_time`，耗时统计会自动生效：

```nginx
log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                '$status $body_bytes_sent "$http_referer" "$http_user_agent" $request_time';
```

解析不了的行不会中断统计，只会记进「无法解析的行」，方便发现格式变化。

## 目录结构

```
log-analyzer/
├── log_analyzer.py            # 解析 + 统计 + 出报告
├── data/sample.log            # 示例日志（含 1 行坏数据）
├── tests/test_log_analyzer.py # 16 个单元测试
├── LICENSE
└── README.md
```

## 测试

```bash
python -m unittest discover -s tests
```

16 个测试覆盖：字段解析、query string 剥离、缺少 `$request_time` 的兼容、
坏行计数、状态码 / IP / 小时统计、慢请求识别、分位数插值、报告结构、命令行出口。

## 后续计划

- [ ] 支持 `*.log.gz` 直接读取
- [ ] 按时间窗口过滤（`--since 10:00 --until 11:00`）
- [ ] 多文件合并，做日环比
- [ ] 输出 HTML 图表（不引第三方库，手写 SVG）

## 说明

个人项目，用来练日志处理和统计。真实环境的日志格式千变万化，
如果解析失败，先确认 `log_format` 是否改过。
