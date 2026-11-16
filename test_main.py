"""Tests for main.py.

Most tests replace the network with httpx.MockTransport; the end-to-end tests
use a throwaway HTTP server on 127.0.0.1, so no internet access is required.
"""

import http.server
import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest

import main

URL = "https://example.com/image.jpg"

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def streamed_response(
    body: bytes, status_code: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    """Build a response with an unread body, as a real transport returns it.

    httpx.Response(content=...) loads the body eagerly, so iter_raw() could not
    stream it; passing stream=... mimics a network response.
    """
    return httpx.Response(
        status_code,
        headers={"Content-Length": str(len(body)), **(headers or {})},
        stream=httpx.ByteStream(body),
    )


# --- Measuring a single request ---------------------------------------------


def test_measure_request_counts_bytes_of_streamed_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # A chunked body has no Content-Length: bytes must be counted on arrival.
        return httpx.Response(200, content=iter([b"a" * 1000, b"b" * 500]))

    with make_client(handler) as client:
        measurement = main.measure_request(client, URL)

    assert measurement.downloaded_bytes == 1500
    assert measurement.elapsed_seconds > 0


def test_measure_request_ignores_content_length_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return streamed_response(b"x" * 100, headers={"Content-Length": "999999"})

    with make_client(handler) as client:
        assert main.measure_request(client, URL).downloaded_bytes == 100


@pytest.mark.parametrize("status_code", [403, 404, 500, 503])
def test_measure_request_raises_for_http_error_status(status_code: int) -> None:
    with (
        make_client(lambda request: httpx.Response(status_code)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        main.measure_request(client, URL)


def test_measure_request_rejects_empty_body() -> None:
    with (
        make_client(lambda request: streamed_response(b"")) as client,
        pytest.raises(main.SpeedTestError, match="empty response body"),
    ):
        main.measure_request(client, URL)


# --- Running the whole series -----------------------------------------------


def test_run_speed_test_downloads_strictly_one_after_another(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        number = len(events) // 2 + 1
        events.append(f"start {number}")

        def body() -> Iterator[bytes]:
            yield b"x" * 1024
            events.append(f"end {number}")  # runs once the body is fully read

        return httpx.Response(200, content=body())

    with make_client(handler) as client:
        measurements = main.run_speed_test(client, URL, count=10)

    assert len(measurements) == 10
    assert all(item.downloaded_bytes == 1024 for item in measurements)
    assert events == [
        event for n in range(1, 11) for event in (f"start {n}", f"end {n}")
    ]
    assert capsys.readouterr().out.count("Request ") == 10


def test_run_speed_test_stops_at_first_failed_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return streamed_response(b"x" * 100, status_code=500 if calls == 3 else 200)

    with (
        make_client(handler) as client,
        pytest.raises(
            main.SpeedTestError,
            match=r"Request 3/10 failed: server responded with HTTP 500",
        ),
    ):
        main.run_speed_test(client, URL, count=10)

    assert calls == 3


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (httpx.ConnectError("Name or service not known"), "could not connect"),
        (httpx.ConnectTimeout("timed out"), "timed out while connecting"),
        (httpx.ReadTimeout("timed out"), "timed out while waiting for data"),
        (httpx.RemoteProtocolError("peer closed connection"), "network error"),
        (httpx.TooManyRedirects("Exceeded maximum allowed redirects."), "redirects"),
        (httpx.ReadError(""), "network error (ReadError)"),  # empty message
    ],
)
def test_run_speed_test_reports_network_errors(
    error: httpx.HTTPError, expected_reason: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with (
        make_client(handler) as client,
        pytest.raises(main.SpeedTestError, match="Request 1/2 failed: ") as error_info,
    ):
        main.run_speed_test(client, URL, count=2)

    assert expected_reason in str(error_info.value)


# --- Calculations and formatting --------------------------------------------


def test_summarize_divides_total_bytes_by_total_time() -> None:
    summary = main.summarize(
        [
            main.RequestMeasurement(elapsed_seconds=1.0, downloaded_bytes=1_000_000),
            main.RequestMeasurement(elapsed_seconds=3.0, downloaded_bytes=1_000_000),
        ]
    )

    assert summary.total_bytes == 2_000_000
    assert summary.total_seconds == pytest.approx(4.0)
    assert summary.average_seconds == pytest.approx(2.0)
    # 16 Mbit in 4 s = 4 Mbps, not the 5.33 Mbps mean of per-request speeds.
    assert summary.bits_per_second == pytest.approx(4_000_000)


def test_summarize_requires_measurements() -> None:
    with pytest.raises(ValueError, match="at least one measurement"):
        main.summarize([])


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (0, "B", "0 B"),
        (999, "B", "999 B"),
        (1_000, "B", "1.00 KB"),
        (1_240_000, "B", "1.24 MB"),
        (2_500_000_000, "B", "2.50 GB"),
    ],
)
def test_format_decimal_uses_si_prefixes(
    value: float, unit: str, expected: str
) -> None:
    assert main.format_decimal(value, unit) == expected


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (9_620_000, "B/s", "9.62 MB/s"),
        (500_000, "B/s", "0.50 MB/s"),  # a slow link still reads in MB/s
        (10_000, "B/s", "0.01 MB/s"),
        (2_120, "B/s", "2.12 KB/s"),  # would otherwise print as 0.00 MB/s
        (212, "B/s", "212 B/s"),
        (76_950_000, "bps", "76.95 Mbps"),
        (1_250_000_000, "bps", "1250.00 Mbps"),
        (1_668.3, "bps", "1.67 Kbps"),
    ],
)
def test_format_rate_prefers_mega_units(value: float, unit: str, expected: str) -> None:
    assert main.format_rate(value, unit) == expected


def test_summary_reports_megabytes_per_second_first() -> None:
    summary = main.SpeedTestSummary(
        request_count=10, total_bytes=50_000_000, total_seconds=5.198
    )

    assert "Download speed:   9.62 MB/s (76.95 Mbps)" in main.format_summary(summary)


# --- Command line -----------------------------------------------------------


def test_parse_args_defaults_match_assignment() -> None:
    args = main.parse_args([URL])

    assert (args.url, args.count, args.timeout) == (URL, 10, 30.0)


@pytest.mark.parametrize(
    "url",
    [
        "example.com/image.jpg",
        "ftp://example.com/image.jpg",
        "https://",
        "http://[::1",
        "https://example.com:99999/image.jpg",
    ],
)
def test_parse_args_rejects_invalid_url(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main.parse_args([url])

    assert exit_info.value.code == 2
    assert "invalid URL" in capsys.readouterr().err


@pytest.mark.parametrize(
    "options",
    [
        ["--count", "0"],
        ["--count", "-1"],
        ["--count", "ten"],
        ["--timeout", "0"],
        ["--timeout", "-5"],
        ["--timeout", "nan"],
        ["--timeout", "inf"],
    ],
)
def test_parse_args_rejects_invalid_options(options: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main.parse_args([URL, *options])

    assert exit_info.value.code == 2


def test_create_client_configuration() -> None:
    with main.create_client(timeout=12.5) as client:
        assert client.timeout == httpx.Timeout(12.5)
        assert client.follow_redirects is True
        assert client.headers["Accept-Encoding"] == "identity"


def test_main_prints_summary_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        main,
        "create_client",
        lambda timeout: make_client(lambda request: streamed_response(b"x" * 2000)),
    )

    assert main.main([URL, "--count", "3"]) == 0

    output = capsys.readouterr().out
    assert output.count("Request ") == 3
    assert "Total downloaded: 6.00 KB (6,000 bytes)" in output
    assert "Download speed:" in output


def test_main_reports_error_and_returns_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        main,
        "create_client",
        lambda timeout: make_client(lambda request: httpx.Response(404)),
    )

    assert main.main([URL]) == 1

    captured = capsys.readouterr()
    assert (
        "Request 1/10 failed: server responded with HTTP 404 Not Found" in captured.err
    )
    assert "RESULTS" not in captured.out


# --- End to end over real sockets -------------------------------------------

LOCAL_BODY_SIZE = 256_000


class RecordingServer(http.server.ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), RecordingHandler)
        self.client_ports: list[int] = []
        self.paths: list[str] = []


class RecordingHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, so the client can reuse a connection

    def do_GET(self) -> None:
        assert isinstance(self.server, RecordingServer)
        self.server.client_ports.append(self.client_address[1])
        self.server.paths.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/file.bin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/slow":
            time.sleep(1)
        body = b"x" * LOCAL_BODY_SIZE
        half = len(body) // 2
        # The 2nd request to /drop-second gets half the promised body, then a hang-up.
        truncated = self.path == "/drop-second" and len(self.server.client_ports) == 2
        try:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if truncated:
                self.wfile.write(body[:half])
            elif self.path == "/stall-body":
                self.wfile.write(body[:half])
                self.wfile.flush()
                time.sleep(1)  # goes silent in the middle of the body
                self.wfile.write(body[half:])
            else:
                self.wfile.write(body)
        except ConnectionError:
            pass  # the client gave up (timeout tests)
        if truncated:
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def local_server() -> Iterator[RecordingServer]:
    server = RecordingServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def local_url(server: RecordingServer, path: str) -> str:
    host, port = server.server_address[:2]
    return f"http://{host!s}:{port}{path}"


def test_end_to_end_reuses_one_connection_for_all_requests(
    local_server: RecordingServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main.main([local_url(local_server, "/file.bin")]) == 0

    assert len(local_server.client_ports) == 10
    assert len(set(local_server.client_ports)) == 1
    assert "Total downloaded: 2.56 MB (2,560,000 bytes)" in capsys.readouterr().out


def test_end_to_end_timeout_fails_with_non_zero_exit(
    local_server: RecordingServer, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main.main([local_url(local_server, "/slow"), "--timeout", "0.2"])

    assert exit_code == 1
    assert "timed out while waiting for data" in capsys.readouterr().err


def test_end_to_end_timeout_in_the_middle_of_the_body(
    local_server: RecordingServer, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main.main([local_url(local_server, "/stall-body"), "--timeout", "0.2"])

    assert exit_code == 1
    assert (
        "Request 1/10 failed: timed out while waiting for data"
        in capsys.readouterr().err
    )


def test_end_to_end_follows_redirects_and_counts_only_the_final_body(
    local_server: RecordingServer, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main.main([local_url(local_server, "/redirect"), "--count", "3"])

    assert exit_code == 0
    assert local_server.paths == ["/redirect", "/file.bin"] * 3
    assert "Total downloaded: 768.00 KB (768,000 bytes)" in capsys.readouterr().out


def test_end_to_end_truncated_body_fails_without_retry(
    local_server: RecordingServer, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main.main([local_url(local_server, "/drop-second")])

    assert exit_code == 1
    assert len(local_server.client_ports) == 2  # stopped at the failure, no retry
    captured = capsys.readouterr()
    assert "Request 2/10 failed: network error" in captured.err
    assert "received 128000 bytes, expected 256000" in captured.err
    assert "RESULTS" not in captured.out
