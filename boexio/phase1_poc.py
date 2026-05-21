from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from html import unescape
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


SCHEMA_VERSION = "0.1.0"
PARSER_VERSION = "0.1.0"
USER_AGENT = "BoExioPriceMonitor/0.1 (+contact: boexio-ops@example.com)"
ALLOWED_HOST = "www.boconcept.com"
ALLOWED_INPUT_PREFIX = "/ja-jp/shop/"
DISCOVERED_PRODUCT_PREFIX = "/ja-jp/p/"
ROBOTS_DISALLOW_PATTERNS = (
    "*/search/?*",
    "*/shop/*_*",
    "*/shop/*?q=*",
    "*/on/demandware*",
    "*/p/*/print/",
    "*/store-lead/*",
    "*/undefined/*",
    "*/v/*",
)

CSV_COLUMNS = [
    "run_id",
    "source_url",
    "source_checked_at",
    "scrape_status",
    "scrape_error_code",
    "scrape_error_message",
    "brand",
    "series",
    "product_name",
    "base_item_number",
    "variant_id",
    "sku",
    "item_number",
    "selected_size",
    "selected_upholstery",
    "selected_leg",
    "width_cm",
    "depth_cm",
    "height_cm",
    "weight_kg",
    "material",
    "list_price",
    "display_price",
    "canonical_price",
    "price_from",
    "currency",
    "tax_type",
    "image_url",
    "pdf_url",
    "raw_data_ref",
]


class TextAndLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.texts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "a":
            attr_map = dict(attrs)
            self._current_href = attr_map.get("href")
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "a" and self._current_href:
            label = " ".join(self._current_text).strip()
            self.links.append((self._current_href, normalize_space(label)))
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = normalize_space(data)
        if not text:
            return
        self.texts.append(text)
        if self._current_href is not None:
            self._current_text.append(text)


@dataclass
class FetchResult:
    url: str
    html: str
    checked_at: str


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def read_target_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        urls.append(value)
    return urls


def is_robots_disallowed(url: str) -> bool:
    parsed = urlparse(url)
    target = parsed.path
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return any(fnmatch_like(target, pattern) for pattern in ROBOTS_DISALLOW_PATTERNS)


def fnmatch_like(path: str, pattern: str) -> bool:
    escaped = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(escaped, path) is not None


def validate_input_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
        return False, "URL_NOT_ALLOWED"
    if not parsed.path.startswith(ALLOWED_INPUT_PREFIX):
        return False, "URL_NOT_ALLOWED"
    if is_robots_disallowed(url):
        return False, "ROBOTS_DISALLOWED"
    return True, ""


def validate_discovered_product_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
        return False, "URL_NOT_ALLOWED"
    if not parsed.path.startswith(DISCOVERED_PRODUCT_PREFIX):
        return False, "URL_NOT_ALLOWED"
    if is_robots_disallowed(url):
        return False, "ROBOTS_DISALLOWED"
    return True, ""


def fetch_url(url: str, timeout: int) -> FetchResult:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
            return FetchResult(url=url, html=html, checked_at=checked_at)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP_{exc.code}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("TIMEOUT_READ: request timed out") from exc
    except URLError as exc:
        reason = str(exc.reason)
        if "unknown url type: https" in reason:
            return fetch_url_with_curl(url, timeout, checked_at)
        code = "TIMEOUT_CONNECT" if "timed out" in reason.lower() else "UNKNOWN"
        raise RuntimeError(f"{code}: {reason}") from exc


def fetch_url_with_curl(url: str, timeout: int, checked_at: str) -> FetchResult:
    marker = "__BOEXIO_HTTP_STATUS__:"
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-L",
            "--max-time",
            str(timeout),
            "-A",
            USER_AGENT,
            "-w",
            f"\n{marker}%{{http_code}}",
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    if result.returncode != 0:
        stderr = normalize_space(result.stderr)
        code = "TIMEOUT_READ" if "timed out" in stderr.lower() else "UNKNOWN"
        raise RuntimeError(f"{code}: curl failed: {stderr}")
    if marker not in result.stdout:
        raise RuntimeError("UNKNOWN: curl output did not include HTTP status")
    body, status_text = result.stdout.rsplit(marker, 1)
    status = int(status_text.strip() or "0")
    if status >= 400:
        raise RuntimeError(f"HTTP_{status}: curl returned HTTP {status}")
    return FetchResult(url=url, html=body.rstrip("\n"), checked_at=checked_at)


def parse_html(html: str) -> TextAndLinkParser:
    parser = TextAndLinkParser()
    parser.feed(html)
    return parser


def select_representative_product(category_url: str, html: str) -> str | None:
    parser = parse_html(html)
    product_links: list[str] = []
    for href, label in parser.links:
        full_url = urljoin(category_url, href)
        valid, _ = validate_discovered_product_url(full_url)
        if not valid:
            continue
        product_links.append(full_url)
        if "Catskills" in label:
            return full_url
    return product_links[0] if product_links else None


def extract_title_parts(html: str) -> tuple[str, str]:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return "", ""
    title = normalize_space(re.sub(r"<[^>]+>", "", match.group(1)))
    parts = [part.strip() for part in title.split("|")]
    product_name = parts[0] if parts else ""
    series = parts[2] if len(parts) >= 3 else ""
    return product_name, series


def value_after(texts: list[str], label: str) -> str:
    for index, text in enumerate(texts):
        if text == label:
            for next_text in texts[index + 1 :]:
                if next_text:
                    return next_text
    return ""


def selected_value(texts: list[str], label: str) -> str:
    prefix = f"{label} "
    for text in texts:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return value_after(texts, label)


def price_values_after(texts: list[str], label: str) -> list[str]:
    prices: list[str] = []
    for index, text in enumerate(texts):
        if text == label:
            for next_text in texts[index + 1 : index + 5]:
                if "¥" in next_text:
                    prices.append(next_text)
            break
    return prices


def first_matching_link(base_url: str, links: Iterable[tuple[str, str]], label: str) -> str:
    for href, text in links:
        if label in text:
            full_url = urljoin(base_url, href)
            if not is_robots_disallowed(full_url):
                return full_url
    return ""


def first_og_image(html: str) -> str:
    patterns = (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1))
    return ""


def escaped_json_value(html: str, key: str) -> str:
    match = re.search(rf'\\"{re.escape(key)}\\":\\"([^\\"]*)\\"', html)
    return unescape(match.group(1)) if match else ""


def escaped_json_number(html: str, key: str) -> str:
    match = re.search(rf'\\"{re.escape(key)}\\":([0-9]+)', html)
    return match.group(1) if match else ""


def selected_option_id(html: str, attribute_id: str) -> str:
    selected_options = re.search(r'\\"selectedOptions\\":\{([^}]*)\}', html)
    if not selected_options:
        return ""
    match = re.search(rf'\\"{re.escape(attribute_id)}\\":\\"([^\\"]+)\\"', selected_options.group(1))
    return match.group(1) if match else ""


def option_name_for_id(html: str, option_id: str) -> str:
    if not option_id:
        return ""
    match = re.search(
        rf'\\"id\\":\\"{re.escape(option_id)}\\".*?\\"name\\":\\"([^\\"]+)\\"',
        html,
        flags=re.DOTALL,
    )
    return unescape(match.group(1)) if match else ""


def extract_material(texts: list[str]) -> str:
    labels = {"背面", "フレーム", "座面", "サスペンション", "ファブリック裏地", "Upholstery composition"}
    parts: list[str] = []
    for index, text in enumerate(texts):
        if text in labels and index + 1 < len(texts):
            parts.append(f"{text}: {texts[index + 1]}")
    return " / ".join(parts[:6])


def parse_product(product: FetchResult, raw_ref: str, run_id: str) -> dict[str, str]:
    parser = parse_html(product.html)
    product_name, series = extract_title_parts(product.html)
    prices = price_values_after(parser.texts, "希望小売価格")
    list_price = prices[0] if prices else ""
    display_price = prices[1] if len(prices) > 1 else list_price
    variant_url_key = escaped_json_value(product.html, "variantUrlKey")
    sku = escaped_json_value(product.html, "variantKey")
    json_price = escaped_json_number(product.html, "currentPrice")
    selected_leg_id = selected_option_id(product.html, "vaMaterialLeg")
    selected_upholstery_id = selected_option_id(product.html, "vaMaterialUpholstery")

    return {
        "run_id": run_id,
        "source_url": product.url,
        "source_checked_at": product.checked_at,
        "scrape_status": "success",
        "scrape_error_code": "",
        "scrape_error_message": "",
        "brand": "BoConcept",
        "series": series,
        "product_name": product_name,
        "base_item_number": value_after(parser.texts, "アイテム番号"),
        "variant_id": variant_url_key,
        "sku": sku,
        "item_number": value_after(parser.texts, "アイテム番号"),
        "selected_size": "",
        "selected_upholstery": option_name_for_id(product.html, selected_upholstery_id)
        or selected_value(parser.texts, "張地"),
        "selected_leg": option_name_for_id(product.html, selected_leg_id) or selected_value(parser.texts, "脚"),
        "width_cm": value_after(parser.texts, "幅"),
        "depth_cm": value_after(parser.texts, "奥行"),
        "height_cm": value_after(parser.texts, "高さ"),
        "weight_kg": value_after(parser.texts, "重さ"),
        "material": extract_material(parser.texts),
        "list_price": list_price,
        "display_price": display_price,
        "canonical_price": display_price,
        "price_from": "dom_text" if display_price else "embedded_json" if json_price else "",
        "currency": "JPY" if display_price else "",
        "tax_type": "tax_included" if display_price else "",
        "image_url": first_og_image(product.html),
        "pdf_url": first_matching_link(product.url, parser.links, "製品データシート"),
        "raw_data_ref": raw_ref,
    }


def failed_row(run_id: str, url: str, code: str, message: str) -> dict[str, str]:
    row = {column: "" for column in CSV_COLUMNS}
    row.update(
        {
            "run_id": run_id,
            "source_url": url,
            "source_checked_at": datetime.now(timezone.utc).isoformat(),
            "scrape_status": "failed",
            "scrape_error_code": code,
            "scrape_error_message": message,
        }
    )
    return row


def split_error(error: Exception) -> tuple[str, str]:
    message = str(error)
    if ":" in message:
        code, detail = message.split(":", 1)
        return code.strip(), detail.strip()
    return "UNKNOWN", message


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commit_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) / "runs" / run_id
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    logs: list[str] = []
    rows: list[dict[str, str]] = []
    target_urls = read_target_urls(Path(args.targets))

    for target_url in target_urls[:1]:
        valid, error_code = validate_input_url(target_url)
        if not valid:
            rows.append(failed_row(run_id, target_url, error_code, "input URL is not allowed"))
            continue
        try:
            category = fetch_url(target_url, args.timeout)
            category_raw = raw_dir / "category.html"
            category_raw.write_text(category.html, encoding="utf-8")
            product_url = select_representative_product(target_url, category.html)
            if not product_url:
                rows.append(failed_row(run_id, target_url, "SELECTOR_MISS", "product URL was not found"))
                continue

            product = fetch_url(product_url, args.timeout)
            product_raw = raw_dir / "product.html"
            product_raw.write_text(product.html, encoding="utf-8")
            rows.append(parse_product(product, "raw/product.html", run_id))
            logs.append(f"selected_product_url={product_url}")
        except Exception as exc:
            code, detail = split_error(exc)
            rows.append(failed_row(run_id, target_url, code, detail))
            logs.append(f"failed_url={target_url} code={code} detail={detail}")

    csv_path = output_dir / "products_poc.csv"
    log_path = output_dir / "scrape_log.txt"
    metadata_path = output_dir / "run_metadata.json"
    write_csv(csv_path, rows)
    log_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    success_count = sum(1 for row in rows if row["scrape_status"] == "success")
    failure_count = sum(1 for row in rows if row["scrape_status"] == "failed")
    run_status = "success" if success_count and not failure_count else "partial_success" if success_count else "failed"
    output_files = [str(csv_path), str(log_path)]
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "commit_sha": commit_sha(),
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "target_urls": target_urls,
        "output_files": output_files,
        "output_file_checksums": {str(path): sha256_file(Path(path)) for path in output_files},
        "run_status": run_status,
        "success_count": success_count,
        "failure_count": failure_count,
        "notes": [
            "Phase 1 PoC: category URL is allowed input; discovered product URL under /ja-jp/p/ is fetched for product detail inspection."
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if success_count else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BoExio Phase 1 product PoC.")
    parser.add_argument("--targets", default="config/target_urls.txt")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--run-id", default="")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
