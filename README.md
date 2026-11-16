# Internet Download Speed Test

A small command-line tool that measures download speed: it downloads the same
URL several times (10 by default), strictly one request after another, measures
how long each download takes and how many bytes actually arrive, and prints the
resulting speed.

## Features

- Exactly **10 sequential requests** by default; each one starts only after the
  previous response body has been fully downloaded.
- Precise timing with `time.perf_counter()`, from sending the request to
  receiving the last byte of the body.
- Volume is counted from the **bytes actually received**, not from the
  `Content-Length` header.
- Per-request time, size and speed, then a summary: total volume, total time,
  average time per request and the overall download speed.
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

Request  1/10:   0.710 sec |   5.00 MB |  56.34 Mbps
Request  2/10:   0.479 sec |   5.00 MB |  83.57 Mbps
Request  3/10:   0.492 sec |   5.00 MB |  81.23 Mbps
Request  4/10:   0.527 sec |   5.00 MB |  75.87 Mbps
Request  5/10:   0.479 sec |   5.00 MB |  83.54 Mbps
Request  6/10:   0.496 sec |   5.00 MB |  80.66 Mbps
Request  7/10:   0.506 sec |   5.00 MB |  79.09 Mbps
Request  8/10:   0.529 sec |   5.00 MB |  75.66 Mbps
Request  9/10:   0.486 sec |   5.00 MB |  82.34 Mbps
Request 10/10:   0.495 sec |   5.00 MB |  80.78 Mbps

--------------------------------------------------------
RESULTS
--------------------------------------------------------

Total downloaded: 50.00 MB (50,000,000 bytes)
Total time:       5.198 sec
Average time:     0.520 sec
Download speed:   76.95 Mbps (9.62 MB/s)

========================================================
```

The first request is usually the slowest: it includes the DNS lookup and the
TCP and TLS handshakes. The following requests reuse the same connection.

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

The main unit is **megabits per second (Mbps)**, because internet plans are
sold in Mbps, so the result can be compared with your plan directly. The
equivalent in megabytes per second (MB/s) is shown in brackets, which is
easier to relate to file sizes. The prefix adapts to the value (for example,
a very slow transfer shows as `1.69 Kbps` instead of a misleading `0.00 Mbps`).

> File managers such as Windows Explorer show sizes in binary units
> (1 MiB = 1,048,576 bytes) but label them "MB". The same 5,000,000-byte file
> is 5.00 MB here and "4.76 MB" in Explorer.

For `N` requests, where request `i` took `tᵢ` seconds and delivered `bᵢ` bytes:

```text
Total downloaded  B = b₁ + b₂ + … + bₙ                      (bytes)
Total time        T = t₁ + t₂ + … + tₙ                      (seconds)
Average time        = T / N                                 (seconds)
Download speed      = B × 8 / T / 1 000 000                 (Mbps)
                    = B / T / 1 000 000                     (MB/s)
```

Per-request speed in each line is `bᵢ × 8 / tᵢ`.

The overall speed is **total bytes divided by total time**, not the average of
the per-request speeds. For example, 1 MB in 1 s plus 1 MB in 3 s is
16 Mbit / 4 s = **4 Mbps**. Averaging the two speeds (8 and 2.67 Mbps) would
give 5.33 Mbps, which overstates the speed because it gives the fast request
as much weight as the slow one.

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

Invalid arguments are rejected before any network request is made. Exit code 2
is the standard `argparse` code for usage errors.

### Timeout

`--timeout` limits how long the tool waits to **establish a connection** and
how long it waits for **each next portion of data**. It does not cap the total
duration of a download. A large file on a slow but working connection is
measured to the end, while a server that stops responding is detected within
`--timeout` seconds. A hard cap on total time would turn a slow connection,
which is exactly what a speed test should report, into a failure.

Redirects are followed automatically (up to 20 per request). The time spent on
redirects is part of the request time.

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests don't need internet access. HTTP is replaced by
`httpx.MockTransport`, and two end-to-end tests use a temporary HTTP server on
`127.0.0.1`. They cover:

- byte counting (streamed body without `Content-Length`, misleading `Content-Length`);
- strictly sequential execution: each response is fully read before the next
  request starts;
- stopping at the first failure, with the request number in the message;
- HTTP errors, empty body, connection errors and timeouts;
- the speed formula (total bytes / total time) and unit formatting;
- CLI validation and exit codes;
- connection reuse (all 10 requests over one keep-alive connection) and a real
  read timeout over sockets.

## Project structure

```text
internet-speed-test/
├── main.py               # the whole tool: CLI, measurement, calculations, report
├── test_main.py          # pytest tests (no internet needed)
├── requirements.txt      # runtime dependency: httpx
├── requirements-dev.txt  # runtime + pytest, for running tests
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

**Why a single file.** The tool is about 300 lines with one job. The code is
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
