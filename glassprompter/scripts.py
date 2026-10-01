"""Script library (SQLite) and file import. Thread-safe: used by the UI thread and the remote server."""
import html
import io
import logging
import os
import re
import sqlite3
import threading
import time
import zipfile

from . import engine

log = logging.getLogger(__name__)

MAX_TITLE = 120
MAX_BODY = 1_000_000          # characters; ~150k words, far beyond any real script
MAX_DOCX_XML = 25_000_000     # bytes of document.xml we are willing to inflate (zip-bomb guard)
ALLOWED_EXT = (".txt", ".md", ".docx")
DB_VERSION = 1


class ValidationError(ValueError):
    pass


def clean(title, body):
    body = engine.normalize(body if isinstance(body, str) else "")
    if not body:
        raise ValidationError("The script is empty")
    if len(body) > MAX_BODY:
        raise ValidationError("The script is too long (1,000,000 characters max)")
    title = re.sub(r"\s+", " ", (title if isinstance(title, str) else "")).strip()
    title = title[:MAX_TITLE] or engine.title_from(body)
    return title, body


# ------------------------------------------------------------------ file import
def _decode_text(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def _strip_markdown(text):
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)              # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)           # links -> text
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"(?<![\w\[])\*(?!\s)|(?<!\s)\*(?![\w\]])", "", text)
    return text


def _docx_text(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML:
                raise ValidationError("That Word file is too large")
            xml = z.read(info).decode("utf-8", "ignore")
    except (zipfile.BadZipFile, KeyError):
        raise ValidationError("That doesn't look like a valid .docx file")
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        p = re.sub(r"<w:tab/>", " ", p)
        p = re.sub(r"<w:br[^>]*/>", "\n", p)
        out.append(html.unescape("".join(re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", p, flags=re.S))))
    return "\n".join(out)


def read_bytes(name, data):
    ext = os.path.splitext(name or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValidationError("Use a .txt, .md or .docx file")
    if ext == ".docx":
        return _docx_text(data)
    text = _decode_text(data)
    return _strip_markdown(text) if ext == ".md" else text


def read_file(path):
    with open(path, "rb") as f:
        return read_bytes(path, f.read())


def title_from_filename(name):
    stem = os.path.splitext(os.path.basename(name))[0]
    return re.sub(r"[_-]+", " ", stem).strip()[:MAX_TITLE] or "Imported script"


# ------------------------------------------------------------------ library
class ScriptStore:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    def _migrate(self):
        v = self._db.execute("PRAGMA user_version").fetchone()[0]
        if v < 1:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS scripts (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    title     TEXT    NOT NULL,
                    body      TEXT    NOT NULL,
                    words     INTEGER NOT NULL DEFAULT 0,
                    source    TEXT    UNIQUE,
                    created   REAL    NOT NULL,
                    updated   REAL    NOT NULL,
                    last_used REAL
                );
                CREATE INDEX IF NOT EXISTS idx_scripts_updated ON scripts(updated DESC);
            """)
            self._db.execute("PRAGMA user_version = %d" % DB_VERSION)
            self._db.commit()

    @staticmethod
    def _summary(row):
        return {"id": row["id"], "title": row["title"], "words": row["words"],
                "updated": row["updated"], "last_used": row["last_used"]}

    @staticmethod
    def _full(row):
        d = ScriptStore._summary(row)
        d["body"] = row["body"]
        d["created"] = row["created"]
        return d

    def count(self):
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM scripts").fetchone()[0]

    def list(self, query=None, limit=500):
        sql = "SELECT id, title, words, updated, last_used FROM scripts"
        args = []
        if query:
            sql += " WHERE title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\'"
            q = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args = [q, q]
        # most recently used/edited first; on a timestamp tie, a script you opened beats one you only saved
        sql += " ORDER BY COALESCE(last_used, updated) DESC, (last_used IS NULL), id DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            return [self._summary(r) for r in self._db.execute(sql, args).fetchall()]

    def get(self, script_id):
        with self._lock:
            r = self._db.execute("SELECT * FROM scripts WHERE id = ?", (int(script_id),)).fetchone()
        return self._full(r) if r else None

    def create(self, title, body, source=None):
        title, body = clean(title, body)
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO scripts(title, body, words, source, created, updated) VALUES (?,?,?,?,?,?)",
                (title, body, engine.count_words(body), source, now, now))
            self._db.commit()
            return self.get(cur.lastrowid)

    def update(self, script_id, title=None, body=None):
        cur = self.get(script_id)
        if not cur:
            return None
        title, body = clean(cur["title"] if title is None else title, cur["body"] if body is None else body)
        with self._lock:
            self._db.execute("UPDATE scripts SET title=?, body=?, words=?, updated=? WHERE id=?",
                             (title, body, engine.count_words(body), time.time(), int(script_id)))
            self._db.commit()
        return self.get(script_id)

    def delete(self, script_id):
        with self._lock:
            n = self._db.execute("DELETE FROM scripts WHERE id = ?", (int(script_id),)).rowcount
            self._db.commit()
        return n > 0

    def touch(self, script_id):
        with self._lock:
            self._db.execute("UPDATE scripts SET last_used=? WHERE id=?", (time.time(), int(script_id)))
            self._db.commit()

    def upsert_source(self, source, title, body):
        """Create or refresh the library entry that mirrors an external file."""
        with self._lock:
            r = self._db.execute("SELECT id FROM scripts WHERE source = ?", (source,)).fetchone()
        if r:
            return self.update(r["id"], title, body)
        return self.create(title, body, source=source)

    def close(self):
        with self._lock:
            try:
                self._db.close()
            except Exception:
                pass
