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
DB_VERSION = 2


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
    text = re.sub(r"^#{1,6}\s*", "# ", text, flags=re.M)          # headings become sections
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
    base = re.split(r"[\\/]", name)[-1]          # Windows or POSIX path, whatever OS we run on
    stem = os.path.splitext(base)[0]
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
            self._db.execute("PRAGMA user_version = 1")
            self._db.commit()
            v = 1
        if v < 2:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS rehearsals (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    script_id INTEGER,
                    at        REAL    NOT NULL,
                    seconds   INTEGER NOT NULL,
                    wpm       INTEGER NOT NULL,
                    fillers   INTEGER NOT NULL,
                    score     INTEGER NOT NULL,
                    data      TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_reh_script ON rehearsals(script_id, at DESC);
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

    def add_rehearsal(self, script_id, report):
        import json
        with self._lock:
            self._db.execute("INSERT INTO rehearsals(script_id, at, seconds, wpm, fillers, score, data) "
                             "VALUES (?,?,?,?,?,?,?)",
                             (int(script_id or 0), time.time(), int(report["seconds"]), int(report["wpm"]),
                              int(report["filler_count"]), int(report["score"]), json.dumps(report)))
            self._db.commit()

    def rehearsals(self, script_id, limit=10):
        with self._lock:
            rows = self._db.execute("SELECT at, seconds, wpm, fillers, score FROM rehearsals WHERE script_id = ? "
                                    "ORDER BY at DESC, id DESC LIMIT ?", (int(script_id or 0), int(limit))).fetchall()
        return [dict(r) for r in rows]

    def backup(self, folder, keep=7):
        """Consistent snapshot of the library (sqlite online backup), one per day, newest `keep` kept.
        Protects against the 'my scripts vanished after an update' failure users report elsewhere."""
        os.makedirs(folder, exist_ok=True)
        name = time.strftime("library-%Y%m%d.db")
        dest = os.path.join(folder, name)
        if not os.path.exists(dest):
            with self._lock:
                out = sqlite3.connect(dest)
                try:
                    self._db.backup(out)
                finally:
                    out.close()
        snaps = sorted(f for f in os.listdir(folder) if f.startswith("library-") and f.endswith(".db"))
        for old in snaps[:-keep]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        return dest

    def close(self):
        with self._lock:
            try:
                self._db.close()
            except Exception:
                pass


def safe_filename(title):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title).strip(" .")
    return (name or "Script")[:80]


def export_markdown(store, folder):
    """Write every script to `folder` as .md (unique names). Returns how many were written."""
    os.makedirs(folder, exist_ok=True)
    used, n = set(), 0
    for summary in store.list(limit=100000):
        s = store.get(summary["id"])
        if not s:
            continue
        base = safe_filename(s["title"])
        name, k = base, 2
        while name.lower() in used or os.path.exists(os.path.join(folder, name + ".md")):
            name = "%s (%d)" % (base, k)
            k += 1
        used.add(name.lower())
        with open(os.path.join(folder, name + ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(s["body"].rstrip() + "\n")
        n += 1
    return n
