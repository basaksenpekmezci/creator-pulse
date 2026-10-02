"""
Dashboard sayfasının (templates/dashboard.html) yapısı için testler: tarih
aralığı açılır menüsü, sıralama düğmeleriyle aynı satırda durması ve kaldırılan
trend grafiğinden iz kalmaması. HTML standart kütüphaneyle ayrıştırılır.
"""
from html.parser import HTMLParser
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import dashboard
from app.routers.dashboard import DATE_RANGES

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboard.html"


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children, self.text = [], ""

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class TreeBuilder(HTMLParser):
    VOID = {"meta", "br", "img", "input", "link", "hr"}

    def __init__(self):
        super().__init__()
        self.root = Node("root", [], None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None:
            self.current = node.parent

    def handle_data(self, data):
        self.current.text += data


def page():
    builder = TreeBuilder()
    builder.feed(TEMPLATE.read_text(encoding="utf-8"))
    return builder.root


def by_id(root, element_id):
    return next(n for n in root.iter() if n.attrs.get("id") == element_id)


def test_date_range_is_a_single_select_with_all_ranges():
    root = page()
    select = by_id(root, "range-select")
    assert select.tag == "select"
    options = [n for n in select.iter() if n.tag == "option"]
    assert [o.attrs["value"] for o in options] == list(DATE_RANGES)
    assert [o.text.strip() for o in options] == [
        "Son 1 ay", "Son 2 ay", "Son 3 ay", "Son 6 ay", "Tümü",
    ]
    # Eski yan yana tarih butonları kalmamalı.
    assert not [n for n in root.iter() if "range-btn" in n.classes]


def test_select_defaults_to_all_like_the_api():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "let currentRange = 'all';" in source
    assert "rangeSelect.value = currentRange;" in source


def test_range_select_and_sort_buttons_share_one_row_with_divider():
    root = page()
    row = by_id(root, "controls")
    select = by_id(root, "range-select")
    divider = by_id(root, "sort-divider")
    sort_group = by_id(root, "sort-controls")
    for node in (select, divider, sort_group):
        assert row in node.ancestors()

    order = [n for n in row.children if n in (select, divider, sort_group)]
    assert order == [select, divider, sort_group]
    assert "divider" in divider.classes

    sorts = [n.attrs["data-sort"] for n in sort_group.iter() if "data-sort" in n.attrs]
    assert sorts == ["views", "likes", "comments", "total", "newest"]


def test_trend_chart_is_removed():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "Zaman içindeki trend" not in source
    assert "chart.js" not in source.lower()
    assert "/api/metrics/trend" not in source

    app = FastAPI()
    app.include_router(dashboard.router)
    assert TestClient(app).get("/api/metrics/trend").status_code == 404


def test_connect_buttons_and_youtube_form():
    root = page()
    bar = by_id(root, "connect-bar")
    yt_btn = by_id(root, "youtube-connect-btn")
    ig_btn = by_id(root, "instagram-connect-btn")
    assert bar in yt_btn.ancestors() and bar in ig_btn.ancestors()
    assert yt_btn.text.strip() == "YouTube bağla"
    assert ig_btn.text.strip() == "Instagram bağla"
    # Instagram OAuth akışını başlatır.
    assert ig_btn.tag == "a" and ig_btn.attrs["href"] == "/connect/instagram"
    # YouTube kanal adı dashboard'da girilir, terminal gerekmez.
    form = by_id(root, "youtube-form")
    assert by_id(root, "youtube-handle").attrs["name"] == "handle"
    assert form in by_id(root, "youtube-submit").ancestors()
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "api('/connect/youtube'" in source


def test_no_terminal_instructions_left():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "curl" not in source
    assert "/sync/youtube" not in source


def test_logout_button_posts_to_logout():
    root = page()
    button = by_id(root, "logout-btn")
    form = next(n for n in button.ancestors() if n.tag == "form")
    assert form.attrs["method"] == "post" and form.attrs["action"] == "/logout"
    assert by_id(root, "user-email") is not None


def test_dashboard_polls_while_syncing_and_handles_expired_session():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "res.status === 401" in source and "window.location.href = '/login'" in source
    assert "a.sync_status === 'syncing'" in source
    assert "setInterval(refreshAccounts" in source
