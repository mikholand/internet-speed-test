"""Measure HTTP download speed by fetching the same URL several times in a row.

Usage:
    python main.py https://example.com/image.jpg [--count 10] [--timeout 30]
"""

import argparse
import math
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

DEFAULT_REQUEST_COUNT = 10
DEFAULT_TIMEOUT_SECONDS = 30.0

BITS_PER_BYTE = 8
# Decimal (SI) prefixes for both bytes and bits: 1 MB = 10**6 bytes = 8 Mbit.
DECIMAL_PREFIXES = (("G", 1_000_000_000), ("M", 1_000_000), ("K", 1_000))

MAX_PORT = 65_535

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_INTERRUPTED = 130

REPORT_WIDTH = 56
USER_AGENT = "internet-speed-test/1.0"


class SpeedTestError(Exception):
    """Raised when a download cannot be completed and measured."""


@dataclass(frozen=True, slots=True)
class RequestMeasurement:
    """Time and volume of one fully completed download."""

    elapsed_seconds: float
    downloaded_bytes: int

    @property
    def bits_per_second(self) -> float:
        return transfer_rate(self.downloaded_bytes, self.elapsed_seconds)


@dataclass(frozen=True, slots=True)
class SpeedTestSummary:
    """Aggregated result of all downloads."""

    request_count: int
    total_bytes: int
    total_seconds: float

    @property
    def average_seconds(self) -> float:
        return self.total_seconds / self.request_count

    @property
    def bits_per_second(self) -> float:
        return transfer_rate(self.total_bytes, self.total_seconds)


def transfer_rate(num_bytes: int, seconds: float) -> float:
    """Return the transfer rate in bits per second."""
    return num_bytes * BITS_PER_BYTE / seconds


def http_url(value: str) -> str:
    """argparse type: accept only absolute http:// or https:// URLs."""
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL as error:
        raise argparse.ArgumentTypeError(f"invalid URL {value!r}: {error}") from None
    if url.scheme not in ("http", "https") or not url.host:
        raise argparse.ArgumentTypeError(
            f"invalid URL {value!r}: expected an absolute URL "
            "starting with http:// or https://"
        )
    if url.port is not None and not 1 <= url.port <= MAX_PORT:
        raise argparse.ArgumentTypeError(
            f"invalid URL {value!r}: port must be between 1 and {MAX_PORT}"
        )
    return value


def positive_int(value: str) -> int:
    """argparse type: an integer greater than zero."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, got {value!r}"
        ) from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return number


def positive_float(value: str) -> float:
    """argparse type: a finite number greater than zero."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a positive number, got {value!r}"
        ) from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive number, got {value!r}")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure download speed by fetching a URL several times, "
            "strictly one request after another."
        ),
        epilog="Example: python main.py https://example.com/image.jpg",
    )
    parser.add_argument(
        "url",
        type=http_url,
        help="URL of the resource to download (http:// or https://)",
    )
    parser.add_argument(
        "-c",
        "--count",
        type=positive_int,
        default=DEFAULT_REQUEST_COUNT,
        help=f"number of sequential requests (default: {DEFAULT_REQUEST_COUNT})",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "timeout in seconds for connecting and for each wait for data "
            f"(default: {DEFAULT_TIMEOUT_SECONDS:g})"
        ),
    )
    return parser.parse_args(argv)


def create_client(timeout: float) -> httpx.Client:
    """Create the single HTTP client shared by all requests (keep-alive pool)."""
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={
            # Ask for the body as is, so the volume is the real resource size.
            "Accept-Encoding": "identity",
            "User-Agent": USER_AGENT,
        },
    )


def measure_request(client: httpx.Client, url: str) -> RequestMeasurement:
    """Download the URL once and measure the elapsed time and body bytes received.

    The timer covers sending the request, waiting for the response and reading
    the whole body. Bytes are counted as they arrive (raw, before any content
    decoding), so the result never relies on the Content-Length header.
    """
    started_at = time.perf_counter()
    with client.stream("GET", url) as response:
        response.raise_for_status()
        downloaded_bytes = sum(len(chunk) for chunk in response.iter_raw())
        elapsed_seconds = time.perf_counter() - started_at
    if downloaded_bytes == 0:
        raise SpeedTestError("the server returned an empty response body")
    return RequestMeasurement(
        elapsed_seconds=elapsed_seconds, downloaded_bytes=downloaded_bytes
    )


def describe_error(error: Exception) -> str:
    """Turn a request failure into a short human-readable reason."""
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        status = f"{response.status_code} {response.reason_phrase}".rstrip()
        return f"server responded with HTTP {status}"
    if isinstance(error, httpx.ConnectTimeout):
        return "timed out while connecting to the server"
    if isinstance(error, httpx.TimeoutException):
        return "timed out while waiting for data from the server"
    if isinstance(error, httpx.ConnectError):
        return f"could not connect to the server ({error})"
    if isinstance(error, httpx.RequestError):
        return f"network error ({str(error) or type(error).__name__})"
    return str(error)


def run_speed_test(
    client: httpx.Client, url: str, count: int
) -> list[RequestMeasurement]:
    """Download the URL `count` times, each request after the previous one ends.

    Every result is printed as soon as its request completes; printing is
    outside the timed section. The first failed request aborts the run.
    """
    measurements: list[RequestMeasurement] = []
    for number in range(1, count + 1):
        try:
            measurement = measure_request(client, url)
        except (httpx.HTTPError, SpeedTestError) as error:
            raise SpeedTestError(
                f"Request {number}/{count} failed: {describe_error(error)}"
            ) from error
        measurements.append(measurement)
        print(format_measurement(number, count, measurement), flush=True)
    return measurements


def summarize(measurements: Sequence[RequestMeasurement]) -> SpeedTestSummary:
    if not measurements:
        raise ValueError("at least one measurement is required")
    return SpeedTestSummary(
        request_count=len(measurements),
        total_bytes=sum(item.downloaded_bytes for item in measurements),
        total_seconds=sum(item.elapsed_seconds for item in measurements),
    )


def format_decimal(value: float, unit: str) -> str:
    """Format a value with a decimal prefix, e.g. 1_240_000 B -> '1.24 MB'."""
    for prefix, factor in DECIMAL_PREFIXES:
        if value >= factor:
            return f"{value / factor:.2f} {prefix}{unit}"
    return f"{value:.0f} {unit}"


def format_header(url: str, count: int, timeout: float) -> str:
    return "\n".join(
        [
            "=" * REPORT_WIDTH,
            "INTERNET DOWNLOAD SPEED TEST".center(REPORT_WIDTH).rstrip(),
            "=" * REPORT_WIDTH,
            "",
            f"URL:      {url}",
            f"Requests: {count}",
            f"Timeout:  {timeout:g} sec",
            "",
        ]
    )


def format_measurement(number: int, count: int, measurement: RequestMeasurement) -> str:
    number_width = len(str(count))
    return (
        f"Request {number:>{number_width}}/{count}: "
        f"{measurement.elapsed_seconds:7.3f} sec | "
        f"{format_decimal(measurement.downloaded_bytes, 'B'):>9} | "
        f"{format_decimal(measurement.bits_per_second, 'bps'):>11}"
    )


def format_summary(summary: SpeedTestSummary) -> str:
    bytes_per_second = summary.bits_per_second / BITS_PER_BYTE
    return "\n".join(
        [
            "",
            "-" * REPORT_WIDTH,
            "RESULTS",
            "-" * REPORT_WIDTH,
            "",
            f"Total downloaded: {format_decimal(summary.total_bytes, 'B')} "
            f"({summary.total_bytes:,} bytes)",
            f"Total time:       {summary.total_seconds:.3f} sec",
            f"Average time:     {summary.average_seconds:.3f} sec",
            f"Download speed:   {format_decimal(summary.bits_per_second, 'bps')} "
            f"({format_decimal(bytes_per_second, 'B/s')})",
            "",
            "=" * REPORT_WIDTH,
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    print(format_header(args.url, args.count, args.timeout), flush=True)
    try:
        with create_client(args.timeout) as client:
            measurements = run_speed_test(client, args.url, args.count)
    except SpeedTestError as error:
        print(f"\nError: {error}", file=sys.stderr)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return EXIT_INTERRUPTED
    print(format_summary(summarize(measurements)))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
