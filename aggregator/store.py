"""The Operations Record: one SQLite file, and the only module that contains SQL.

Write API  - used by producers (the synthetic example device today, the real feed later).
Read API   - every read takes ``as_of`` and returns only what the Record knew by then.

Rows are append-only. A correction is ``supersede()``, which adds a new entry.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from utils import Entry, LINK_STATUSES, LINK_TYPES

SCHEMA_VERSION = "0.1"
_SCHEMA = Path(__file__).with_name("schema.sql")

INCIDENT_LABELS = ("recovery_action", "confirmed_cause", "certification")
_LABEL_COLUMNS = {
    "recovery_action": ("recovery_action", "recovery_known_at"),
    "confirmed_cause": ("confirmed_cause", "cause_known_at"),
    "certification": ("certification", "certification_known_at"),
}


@dataclass(frozen=True)
class StoredEntry:
    """An entry as read back from the Record."""

    id: int
    source: str
    record_class: str
    kind: str
    type: str
    element: str
    t_start: int
    t_end: Optional[int]
    known_at: int
    payload: dict[str, Any]
    raw_ref: str
    producer: str
    producer_version: str
    review_status: str
    supersedes: Optional[int]


@dataclass(frozen=True)
class IncidentView:
    """An incident as the Record knew it at one moment. Unknown labels are None."""

    id: int
    title: str
    element: str
    t_start: int
    t_end: Optional[int]
    known_at: int
    status: str  # open | mitigated | closed | unresolved
    recovery_action: Optional[str]
    confirmed_cause: Optional[str]
    certification: Optional[str]


@dataclass(frozen=True)
class LinkView:
    id: int
    src_entry_id: int
    dst_entry_id: int
    link_type: str
    relation: str
    status: str
    rationale: str
    known_at: int


_ENTRY_COLS = (
    "e.id, e.source, e.record_class, e.kind, e.type, el.name, e.t_start, e.t_end, "
    "e.known_at, e.payload, e.raw_ref, e.producer, e.producer_version, e.review_status, e.supersedes"
)
# An entry is hidden once a correction to it is known.
_NOT_SUPERSEDED = (
    "NOT EXISTS (SELECT 1 FROM entry s WHERE s.supersedes = e.id AND s.known_at <= :as_of)"
)


def _entry(row: Sequence[Any]) -> StoredEntry:
    return StoredEntry(
        id=row[0], source=row[1], record_class=row[2], kind=row[3], type=row[4],
        element=row[5], t_start=row[6], t_end=row[7], known_at=row[8],
        payload=json.loads(row[9]), raw_ref=row[10], producer=row[11],
        producer_version=row[12], review_status=row[13], supersedes=row[14],
    )


class RecordStore:
    def __init__(self, conn: sqlite3.Connection, path: Path):
        self._db = conn
        self.path = path
        self._element_ids: dict[str, int] = {}

    # ------------------------------------------------------------------ open
    @classmethod
    def create(cls, path: str | Path, meta: Optional[dict[str, str]] = None) -> "RecordStore":
        path = Path(path)
        if path.exists():
            raise FileExistsError(f"{path} already exists; the Record is never overwritten in place")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript(_SCHEMA.read_text())
        store = cls(conn, path)
        store.set_meta("schema_version", SCHEMA_VERSION)
        for k, v in (meta or {}).items():
            store.set_meta(k, v)
        return store

    @classmethod
    def open(cls, path: str | Path, readonly: bool = True) -> "RecordStore":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"no Record at {path}; build one with `orchestra synth`")
        uri = f"file:{path}?mode=ro" if readonly else f"file:{path}?mode=rw"
        return cls(sqlite3.connect(uri, uri=True), path)

    def commit(self) -> None:
        self._db.commit()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    # ----------------------------------------------------------------- write
    def set_meta(self, key: str, value: str) -> None:
        self._db.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, str(value)))

    def add_element(self, name: str, kind: str, parent: Optional[str] = None) -> int:
        parent_id = self._eid(parent) if parent else None
        cur = self._db.execute(
            "INSERT INTO element (name, kind, parent_id) VALUES (?, ?, ?)", (name, kind, parent_id)
        )
        self._element_ids[name] = cur.lastrowid
        return cur.lastrowid

    def relate(self, element: str, related: str, relation: str) -> None:
        self._db.execute(
            "INSERT INTO element_relation (element_id, related_id, relation) VALUES (?, ?, ?)",
            (self._eid(element), self._eid(related), relation),
        )

    def add_entry(self, entry: Entry, supersedes: Optional[int] = None) -> int:
        cur = self._db.execute(
            "INSERT INTO entry (source, record_class, kind, type, element_id, t_start, t_end, "
            "known_at, payload, raw_ref, producer, producer_version, review_status, supersedes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.source, entry.record_class, entry.kind, entry.type, self._eid(entry.element),
                entry.t_start, entry.t_end, entry.known_at,
                json.dumps(entry.payload, sort_keys=True), entry.raw_ref, entry.producer,
                entry.producer_version, entry.review_status, supersedes,
            ),
        )
        return cur.lastrowid

    def add_entries(self, entries: Iterable[Entry]) -> list[int]:
        return [self.add_entry(e) for e in entries]

    def supersede(self, old_id: int, entry: Entry) -> int:
        """Record a correction: a new entry that replaces ``old_id`` from its known_at on."""
        if self._db.execute("SELECT 1 FROM entry WHERE id = ?", (old_id,)).fetchone() is None:
            raise KeyError(f"no entry {old_id}")
        return self.add_entry(entry, supersedes=old_id)

    def add_link(self, src_entry_id: int, dst_entry_id: int, link_type: str, relation: str,
                 known_at: int, producer: str, producer_version: str = "",
                 status: str = "proposed", rationale: str = "") -> int:
        if link_type not in LINK_TYPES:
            raise ValueError(f"link_type {link_type!r} not in {LINK_TYPES}")
        if status not in LINK_STATUSES:
            raise ValueError(f"status {status!r} not in {LINK_STATUSES}")
        cur = self._db.execute(
            "INSERT INTO link (src_entry_id, dst_entry_id, link_type, relation, status, rationale, "
            "known_at, producer, producer_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_entry_id, dst_entry_id, link_type, relation, status, rationale, known_at,
             producer, producer_version),
        )
        return cur.lastrowid

    def open_incident(self, title: str, element: str, t_start: int, known_at: int) -> int:
        cur = self._db.execute(
            "INSERT INTO incident (title, element_id, t_start, known_at) VALUES (?, ?, ?, ?)",
            (title, self._eid(element), t_start, known_at),
        )
        return cur.lastrowid

    def _set_once(self, incident_id: int, values: dict[str, Any]) -> None:
        cols = list(values)
        row = self._db.execute(
            f"SELECT {', '.join(cols)} FROM incident WHERE id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no incident {incident_id}")
        if any(v is not None for v in row):
            raise ValueError(f"incident {incident_id}: {cols} already set; rows are append-only")
        self._db.execute(
            f"UPDATE incident SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
            (*values.values(), incident_id),
        )

    def set_incident_end(self, incident_id: int, t_end: int) -> None:
        self._set_once(incident_id, {"t_end": t_end})

    def label_incident(self, incident_id: int, label: str, value: str, known_at: int) -> None:
        if label not in INCIDENT_LABELS:
            raise ValueError(f"label {label!r} not in {INCIDENT_LABELS}")
        col, known_col = _LABEL_COLUMNS[label]
        self._set_once(incident_id, {col: value, known_col: known_at})

    def close_incident(self, incident_id: int, final_status: str, known_at: int) -> None:
        self._set_once(incident_id, {"final_status": final_status, "closed_known_at": known_at})

    def attach(self, incident_id: int, entry_id: int, role: str, known_at: int) -> None:
        self._db.execute(
            "INSERT INTO incident_entry (incident_id, entry_id, role, known_at) VALUES (?, ?, ?, ?)",
            (incident_id, entry_id, role, known_at),
        )

    def log_query(self, session: str, tool: str, args: dict[str, Any], as_of: int,
                  result_ids: Sequence[int]) -> int:
        cur = self._db.execute(
            "INSERT INTO query_log (session, tool, args, as_of, result_ids) VALUES (?, ?, ?, ?, ?)",
            (session, tool, json.dumps(args, sort_keys=True), as_of, json.dumps(list(result_ids))),
        )
        return cur.lastrowid

    # ------------------------------------------------------------- elements
    def _eid(self, name: str) -> int:
        if name not in self._element_ids:
            row = self._db.execute("SELECT id FROM element WHERE name = ?", (name,)).fetchone()
            if row is None:
                raise KeyError(f"unknown element {name!r}")
            self._element_ids[name] = row[0]
        return self._element_ids[name]

    def has_element(self, name: str) -> bool:
        try:
            self._eid(name)
            return True
        except KeyError:
            return False

    def element_kind(self, name: str) -> str:
        return self._db.execute("SELECT kind FROM element WHERE id = ?", (self._eid(name),)).fetchone()[0]

    def elements(self, kind: Optional[str] = None) -> list[str]:
        if kind:
            rows = self._db.execute("SELECT name FROM element WHERE kind = ? ORDER BY id", (kind,))
        else:
            rows = self._db.execute("SELECT name FROM element ORDER BY id")
        return [r[0] for r in rows]

    def parent(self, name: str) -> Optional[str]:
        row = self._db.execute(
            "SELECT p.name FROM element c JOIN element p ON p.id = c.parent_id WHERE c.id = ?",
            (self._eid(name),),
        ).fetchone()
        return row[0] if row else None

    def ancestors(self, name: str) -> list[str]:
        out, cur = [], self.parent(name)
        while cur:
            out.append(cur)
            cur = self.parent(cur)
        return out

    def children(self, name: str) -> list[str]:
        rows = self._db.execute(
            "SELECT name FROM element WHERE parent_id = ? ORDER BY id", (self._eid(name),)
        )
        return [r[0] for r in rows]

    def subtree(self, name: str) -> list[str]:
        """The element and everything below it in the hierarchy."""
        out, todo = [], [name]
        while todo:
            cur = todo.pop()
            out.append(cur)
            todo.extend(self.children(cur))
        return out

    def related(self, name: str) -> list[tuple[str, str]]:
        """Service-side neighbours as (relation, element), in both directions."""
        eid = self._eid(name)
        rows = self._db.execute(
            "SELECT r.relation, e.name FROM element_relation r JOIN element e ON e.id = r.related_id "
            "WHERE r.element_id = ? "
            "UNION ALL "
            "SELECT r.relation || '_of', e.name FROM element_relation r JOIN element e ON e.id = r.element_id "
            "WHERE r.related_id = ? ORDER BY 1, 2",
            (eid, eid),
        )
        return [(r[0], r[1]) for r in rows]

    # --------------------------------------------------------------- entries
    def _entry_filter(self, as_of: int, elements=None, t0=None, t1=None, types=None, kinds=None,
                      record_classes=None, sources=None, text=None) -> tuple[str, dict[str, Any]]:
        where = ["e.known_at <= :as_of", _NOT_SUPERSEDED]
        params: dict[str, Any] = {"as_of": as_of}

        def _in(col: str, key: str, values: Sequence[Any]) -> None:
            names = []
            for i, v in enumerate(values):
                params[f"{key}{i}"] = v
                names.append(f":{key}{i}")
            where.append(f"{col} IN ({', '.join(names)})" if names else "1 = 0")

        if elements is not None:
            _in("e.element_id", "el", [self._eid(n) for n in elements])
        if types is not None:
            _in("e.type", "ty", list(types))
        if kinds is not None:
            _in("e.kind", "ki", list(kinds))
        if record_classes is not None:
            _in("e.record_class", "rc", list(record_classes))
        if sources is not None:
            _in("e.source", "so", list(sources))
        if t1 is not None:
            where.append("e.t_start <= :t1")
            params["t1"] = t1
        if t0 is not None:
            where.append("COALESCE(e.t_end, e.t_start) >= :t0")
            params["t0"] = t0
        if text:
            where.append("LOWER(e.payload) LIKE :text")
            params["text"] = f"%{text.lower()}%"
        return " AND ".join(where), params

    def entries(self, as_of: int, elements: Optional[Sequence[str]] = None,
                t0: Optional[int] = None, t1: Optional[int] = None,
                types: Optional[Sequence[str]] = None, kinds: Optional[Sequence[str]] = None,
                record_classes: Optional[Sequence[str]] = None,
                limit: Optional[int] = None, sources: Optional[Sequence[str]] = None,
                text: Optional[str] = None, offset: int = 0,
                newest_first: bool = False) -> list[StoredEntry]:
        """Entries known by ``as_of`` whose event time overlaps [t0, t1], oldest first.

        ``text`` matches anywhere in the payload, ignoring case.
        """
        where, params = self._entry_filter(as_of, elements, t0, t1, types, kinds,
                                           record_classes, sources, text)
        order = "e.t_start DESC, e.id DESC" if newest_first else "e.t_start, e.id"
        sql = (f"SELECT {_ENTRY_COLS} FROM entry e JOIN element el ON el.id = e.element_id "
               f"WHERE {where} ORDER BY {order}")
        if limit is not None:
            sql += " LIMIT :limit OFFSET :offset"
            params["limit"], params["offset"] = limit, offset
        return [_entry(r) for r in self._db.execute(sql, params)]

    def count_entries(self, as_of: int, elements=None, t0=None, t1=None, types=None, kinds=None,
                      record_classes=None, sources=None, text=None) -> int:
        where, params = self._entry_filter(as_of, elements, t0, t1, types, kinds,
                                           record_classes, sources, text)
        return self._db.execute(f"SELECT COUNT(*) FROM entry e WHERE {where}", params).fetchone()[0]

    def counts_by_type(self, as_of: int) -> list[tuple[str, str, str, str, int]]:
        """(class, source, type, kind, count) of the entries known by ``as_of``."""
        return [tuple(r) for r in self._db.execute(
            "SELECT e.record_class, e.source, e.type, e.kind, COUNT(*) FROM entry e "
            f"WHERE e.known_at <= :as_of AND {_NOT_SUPERSEDED} "
            "GROUP BY e.record_class, e.source, e.type, e.kind "
            "ORDER BY e.record_class, e.source, e.type", {"as_of": as_of})]

    def superseded_by(self, entry_id: int, as_of: int) -> Optional[int]:
        """The correction that replaced this entry, if one is known by ``as_of``."""
        row = self._db.execute(
            "SELECT id FROM entry WHERE supersedes = ? AND known_at <= ? ORDER BY known_at LIMIT 1",
            (entry_id, as_of)).fetchone()
        return row[0] if row else None

    def incidents_of_entry(self, entry_id: int, as_of: int) -> list[tuple[int, str]]:
        """(incident id, role) for the incidents this entry is attached to."""
        rows = self._db.execute(
            "SELECT ie.incident_id, ie.role FROM incident_entry ie JOIN incident i ON i.id = ie.incident_id "
            "WHERE ie.entry_id = ? AND ie.known_at <= ? AND i.known_at <= ? ORDER BY ie.incident_id",
            (entry_id, as_of, as_of))
        return [(r[0], r[1]) for r in rows]

    _INCIDENT_TIMES = ("known_at", "recovery_known_at", "cause_known_at",
                       "certification_known_at", "closed_known_at")

    def next_known_at(self, t: int, forward: bool = True, incident_id: Optional[int] = None) -> Optional[int]:
        """The nearest moment after (or before) ``t`` at which the Record learned something.

        Returns only the time, never what was learned. With ``incident_id``, only moments
        that concern that incident.
        """
        parts, params = [], []
        if incident_id is None:
            parts += ["SELECT known_at AS k FROM entry", "SELECT known_at FROM link",
                      "SELECT known_at FROM incident_entry"]
            parts += [f"SELECT {c} FROM incident" for c in self._INCIDENT_TIMES]
        else:
            parts += ["SELECT ie.known_at AS k FROM incident_entry ie WHERE ie.incident_id = ?",
                      "SELECT e.known_at FROM incident_entry ie JOIN entry e ON e.id = ie.entry_id "
                      "WHERE ie.incident_id = ?"]
            params += [incident_id, incident_id]
            for c in self._INCIDENT_TIMES:
                parts.append(f"SELECT {c} FROM incident WHERE id = ?")
                params.append(incident_id)
        op, agg = (">", "MIN") if forward else ("<", "MAX")
        row = self._db.execute(
            f"SELECT {agg}(k) FROM ({' UNION ALL '.join(parts)}) WHERE k IS NOT NULL AND k {op} ?",
            (*params, t)).fetchone()
        return row[0]

    def became_known(self, t_from: int, t_to: int, limit: int = 200) -> dict[str, Any]:
        """What the Record learned in (t_from, t_to]: entries, incident changes, links."""
        entries = [_entry(r) for r in self._db.execute(
            f"SELECT {_ENTRY_COLS} FROM entry e JOIN element el ON el.id = e.element_id "
            "WHERE e.known_at > ? AND e.known_at <= ? ORDER BY e.known_at, e.id LIMIT ?",
            (t_from, t_to, limit))]
        n_entries = self._db.execute(
            "SELECT COUNT(*) FROM entry WHERE known_at > ? AND known_at <= ?", (t_from, t_to)).fetchone()[0]
        n_links = self._db.execute(
            "SELECT COUNT(*) FROM link WHERE known_at > ? AND known_at <= ?", (t_from, t_to)).fetchone()[0]
        changes = []
        labels = {"known_at": "incident opened", "recovery_known_at": "recovery action recorded",
                  "cause_known_at": "cause confirmed", "certification_known_at": "certification recorded",
                  "closed_known_at": "incident closed"}
        for row in self._db.execute(
                f"SELECT id, title, {', '.join(self._INCIDENT_TIMES)} FROM incident ORDER BY id"):
            for col, t in zip(self._INCIDENT_TIMES, row[2:]):
                if t is not None and t_from < t <= t_to:
                    changes.append({"incident_id": row[0], "title": row[1], "what": labels[col], "t": t})
        changes.sort(key=lambda c: (c["t"], c["incident_id"]))
        return {"entries": entries, "n_entries": n_entries, "n_links": n_links, "incident_changes": changes}

    def get_entry(self, entry_id: int, as_of: int) -> Optional[StoredEntry]:
        row = self._db.execute(
            f"SELECT {_ENTRY_COLS} FROM entry e JOIN element el ON el.id = e.element_id "
            "WHERE e.id = :id AND e.known_at <= :as_of",
            {"id": entry_id, "as_of": as_of},
        ).fetchone()
        return _entry(row) if row else None

    def state_at(self, element: str, type: str, t: int, as_of: int) -> Optional[StoredEntry]:
        """The last 'state' entry of this type at or before ``t``, however old it is."""
        row = self._db.execute(
            f"SELECT {_ENTRY_COLS} FROM entry e JOIN element el ON el.id = e.element_id "
            f"WHERE e.element_id = :el AND e.type = :type AND e.kind = 'state' "
            f"AND e.t_start <= :t AND e.known_at <= :as_of AND {_NOT_SUPERSEDED} "
            "ORDER BY e.t_start DESC, e.id DESC LIMIT 1",
            {"el": self._eid(element), "type": type, "t": t, "as_of": as_of},
        ).fetchone()
        return _entry(row) if row else None

    def state_types(self, element: str, as_of: int) -> list[str]:
        rows = self._db.execute(
            "SELECT DISTINCT type FROM entry WHERE element_id = ? AND kind = 'state' "
            "AND known_at <= ? ORDER BY type", (self._eid(element), as_of))
        return [r[0] for r in rows]

    def links(self, entry_id: int, as_of: int) -> list[LinkView]:
        """Links touching an entry. Both ends must also be known by ``as_of``."""
        rows = self._db.execute(
            "SELECT l.id, l.src_entry_id, l.dst_entry_id, l.link_type, l.relation, l.status, "
            "l.rationale, l.known_at FROM link l "
            "JOIN entry a ON a.id = l.src_entry_id JOIN entry b ON b.id = l.dst_entry_id "
            "WHERE (l.src_entry_id = :id OR l.dst_entry_id = :id) AND l.known_at <= :as_of "
            "AND a.known_at <= :as_of AND b.known_at <= :as_of ORDER BY l.id",
            {"id": entry_id, "as_of": as_of},
        )
        return [LinkView(*r) for r in rows]

    # ------------------------------------------------------------- incidents
    def _incident_view(self, row: Sequence[Any], as_of: int) -> IncidentView:
        (iid, title, element, t_start, t_end, known_at, rec, rec_k, cause, cause_k,
         cert, cert_k, final, closed_k) = row

        def seen(value: Any, known: Optional[int]) -> Any:
            return value if known is not None and known <= as_of else None

        recovery = seen(rec, rec_k)
        if closed_k is not None and closed_k <= as_of:
            status = final
        elif recovery is not None:
            status = "mitigated"
        else:
            status = "open"
        return IncidentView(
            id=iid, title=title, element=element, t_start=t_start,
            t_end=t_end if t_end is not None and t_end <= as_of else None,
            known_at=known_at, status=status, recovery_action=recovery,
            confirmed_cause=seen(cause, cause_k), certification=seen(cert, cert_k),
        )

    _INCIDENT_SQL = (
        "SELECT i.id, i.title, el.name, i.t_start, i.t_end, i.known_at, i.recovery_action, "
        "i.recovery_known_at, i.confirmed_cause, i.cause_known_at, i.certification, "
        "i.certification_known_at, i.final_status, i.closed_known_at "
        "FROM incident i JOIN element el ON el.id = i.element_id "
    )

    def incidents(self, as_of: int, elements: Optional[Sequence[str]] = None) -> list[IncidentView]:
        """All incidents known by ``as_of`` (open and closed), oldest first."""
        sql = self._INCIDENT_SQL + "WHERE i.known_at <= ?"
        params: list[Any] = [as_of]
        if elements is not None:
            ids = [self._eid(n) for n in elements]
            sql += f" AND i.element_id IN ({', '.join('?' for _ in ids)})"
            params += ids
        sql += " ORDER BY i.t_start, i.id"
        return [self._incident_view(r, as_of) for r in self._db.execute(sql, params)]

    def incident(self, incident_id: int, as_of: int) -> Optional[IncidentView]:
        row = self._db.execute(
            self._INCIDENT_SQL + "WHERE i.id = ? AND i.known_at <= ?", (incident_id, as_of)
        ).fetchone()
        return self._incident_view(row, as_of) if row else None

    def incident_entries(self, incident_id: int, as_of: int) -> list[tuple[str, StoredEntry]]:
        """(role, entry) for the entries attached to an incident, oldest first."""
        rows = self._db.execute(
            f"SELECT ie.role, {_ENTRY_COLS} FROM incident_entry ie "
            "JOIN entry e ON e.id = ie.entry_id JOIN element el ON el.id = e.element_id "
            f"WHERE ie.incident_id = :iid AND ie.known_at <= :as_of AND e.known_at <= :as_of "
            f"AND {_NOT_SUPERSEDED} ORDER BY e.t_start, e.id",
            {"iid": incident_id, "as_of": as_of},
        )
        return [(r[0], _entry(r[1:])) for r in rows]

    # ----------------------------------------------------- following one incident
    def incident_frame(self, incident_id: int) -> Optional[dict[str, Any]]:
        """Which incident a replay follows: title, element and times only, whatever the moment.

        This is the replay's frame, not Record content at a moment: it names the problem
        being followed even before the Record has opened an incident for it.
        """
        row = self._db.execute(
            "SELECT i.id, i.title, el.name, i.t_start, i.known_at FROM incident i "
            "JOIN element el ON el.id = i.element_id WHERE i.id = ?", (incident_id,)).fetchone()
        if row is None:
            return None
        return {"id": row[0], "title": row[1], "element": row[2], "t_start": row[3], "opened_at": row[4]}

    def incident_entries_seen(self, incident_id: int, as_of: int) -> list[tuple[Optional[str], StoredEntry]]:
        """What a replay shows of an incident's entries at ``as_of``.

        Entries whose attachment is known are returned with their role. Before that, only
        the problem's symptoms are returned, with role None: they are what the crew is
        looking at, but nobody has linked them to an incident yet. Evidence an expert links
        later is not returned early; doing so would point at the answer.
        """
        rows = self._db.execute(
            f"SELECT CASE WHEN ie.known_at <= :as_of THEN ie.role END, {_ENTRY_COLS} "
            "FROM incident_entry ie JOIN entry e ON e.id = ie.entry_id "
            "JOIN element el ON el.id = e.element_id "
            f"WHERE ie.incident_id = :iid AND e.known_at <= :as_of AND {_NOT_SUPERSEDED} "
            "AND (ie.known_at <= :as_of OR ie.role = 'symptom') "
            "ORDER BY e.t_start, e.id", {"iid": incident_id, "as_of": as_of})
        return [(r[0], _entry(r[1:])) for r in rows]

    def incident_step_times(self, incident_id: int) -> list[int]:
        """Every moment at which the Record learned something about this incident. Times only."""
        parts = ["SELECT ie.known_at AS k FROM incident_entry ie WHERE ie.incident_id = ?",
                 "SELECT e.known_at FROM incident_entry ie JOIN entry e ON e.id = ie.entry_id "
                 "WHERE ie.incident_id = ?"]
        params = [incident_id, incident_id]
        for c in self._INCIDENT_TIMES:
            parts.append(f"SELECT {c} FROM incident WHERE id = ?")
            params.append(incident_id)
        rows = self._db.execute(
            f"SELECT DISTINCT k FROM ({' UNION ALL '.join(parts)}) WHERE k IS NOT NULL ORDER BY k", params)
        return [r[0] for r in rows]

    # ------------------------------------------------- raw rows, for illustration
    _INCIDENT_PAIRS = (("recovery_action", "recovery_known_at"), ("confirmed_cause", "cause_known_at"),
                       ("certification", "certification_known_at"), ("final_status", "closed_known_at"))

    def _raw(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any]:
        cur = self._db.execute(sql, params)
        return {"columns": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}

    def _mask_incidents(self, table: dict[str, Any], as_of: int) -> dict[str, Any]:
        """Blank the incident columns that were not yet known at ``as_of``."""
        col = {name: i for i, name in enumerate(table["columns"])}
        for row in table["rows"]:
            for value, known in self._INCIDENT_PAIRS:
                if row[col[known]] is None or row[col[known]] > as_of:
                    row[col[value]] = row[col[known]] = None
            if row[col["t_end"]] is not None and row[col["t_end"]] > as_of:
                row[col["t_end"]] = None
        return table

    def table_counts(self, as_of: int) -> dict[str, int]:
        """Rows in each table that the Record held at ``as_of``."""
        one = lambda sql, *p: self._db.execute(sql, p).fetchone()[0]
        return {
            "element": one("SELECT COUNT(*) FROM element"),
            "element_relation": one("SELECT COUNT(*) FROM element_relation"),
            "entry": one("SELECT COUNT(*) FROM entry WHERE known_at <= ?", as_of),
            "link": one("SELECT COUNT(*) FROM link WHERE known_at <= ?", as_of),
            "incident": one("SELECT COUNT(*) FROM incident WHERE known_at <= ?", as_of),
            "incident_entry": one("SELECT COUNT(*) FROM incident_entry WHERE known_at <= ?", as_of),
            "query_log": one("SELECT COUNT(*) FROM query_log"),
            "meta": one("SELECT COUNT(*) FROM meta"),
        }

    def table_sample(self, table: str, as_of: int, limit: int = 6) -> dict[str, Any]:
        """A few raw rows of one table, as the Record held them at ``as_of``, chosen for variety."""
        queries = {
            "element": ("SELECT * FROM element WHERE id IN (SELECT MIN(id) FROM element GROUP BY kind) "
                        "ORDER BY id LIMIT ?", (limit,)),
            "element_relation": ("SELECT * FROM element_relation ORDER BY element_id, relation LIMIT ?", (limit,)),
            "entry": ("SELECT * FROM entry WHERE id IN (SELECT MIN(id) FROM entry WHERE known_at <= ? "
                      "GROUP BY source, kind) ORDER BY record_class, id LIMIT ?", (as_of, limit + 4)),
            "link": ("SELECT * FROM link WHERE id IN (SELECT MIN(id) FROM link WHERE known_at <= ? "
                     "GROUP BY link_type, relation) ORDER BY id LIMIT ?", (as_of, limit)),
            "incident": ("SELECT * FROM incident WHERE known_at <= ? ORDER BY id LIMIT ?", (as_of, limit)),
            "incident_entry": ("SELECT * FROM incident_entry WHERE known_at <= ? AND rowid IN "
                               "(SELECT MIN(rowid) FROM incident_entry WHERE known_at <= ? GROUP BY role) "
                               "ORDER BY incident_id, entry_id LIMIT ?", (as_of, as_of, limit + 2)),
            "query_log": ("SELECT * FROM query_log ORDER BY id LIMIT ?", (limit,)),
            "meta": ("SELECT * FROM meta WHERE key <> 'config' ORDER BY key LIMIT ?", (limit + 4,)),
        }
        if table not in queries:
            raise KeyError(f"unknown table {table!r}")
        out = self._raw(*queries[table])
        return self._mask_incidents(out, as_of) if table == "incident" else out

    def incident_rows(self, incident_id: int, as_of: int, limit: int = 8) -> dict[str, dict[str, Any]]:
        """The raw rows, table by table, that together make up one incident at ``as_of``."""
        inc = self._mask_incidents(self._raw(
            "SELECT * FROM incident WHERE id = ? AND known_at <= ?", (incident_id, as_of)), as_of)
        attached = self._raw(
            "SELECT ie.* FROM incident_entry ie JOIN entry e ON e.id = ie.entry_id "
            "WHERE ie.incident_id = ? AND ie.known_at <= ? AND e.known_at <= ? "
            "ORDER BY e.t_start, e.id LIMIT ?", (incident_id, as_of, as_of, limit))
        ids = [r[1] for r in attached["rows"]] or [-1]
        marks = ", ".join("?" for _ in ids)
        entries = self._raw(f"SELECT * FROM entry WHERE id IN ({marks}) ORDER BY t_start, id", ids)
        links = self._raw(
            f"SELECT * FROM link WHERE known_at <= ? AND src_entry_id IN ({marks}) "
            f"AND dst_entry_id IN (SELECT entry_id FROM incident_entry WHERE incident_id = ? AND known_at <= ?) "
            "ORDER BY id", (as_of, *ids, incident_id, as_of))
        col = {name: i for i, name in enumerate(entries["columns"])}
        el_ids = sorted({r[col["element_id"]] for r in entries["rows"]}
                        | {r[inc["columns"].index("element_id")] for r in inc["rows"]}) or [-1]
        elements = self._raw(
            f"SELECT * FROM element WHERE id IN ({', '.join('?' for _ in el_ids)}) ORDER BY id", el_ids)
        return {"incident": inc, "incident_entry": attached, "entry": entries, "link": links, "element": elements}

    # ------------------------------------------------------------ inspection
    def meta(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT key, value FROM meta ORDER BY key"))

    def latest_known_at(self) -> int:
        """The latest known-at time anywhere in the Record ('as of the end')."""
        row = self._db.execute(
            "SELECT MAX(m) FROM (SELECT MAX(known_at) AS m FROM entry "
            "UNION ALL SELECT MAX(known_at) FROM link "
            "UNION ALL SELECT MAX(known_at) FROM incident_entry "
            "UNION ALL SELECT MAX(closed_known_at) FROM incident "
            "UNION ALL SELECT MAX(cause_known_at) FROM incident "
            "UNION ALL SELECT MAX(recovery_known_at) FROM incident "
            "UNION ALL SELECT MAX(certification_known_at) FROM incident)"
        ).fetchone()
        return row[0] or 0

    def time_span(self) -> tuple[int, int]:
        row = self._db.execute("SELECT MIN(t_start), MAX(COALESCE(t_end, t_start)) FROM entry").fetchone()
        return (row[0] or 0, row[1] or 0)

    def counts(self) -> dict[str, Any]:
        tables = {t: self._db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("element", "element_relation", "entry", "link", "incident",
                            "incident_entry", "query_log")}
        by_type = [tuple(r) for r in self._db.execute(
            "SELECT record_class, source, type, kind, COUNT(*) FROM entry "
            "GROUP BY record_class, source, type, kind ORDER BY record_class, source, type")]
        by_kind = dict(self._db.execute("SELECT kind, COUNT(*) FROM element GROUP BY kind ORDER BY kind"))
        return {"tables": tables, "entries_by_type": by_type, "elements_by_kind": by_kind}

    def content_hash(self) -> str:
        """A hash of the Record's content, independent of SQLite's file layout."""
        import hashlib

        h = hashlib.sha256()
        for table in ("meta", "element", "element_relation", "entry", "link", "incident", "incident_entry"):
            for row in sorted(repr(r) for r in self._db.execute(f"SELECT * FROM {table}")):
                h.update(row.encode())
        return h.hexdigest()
