# Internet Download Speed Test

A small command-line tool that measures download speed: it downloads the same
URL several times (10 by default), strictly one request after another, measures
how long each download takes and how many bytes actually arrive, and prints the
resulting speed.

The decisions taken on ambiguous points of the task are listed in
[How the task was interpreted](#how-the-task-was-interpreted).

## Quick start

```bash
git clone https://github.com/mikholand/internet-speed-test.git
cd internet-speed-test
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py "https://speed.cloudflare.com/__down?bytes=5000000"
```

The last line of the report shows the result, for example
`Download speed:   9.22 MB/s (73.77 Mbps)`. On macOS and Linux use `python3`
if `python` is not found. Details for each system are in
[Installation](#installation) and [Usage](#usage).

## Features

- Exactly **10 sequential requests** by default; each one starts only after the
  previous response body has been fully downloaded.
- Precise timing with `time.perf_counter()`, from sending the request to
  receiving the last byte of the body.
- Volume is counted from the **bytes actually received**, not from the
  `Content-Length` header.
- Per-request time, size and speed, then a summary: total volume, total time,
  average time per request and the overall download speed in MB/s (with Mbps
  alongside).
- One HTTP client for the whole run: the connection is kept alive and reused.
- Clear error messages and non-zero exit codes for invalid URLs, connection
  errors, timeouts, HTTP 4xx/5xx and empty responses.
- One runtime dependency (`httpx`), a single source file, and tests that need
  no internet access.

## Requirements

- Python **3.10 or newer** (tested with 3.10 and 3.12)
- `pip`
- Internet access to the URL you want to test

## Installation

```bash
git clone https://github.com/mikholand/internet-speed-test.git
cd internet-speed-test
```

Create a virtual environment and install the dependency.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If PowerShell refuses to run `Activate.ps1`, skip activation and call the
> interpreter directly: `.venv\Scripts\python.exe -m pip install -r requirements.txt`,
> then `.venv\Scripts\python.exe main.py <URL>`.

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py <URL> [--count N] [--timeout SECONDS]
```

### Examples

```bash
# Default: 10 sequential requests, 30-second timeout
python main.py https://example.com/image.jpg

# Cloudflare's speed-test endpoint returns exactly the requested number of bytes
python main.py "https://speed.cloudflare.com/__down?bytes=5000000"

# A large image (redirects to a CDN; redirects are followed automatically)
python main.py https://picsum.photos/seed/speedtest/3840/2160

# Fewer requests and a shorter timeout
python main.py https://example.com/image.jpg --count 5 --timeout 10

# Help
python main.py --help
```

Put the URL in quotes if it contains `?` or `&`, otherwise the shell may
interpret those characters.

Use a resource of at least a few megabytes. For small files the time is
dominated by network latency (round trips), not by bandwidth, so the reported
speed will be much lower than your connection can deliver.

### Command-line options

| Argument | Default | Description |
|---|---|---|
| `url` (positional) | required | Absolute `http://` or `https://` URL of the resource to download. |
| `-c`, `--count` | `10` | Number of sequential requests. Must be a positive integer. |
| `-t`, `--timeout` | `30` | Timeout in seconds for establishing a connection and for **each wait for data** (see [Timeout](#timeout)). Must be a positive number. |
| `-h`, `--help` | | Show help and exit. |

### Sample output

Real output of `python main.py "https://speed.cloudflare.com/__down?bytes=5000000"`:

```text
========================================================
              INTERNET DOWNLOAD SPEED TEST
========================================================

URL:      https://speed.cloudflare.com/__down?bytes=5000000
Requests: 10
Timeout:  30 sec

Request  1/10:   0.726 sec |   5.00 MB |  6.89 MB/s
Request  2/10:   0.545 sec |   5.00 MB |  9.17 MB/s
Request  3/10:   0.509 sec |   5.00 MB |  9.82 MB/s
Request  4/10:   0.506 sec |   5.00 MB |  9.87 MB/s
Request  5/10:   0.509 sec |   5.00 MB |  9.82 MB/s
Request  6/10:   0.514 sec |   5.00 MB |  9.72 MB/s
Request  7/10:   0.547 sec |   5.00 MB |  9.14 MB/s
Request  8/10:   0.499 sec |   5.00 MB | 10.02 MB/s
Request  9/10:   0.540 sec |   5.00 MB |  9.25 MB/s
Request 10/10:   0.526 sec |   5.00 MB |  9.51 MB/s

--------------------------------------------------------
RESULTS
--------------------------------------------------------

Total downloaded: 50.00 MB (50,000,000 bytes)
Total time:       5.422 sec
Average time:     0.542 sec
Download speed:   9.22 MB/s (73.77 Mbps)

========================================================
```

The first request is usually the slowest: it includes the DNS lookup and the
TCP and TLS handshakes. The following requests reuse the same connection.

## How the task was interpreted

The task statement is short, so several points allow more than one reading.
These are the decisions taken and the reason for each.

| Point | Decision | Reason |
|---|---|---|
| Speed unit ("мб/с" in the task) | Megabytes per second, decimal (1 MB = 10⁶ bytes), printed first; the same value in Mbps in brackets | "мб/с" most commonly means megabytes per second; Mbps is added because internet plans are sold in it |
| "Wait for the response" | A request ends when the last byte of the body has arrived, not when the headers arrive | The speed has to cover the actual data transfer |
| "10 sequential requests" | Exactly 10 by default, each started only after the previous body is fully read; no extra warm-up request. `--count` exists, but the default stays 10 | A warm-up request would mean 11 requests to the server |
| Downloaded volume | Body bytes actually received; HTTP headers are not counted and `Content-Length` is not used | The header can be missing or wrong; the body is the data the user asked for |
| Speed formula | Total bytes / total time of the requests; pauses between requests are excluded | The average of per-request speeds overstates the result (see [Units and formulas](#units-and-formulas)) |
| Connection setup (not in the task) | Counted: the first request includes DNS, TCP and TLS; the others reuse the connection | It is part of a real request, and reusing the connection is what a normal HTTP client does |
| Redirects (not in the task) | Followed; their time is part of the request | Image URLs often redirect to a CDN |
| Timeout (not in the task) | 30 seconds without network activity, not a cap on the total download time | A slow but working link is a result to report, not a failure |
| Failed request (not in the task) | The run stops, no summary is printed, exit code 1 | A speed based on fewer downloads than requested, or with zeros filled in, would be misleading |
| Empty response (not in the task) | Treated as a failure | There is nothing to measure |
| Language (not in the task) | Python 3.10+ | The task does not name a language |

## How the measurement works

1. A single `httpx.Client` is created for the whole run. Its connection pool
   keeps the connection alive, so later requests skip connection setup.
2. For each request `i` (1…N), strictly sequentially:
   - the timer starts (`time.perf_counter()`) right before the `GET` request
     is sent;
   - the response status is checked (4xx/5xx is an error);
   - the body is read as a stream, and the length of every received chunk is
     added up (`response.iter_raw()`), so the size is what actually arrived,
     whatever the `Content-Length` header says;
   - the timer stops right after the last byte of the body is received.
3. Printing a result happens after the timer has stopped, so the time between
   requests is never counted. Only the time spent on the HTTP requests is.

The measured time `tᵢ` therefore includes sending the request, server
processing, following redirects (if any) and downloading the whole body. The
measured volume `bᵢ` is the body only: HTTP headers and TLS overhead are not
counted, so the result is the useful (application-level) throughput.

Requests are sent with `Accept-Encoding: identity`, which asks the server not
to compress the body. The measured volume then equals the real size of the
resource. If a server compresses anyway, the raw (compressed) bytes that
crossed the network are counted, because that is what was actually downloaded.

## Units and formulas

All units are **decimal (SI)**, the same convention ISPs and speed-test
services use:

| Unit | Value |
|---|---|
| 1 KB / 1 MB / 1 GB | 10³ / 10⁶ / 10⁹ bytes |
| 1 Kbps / 1 Mbps / 1 Gbps | 10³ / 10⁶ / 10⁹ bits per second |
| 1 MB/s | 8 Mbps |

The main unit is **megabytes per second (MB/s)**: the task asks for the speed
in "мб/с", and MB/s relates directly to file sizes. The same value in
**megabits per second (Mbps)** is shown in brackets, because internet plans are
sold in Mbps. Both stay in mega-units even on a slow link (`0.50 MB/s`). Only a
rate that would round to `0.00` gets a smaller prefix, for example `2.12 KB/s`
instead of a misleading `0.00 MB/s`.

> File managers such as Windows Explorer show sizes in binary units
> (1 MiB = 1,048,576 bytes) but label them "MB". The same 5,000,000-byte file
> is 5.00 MB here and "4.76 MB" in Explorer.

For `N` requests, where request `i` took `tᵢ` seconds and delivered `bᵢ` bytes:

```text
Total downloaded  B = b₁ + b₂ + … + bₙ                      (bytes)
Total time        T = t₁ + t₂ + … + tₙ                      (seconds)
Average time        = T / N                                 (seconds)
Download speed      = B / T / 1 000 000                     (MB/s)
                    = B × 8 / T / 1 000 000                 (Mbps)
```

Per-request speed in each line is `bᵢ / tᵢ`, shown in MB/s.

The overall speed is **total bytes divided by total time**, not the average of
the per-request speeds. For example, 1 MB in 1 s plus 1 MB in 3 s is
2 MB / 4 s = **0.50 MB/s**. Averaging the two speeds (1.00 and 0.33 MB/s) would
give 0.67 MB/s, which overstates the speed because it gives the fast request as
much weight as the slow one.

## Error handling

The run is **all or nothing**: the first failed request stops the test. A
failed request is never counted as zero time or zero bytes, and no partial
summary is printed. Errors go to stderr and the program exits with a non-zero
code.

| Situation | Example message | Exit code |
|---|---|---|
| Invalid URL (no scheme, not http/https, no host, bad port) | `error: argument url: invalid URL 'example.com/image.jpg': expected an absolute URL starting with http:// or https://` | 2 |
| Invalid `--count` / `--timeout` | `error: argument -c/--count: expected a positive integer, got '0'` | 2 |
| Unknown host / connection refused | `Error: Request 1/10 failed: could not connect to the server ([Errno 11001] getaddrinfo failed)` | 1 |
| Connection timeout | `Error: Request 1/10 failed: timed out while connecting to the server` | 1 |
| Server stops sending data (read timeout) | `Error: Request 1/10 failed: timed out while waiting for data from the server` | 1 |
| HTTP 4xx / 5xx | `Error: Request 3/10 failed: server responded with HTTP 503 Service Unavailable` | 1 |
| Empty body (e.g. HTTP 204) | `Error: Request 1/10 failed: the server returned an empty response body` | 1 |
| Connection dropped mid-download, too many redirects, other protocol errors | `Error: Request 1/10 failed: network error (peer closed connection without sending complete message body (received 400000 bytes, expected 1000000))` | 1 |
| Interrupted with Ctrl+C | `Interrupted by user.` | 130 |
| Output closed early, e.g. piped to `head` | Stops quietly, no traceback | 1 |

Invalid arguments are rejected before any network request is made. Exit code 2
is the standard `argparse` code for usage errors.

Anything not in this table would be a bug in the tool. Such errors are
deliberately not caught, so their traceback stays visible (Python exits with
code 1).

### Timeout

`--timeout` limits how long the tool waits to **establish a connection** and
how long it waits for **each next portion of data**. It does not cap the total
duration of a download. A large file on a slow but working connection is
measured to the end, while a server that stops responding is detected within
`--timeout` seconds. A hard cap on total time would turn a slow connection,
which is exactly what a speed test should report, into a failure.

Redirects are followed automatically (up to 20 per request). The time spent on
redirects is part of the request time.

## Development and tests

Install the development tools (pytest, pytest-cov, ruff, mypy) into the
virtual environment:

```bash
pip install -r requirements-dev.txt
```

Run the checks the project is kept clean with:

```bash
python -m pytest --cov    # tests with line and branch coverage; fails below 100%
ruff check .              # linting
ruff format --check .     # formatting
mypy                      # strict type checking
```

Tool settings are in `pyproject.toml`. That file holds only tool
configuration: the project is a single script, not an installable package.

The tests need no internet access. Most of them replace HTTP with
`httpx.MockTransport`; the end-to-end tests use a temporary HTTP server on
`127.0.0.1`, and some run `main.py` as a separate process. They cover:

- byte counting (streamed body without `Content-Length`, misleading `Content-Length`);
- strictly sequential execution: each response is fully read before the next
  request starts;
- stopping at the first failure, with the request number in the message;
- HTTP errors (including a status without a reason phrase), empty body,
  connection errors and timeouts;
- the speed formula (total bytes / total time) and unit formatting;
- CLI validation, Ctrl+C, a closed output pipe, and the exit codes of the real
  process;
- over real sockets: connection reuse (all 10 requests over one keep-alive
  connection), a timeout before the headers and in the middle of the body, a
  followed redirect, and a body cut off mid-download, which must stop the run
  with exit code 1 and must not be retried.

## Project structure

```text
internet-speed-test/
├── main.py               # the whole tool: CLI, measurement, calculations, report
├── test_main.py          # pytest tests (no internet needed)
├── requirements.txt      # runtime dependency: httpx
├── requirements-dev.txt  # runtime + pytest, pytest-cov, ruff, mypy
├── pyproject.toml        # settings for the development tools only
├── README.md
└── .gitignore
```

## Design notes

**Why `httpx`.** `requests` would also work, but `httpx` fits this task
better:

- `httpx.Client` used as a context manager manages the connection pool and its
  lifetime;
- the streaming API (`client.stream()` and `iter_raw()`) yields the body
  exactly as it arrives, which makes byte counting straightforward;
- it has separate connect/read timeouts and a precise exception hierarchy
  (`ConnectError`, `ConnectTimeout`, `ReadTimeout`, `HTTPStatusError`, …),
  which map to clear messages;
- `httpx.MockTransport` allows testing without a network and without extra
  mocking libraries;
- the code is fully type-annotated.

**Why a single file.** The tool is about 330 lines with one job. The code is
already split into small functions with one responsibility each (parse
arguments → measure a request → run the series → summarize → format), so
separate modules would only add imports. Those functions can be moved into
modules later without changes if the tool grows.

**No concurrency.** There is no `asyncio`, threading or multiprocessing. The
requests run in a plain loop, and each download is fully consumed before the
loop continues.

## Limitations

- The tool measures a single HTTP connection. Speed-test services that open
  several parallel connections may report higher numbers on fast links.
- The result depends on the server as well as your connection: its distance,
  load and upload capacity. Choose a fast, nearby host (for example a CDN) for
  the most representative numbers.
