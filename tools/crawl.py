"""
Open every page reachable from the menu for each demo user (in-process, no server needed) and report
server errors (500) and links that lead to "forbidden" pages.   python tools/crawl.py [usernames...]
"""
import os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django; django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = ["*"]
from django.test import Client
from django.contrib.auth import get_user_model
from urllib.parse import urlsplit
import html as htmlmod

ROLES = sys.argv[1:] or ["demo.admin", "demo.director", "demo.accounts", "demo.engineer", "demo.coordinator"]
SKIP = ("/accounts/logout", "/static/", "/media/", "/tf-admin")
results = {}
for uname in ROLES:
    user = get_user_model().objects.get(username=uname)
    c = Client(raise_request_exception=False)
    c.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    seen, queue, errors, forbidden, pattern_count = set(), collections.deque(["/"]), [], [], collections.Counter()
    parent = {}
    while queue and len(seen) < 900:
        url = queue.popleft()
        if url in seen: continue
        seen.add(url)
        try:
            r = c.get(url)
        except Exception as e:
            errors.append((url, "EXC " + repr(e)[:300])); continue
        if r.status_code >= 500:
            errors.append((url, r.status_code)); continue
        if r.status_code == 403: forbidden.append(url + "  <- " + str(parent.get(url)))
        ctype = r.get("Content-Type", "")
        if r.status_code != 200 or "text/html" not in ctype: continue
        body = r.content.decode("utf-8", "replace")
        for href in re.findall(r'href="([^"#]+)"', body):
            href = htmlmod.unescape(href)
            if href.startswith("http") or href.startswith("mailto") or href.startswith("tel") or href.startswith("javascript"): continue
            if not href.startswith("/"): continue
            if any(href.startswith(s) for s in SKIP): continue
            path = urlsplit(href).path
            key = re.sub(r"\d+", "N", path) + ("?" if "?" in href else "")
            if pattern_count[key] >= 4: continue
            pattern_count[key] += 1
            parent.setdefault(href, url); queue.append(href)
        for src in re.findall(r'data-chart="([^"]+)"', body):
            queue.append(htmlmod.unescape(src))
    results[uname] = (len(seen), errors, forbidden)
    print(f"{uname}: {len(seen)} pages, {len(errors)} errors, {len(forbidden)} forbidden", flush=True)
    for e in errors[:40]: print("   ERR", e)
    for f in forbidden[:10]: print("   403", f)
