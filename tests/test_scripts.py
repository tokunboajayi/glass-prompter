import io
import threading
import zipfile

import pytest

from glassprompter import paths, scripts


@pytest.fixture
def store():
    s = scripts.ScriptStore(paths.database_path())
    yield s
    s.close()


def make_docx(paragraphs):
    xml = ('<?xml version="1.0"?><w:document xmlns:w="w"><w:body>'
           + "".join("<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % p for p in paragraphs)
           + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_crud(store):
    s = store.create("", "Hello world, this is my script.\n[PAUSE]\nMore words")
    assert s["title"] == "Hello world, this is my script."
    assert s["words"] == 8
    s2 = store.update(s["id"], "Renamed", None)
    assert s2["title"] == "Renamed" and s2["body"] == s["body"]
    assert store.get(s["id"])["title"] == "Renamed"
    assert store.delete(s["id"]) is True
    assert store.get(s["id"]) is None
    assert store.delete(s["id"]) is False


def test_validation(store):
    with pytest.raises(scripts.ValidationError):
        store.create("t", "   \n  ")
    with pytest.raises(scripts.ValidationError):
        store.create("t", "x" * (scripts.MAX_BODY + 1))


def test_search_treats_wildcards_literally(store):
    store.create("Discount", "We give 100% effort")
    store.create("Other", "Nothing to see")
    assert [s["title"] for s in store.list("100%")] == ["Discount"]
    assert store.list("%") == [] or all("%" in store.get(s["id"])["body"] for s in store.list("%"))


def test_upsert_source_updates_same_entry(store):
    a = store.upsert_source("file:talk.txt", "talk", "Version one")
    b = store.upsert_source("file:talk.txt", "talk", "Version two")
    assert a["id"] == b["id"] and store.get(a["id"])["body"] == "Version two"
    assert store.count() == 1


def test_touch_orders_recent_first(store):
    a = store.create("A", "aaa bbb")
    b = store.create("B", "ccc ddd")
    store.touch(a["id"])
    assert store.list()[0]["id"] == a["id"]


def test_concurrent_writes_are_safe(store):
    errors = []

    def worker(n):
        try:
            for i in range(20):
                store.create("t%d-%d" % (n, i), "body %d %d" % (n, i))
        except Exception as ex:      # pragma: no cover
            errors.append(ex)
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and store.count() == 100


def test_read_docx_and_markdown_and_encodings():
    assert scripts.read_bytes("a.docx", make_docx(["First &amp; line", "Second"])) == "First & line\nSecond"
    md = scripts.read_bytes("a.md", b"# Title\n**Bold** and [a link](http://x.y) `code`")
    assert md == "# Title\nBold and a link code"
    assert scripts.read_bytes("a.txt", "caf\xe9".encode("cp1252")) == "caf\xe9"
    assert scripts.read_bytes("a.txt", "\ufeffhi".encode("utf-8")) == "hi"
    assert scripts.read_bytes("a.txt", "hi".encode("utf-16")) == "hi"


def test_bad_files_rejected():
    with pytest.raises(scripts.ValidationError):
        scripts.read_bytes("evil.exe", b"MZ")
    with pytest.raises(scripts.ValidationError):
        scripts.read_bytes("broken.docx", b"not a zip")


def test_title_from_filename():
    assert scripts.title_from_filename(r"C:\x\my_big-talk.docx") == "my big talk"
