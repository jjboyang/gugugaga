"""Collect a small number of real pictures from a public source page."""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException
from io import BytesIO
from ipaddress import ip_address
import re
import socket
import ssl
from urllib.parse import quote, urljoin

from PIL import Image, ImageOps, UnidentifiedImageError

from pet.exploration import read_url, website_domain


PICTURE_TIMEOUT = 9
MAX_DOWNLOAD = 4 * 1024 * 1024
MARKDOWN_IMAGE = re.compile(r'!\[([^\]\n]*)\]\(<?([^\s)>]+)>?(?:\s+["\'][^\n]*?["\'])?\s*\)')


@dataclass(frozen=True)
class PictureCandidate:
    url: str
    kind: str
    description: str
    jpeg: bytes


class PageImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and (values.get("property") or values.get("name")) in {"og:image", "twitter:image"}:
            self.items.append((values.get("content") or "", "cover", "来源页封面"))
        elif tag == "video" and values.get("poster"):
            self.items.append((values["poster"], "cover", "视频封面"))
        elif tag == "img":
            self.items.append((values.get("data-src") or values.get("src") or "", "figure", values.get("alt") or ""))


def _public_image_url(value, page_url):
    try:
        url = urljoin(page_url, unescape(value))
    except ValueError:
        return ""
    parts = read_url(url)
    if not parts or not website_domain(url):
        return ""
    if parts.scheme == "http" and parts.port in (None, 80):
        parts = parts._replace(scheme="https", netloc=parts.hostname)
    if parts.scheme != "https" or parts.port not in (None, 443):
        return ""
    return parts._replace(fragment="").geturl()


class _PublicHTTPSConnection(HTTPConnection):
    """Connect to a resolved public IP while verifying TLS for the original host."""

    default_port = 443

    def connect(self):
        for family, socktype, proto, _, address in socket.getaddrinfo(
                self.host, self.port, type=socket.SOCK_STREAM):
            ip = ip_address(address[0])
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                continue
            stream = socket.socket(family, socktype, proto)
            stream.settimeout(self.timeout)
            try:
                stream.connect(address)
                self.sock = ssl.create_default_context().wrap_socket(stream, server_hostname=self.host)
                return
            except OSError:
                stream.close()
        raise OSError("No reachable public HTTPS address")


def _download(url, *, limit, content_type, partial=False):
    parts = read_url(url)
    host = parts.hostname.encode("idna").decode("ascii")
    connection = _PublicHTTPSConnection(host, 443, timeout=3)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    try:
        accept = "image/*" if content_type == "image/" else content_type
        connection.request("GET", quote(path, safe="/%?&=:+,;@!$'()*[]-._~"), headers={
            "User-Agent": "DaFeiYu-Exploration/1.0", "Accept": accept,
        })
        response = connection.getresponse()
        if response.status != 200 or not response.getheader("Content-Type", "").lower().startswith(content_type):
            return b""
        data = response.read(limit if partial else limit + 1)
        return data if len(data) <= limit else b""
    except (OSError, HTTPException, UnicodeError, ValueError):
        return b""
    finally:
        connection.close()


def _memory_jpeg(data):
    if not data:
        return b""
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP", "GIF", "AVIF")) as source:
            width, height = source.size
            if width < 220 or height < 140 or width * height > 20_000_000:
                return b""
            picture = ImageOps.exif_transpose(source)
            picture.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            picture = picture.convert("RGBA")
            flattened = Image.new("RGB", picture.size, "white")
            flattened.paste(picture, mask=picture.getchannel("A"))
            output = BytesIO()
            flattened.save(output, format="JPEG", quality=87, optimize=True)
            return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError, UnidentifiedImageError, KeyError):
        return b""


def collect_pictures(page, page_url, cancelled):
    """Read at most two usable illustrations, including public video covers."""
    if cancelled.is_set():
        return []
    parser = PageImages()
    parser.feed(page)
    items = [(match[2], "figure", match[1]) for match in MARKDOWN_IMAGE.finditer(page)]
    items.extend(parser.items)
    parts = read_url(page_url)
    if (not items and parts and parts.hostname == "www.bilibili.com"
            and parts.path.startswith("/video/") and _public_image_url(page_url, page_url)):
        raw = _download(page_url, limit=256_000, content_type="text/html", partial=True)
        parser = PageImages()
        parser.feed(raw.decode("utf-8", errors="replace"))
        items = [item for item in parser.items if item[1] == "cover"]
    pictures = []
    seen = set()
    for candidate, kind, description in items[:8]:
        if cancelled.is_set():
            break
        url = _public_image_url(candidate, page_url) if candidate else ""
        if not url or url in seen:
            continue
        seen.add(url)
        jpeg = _memory_jpeg(_download(url, limit=MAX_DOWNLOAD, content_type="image/"))
        if jpeg:
            pictures.append(PictureCandidate(url, kind, " ".join(description.split())[:100], jpeg))
        if len(pictures) == 2:
            break
    return pictures
