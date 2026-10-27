"""Fill and submit real HTML forms rendered by the CRM (like a browser would), via the Django test client."""
from bs4 import BeautifulSoup


def page(client, url, expect=200):
    r = client.get(url)
    assert r.status_code == expect, f"GET {url} -> {r.status_code}"
    return r


def form_fields(html, index=None, action=None):
    soup = BeautifulSoup(html, "lxml")
    forms = [f for f in soup.find_all("form") if (f.get("method") or "get").lower() == "post"
             and not any(x in (f.get("action") or "") for x in ("/accounts/logout", "/notifications/"))]
    if action is not None:
        forms = [f for f in forms if (f.get("action") or "") == action or (f.get("action") or "").endswith(action)]
    assert forms, f"No POST form found (action={action})"
    form = forms[index or 0]
    data = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or el.find_parent("template") is not None:
            continue
        if el.name == "input":
            t = (el.get("type") or "text").lower()
            if t in ("checkbox", "radio"):
                if el.has_attr("checked"):
                    data.setdefault(name, []).append(el.get("value", "on"))
            elif t in ("submit", "button", "file"):
                continue
            else:
                data[name] = el.get("value", "")
        elif el.name == "select":
            opts = el.find_all("option")
            chosen = [o.get("value", o.text) for o in opts if o.has_attr("selected")]
            if el.has_attr("multiple"):
                data[name] = chosen
            else:
                data[name] = chosen[0] if chosen else (opts[0].get("value", "") if opts else "")
        else:
            data[name] = el.text
    return form.get("action") or None, data


def submit(client, url, overrides=None, *, index=None, action=None, expect_redirect=True, files=None):
    r = page(client, url)
    form_action, data = form_fields(r.content.decode(), index=index, action=action)
    for k, v in (overrides or {}).items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    if files:
        data.update(files)
    target = form_action or url
    resp = client.post(target, data)
    if expect_redirect:
        assert resp.status_code == 302, f"POST {target} -> {resp.status_code}: {_errors(resp)}"
    return resp


def _errors(resp):
    try:
        soup = BeautifulSoup(resp.content.decode(), "lxml")
    except Exception:
        return ""
    msgs = [e.get_text(" ", strip=True) for e in soup.select(".invalid-feedback, .alert-danger, .errorlist")]
    return " | ".join(m for m in msgs if m)[:1500]


def select_value(html, name, text_contains):
    soup = BeautifulSoup(html, "lxml")
    sel = soup.find("select", attrs={"name": name})
    assert sel is not None, f"select {name} missing"
    for o in sel.find_all("option"):
        if text_contains.lower() in o.text.lower():
            return o.get("value")
    raise AssertionError(f"No option containing '{text_contains}' in {name}: {[o.text for o in sel.find_all('option')]}")
