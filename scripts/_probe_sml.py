#!/usr/bin/env python3
"""Quick probe — run directly to inspect SML page structure."""
import signal, sys, requests
from bs4 import BeautifulSoup

def _alarm(s, f):
    print("SIGALRM: timed out", file=sys.stderr); sys.exit(1)

signal.signal(signal.SIGALRM, _alarm)
signal.alarm(18)

HDR = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

print("Fetching /artists/ …")
r = requests.get("https://www.sonymusiclatin.com/artists/", timeout=(6, 12), headers=HDR, stream=True)
print(f"status={r.status_code}  final_url={r.url}")

raw = b""
for chunk in r.iter_content(65536):
    raw += chunk
    if len(raw) > 3_000_000:
        print("(truncated at 3 MB)")
        break
print(f"bytes_read={len(raw)}")

page = BeautifulSoup(raw, "lxml")
print("title:", page.title.string if page.title else "(none)")
print("articles:", len(page.find_all("article")))
print("h2:", [t.get_text(strip=True)[:60] for t in page.find_all("h2")][:8])
print("h3:", [t.get_text(strip=True)[:60] for t in page.find_all("h3")][:8])
links = [a["href"] for a in page.find_all("a", href=True)
         if "/artist" in a["href"] and a["href"] not in ("/", "/artists/")]
print("artist links[:12]:", links[:12])
next_l = page.find("a", rel="next")
print("rel=next link:", next_l)
