"""
The Maid — Tree Architect

Designs a NEW folder tree from what the files actually are, instead of
relabelling the folders the user already has.

Pipeline (deterministic; the LLM is only used to *name* folders):

1. Profile    — every file gets a signal vector: words from its content
                (PDF / Word / Excel / text), its filename, and the meaningful
                folder names above it; plus its kind (document, photo, ...),
                its date (EXIF > filename > mtime) and GPS.
2. Units      — folders the user clearly curated (a named project / client /
                person folder) are kept whole as one unit. Generic dump
                folders (Downloads, Misc, New folder, DCIM, 2023 ...) are
                dissolved and their files are placed one by one.
3. Branches   — photos & videos are organised by real events (time gaps +
                place), named media folders become albums, music by album
                folder, installers/archives get their own branch, everything
                else is clustered by topic.
4. Cluster    — topic units are grouped with TF-IDF + spherical k-means
                (two levels max), tiny groups are folded into their nearest
                neighbour, near-duplicates are merged.
5. Name       — each group is named from its most distinctive words; if a
                local LLM is available it proposes a short human name per
                sibling set (one call per level, validated, keyword fallback).
6. Explain    — every folder carries a rationale (keywords + examples, or
                "kept your folder X together", or the event dates/place).
7. Model      — a compact profile of every leaf folder is saved so that new
                files can be routed to the best existing folder later
                ("keep it live").

The output is the legacy ``{"tree": [{category, subbuckets:[{subcategory,
files, rationale}], rationale}]}`` shape the API/UI already understand, plus a
``summary`` comparing the old structure to the proposed one.
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .extractor import extract_text
from .preferences import Preferences

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

CONTENT_CHARS = 1500          # text read per file for profiling
MAX_TERMS_PER_VECTOR = 40     # sparse vector cap
TOP_LEVEL_MAX_TOPICS = 10     # topic folders at the top (media/software extra)
SUB_MAX_TOPICS = 6
SPLIT_MIN_FILES = 24          # a topic folder bigger than this gets sub-folders
SPLIT_MIN_UNITS = 6
SMALL_BRANCH_FILES = 8        # branches smaller than this are not sub-divided
MIN_GROUP_FILES = 3           # smaller groups fold into a neighbour
MERGE_SIMILARITY = 0.55       # sibling groups more similar than this merge
UNIT_MAX_SHARE = 0.35         # a named folder holding more than this share of
UNIT_MAX_FILES_FLOOR = 60     #   all files (and > floor) is a container, not a unit
EVENT_GAP_HOURS = 36          # photo gap that starts a new event
EVENT_MAX_DAYS = 10           # longer "events" are really a stream: split by month
EVENT_MIN_PHOTOS = 4          # smaller events fold into "<month> other"
ROUTE_MIN_SIMILARITY = 0.12

TO_SORT = "To Sort"
SUGGESTED_AREAS = ["Work", "Personal", "Family", "Finance & Admin", "Studies", "Projects", "Hobbies"]

# ---------------------------------------------------------------------------
# File kinds
# ---------------------------------------------------------------------------

_KIND_EXT: Dict[str, set] = {
    "photo": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif",
              ".tif", ".tiff", ".raw", ".cr2", ".nef", ".arw", ".dng", ".orf"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".3gp", ".webm", ".mts"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma", ".aiff", ".opus"},
    "installer": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage", ".apk", ".iso"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"},
    "document": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages", ".epub", ".tex"},
    "spreadsheet": {".xls", ".xlsx", ".ods", ".csv", ".numbers", ".tsv"},
    "presentation": {".ppt", ".pptx", ".odp", ".key"},
    "code": {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp", ".h",
             ".cs", ".rb", ".php", ".swift", ".kt", ".sh", ".ps1", ".sql", ".html", ".css",
             ".json", ".xml", ".yaml", ".yml", ".toml", ".ipynb"},
    "design": {".psd", ".ai", ".sketch", ".fig", ".xd", ".svg", ".indd", ".blend", ".stl", ".dwg"},
    "font": {".ttf", ".otf", ".woff", ".woff2"},
}
EXT_KIND: Dict[str, str] = {e: k for k, exts in _KIND_EXT.items() for e in exts}

KIND_LABEL = {
    "photo": "Images", "video": "Videos", "audio": "Audio", "installer": "Installers",
    "archive": "Archives", "document": "Documents", "spreadsheet": "Spreadsheets",
    "presentation": "Presentations", "code": "Code", "design": "Design files",
    "font": "Fonts", "other": "Other files",
}

MEDIA_KINDS = {"photo", "video"}

# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

# English + French stopwords (the app is used on both) and file-noise words.
_STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further
had has have having he her here hers herself him himself his how i if in into is it its itself
just me more most my myself no nor not now of off on once only or other our ours ourselves out
over own same she should so some such than that the their theirs them themselves then there
these they this those through to too under until up very was we were what when where which
while who whom why will with you your yours yourself yourselves also may must shall would one
two three new use used using per via etc www http https com org net html pdf
le la les un une des du de d l et ou mais donc or ni car ce cet cette ces mon ma mes ton ta tes
son sa ses notre nos votre vos leur leurs je tu il elle on nous vous ils elles me te se moi toi
lui y en au aux avec sans pour par sur sous dans entre chez vers est sont etre être avoir ai as
a avons avez ont fait faire plus moins tres très bien aussi comme que qui quoi dont ne pas
""".split())

_NOISE_WORDS = set("""
img image images photo photos pic pics picture pictures dsc dscn dcim pxl mvimg vid video videos
mov movie scan scans scanned copy copie final draft v1 v2 v3 rev new nouveau nouvelle untitled
sans titre document documents doc docs file files fichier fichiers page pages screenshot
screenshots capture ecran écran shot export exported download downloads telechargement
version tmp temp test backup bak old misc various stuff folder dossier part iphone ios android
whatsapp signal telegram edited edit jpg jpeg png heic pdf docx xlsx
""".split())

_GENERIC_FOLDERS = set("""
downloads download desktop documents docs mydocuments misc miscellaneous other others stuff
temp tmp files file folder newfolder untitledfolder untitled backup backups bak old archive
archives sort tosort unsorted inbox random various divers nouveaudossier dossier bureau
telechargements téléchargements images pictures photos pics photo videos video movies music
musique audio screenshots camera cameraroll dcim new data export exports import imports
attachments pieces piecesjointes scans scan home user users public shared share common general
stuff2 copy copie
""".split())

# Named folders that usually just hold other curated folders ("Projects/Acme")
_CONTAINER_FOLDERS = set("""
projects project projets projet clients client customers work travail job jobs personal perso
pro professional school ecole university uni courses cours family famille admin administratif
papers papiers business companies company societes
""".split())

_WORD_RE = re.compile(r"[a-z0-9]+")
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_DATE_IN_NAME = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")


def _fold(text: str) -> str:
    """Lowercase and strip accents (facturé -> facture)."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _stem(word: str) -> str:
    """Tiny plural folding so invoice/invoices share a term."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    """Split text into meaningful terms (no stopwords, digits or noise)."""
    if not text:
        return []
    text = _CAMEL_RE.sub(" ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", text)  # Client2023 -> Client 2023
    out = []
    for w in _WORD_RE.findall(_fold(text)):
        if len(w) < 3 or w.isdigit():
            continue
        if w in _STOPWORDS or w in _NOISE_WORDS:
            continue
        out.append(_stem(w))
    return out


def is_generic_folder(name: str) -> bool:
    """Folder names that say nothing about the content (dissolved, not kept)."""
    key = re.sub(r"[^a-z0-9]", "", _fold(name))
    if not key:
        return True
    if key in _GENERIC_FOLDERS:
        return True
    if re.fullmatch(r"\d+", key):               # 2023, 100, 001
        return True
    if re.fullmatch(r"\d+[a-z]{0,6}", key):     # 100apple, 101msdcf
        return True
    if re.fullmatch(r"(new|untitled|nouveau)?(folder|dossier)\d*", key):
        return True
    if re.fullmatch(r"(copy|copie)(of)?.*", key):
        return True
    return not tokenize(name)


def _clean_name(name: str, limit: int = 40) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .-_")
    return name[:limit].strip()


# ---------------------------------------------------------------------------
# Sparse vectors
# ---------------------------------------------------------------------------

Vec = Dict[str, float]


def _norm(v: Vec) -> float:
    return math.sqrt(sum(x * x for x in v.values()))


def _normalize(v: Vec) -> Vec:
    n = _norm(v)
    return {k: x / n for k, x in v.items()} if n else {}


def _cos(a: Vec, b: Vec) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(k, 0.0) for k, x in a.items())


def _add_into(acc: Vec, v: Vec, w: float = 1.0) -> None:
    for k, x in v.items():
        acc[k] = acc.get(k, 0.0) + x * w


def _top(v: Vec, n: int) -> Vec:
    if len(v) <= n:
        return v
    return dict(sorted(v.items(), key=lambda kv: -kv[1])[:n])


def _centroid(vectors: Iterable[Vec]) -> Vec:
    acc: Vec = {}
    for v in vectors:
        _add_into(acc, v)
    return _normalize(_top(acc, MAX_TERMS_PER_VECTOR * 2))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FileProfile:
    id: int
    path: str
    filename: str
    rel_dirs: List[str]            # folders between scan root and the file
    kind: str
    terms: Counter                 # raw weighted term counts
    date: Optional[datetime] = None
    date_source: str = ""
    gps: Optional[Tuple[float, float]] = None
    is_screenshot: bool = False


@dataclass
class Unit:
    """Something placed as one block: a curated folder or a single file."""
    key: str
    files: List[FileProfile]
    name: str = ""                 # folder name when the unit is a kept folder
    base_dirs: List[str] = field(default_factory=list)  # rel dirs of the kept folder
    vec: Vec = field(default_factory=dict)

    @property
    def kind(self) -> str:
        kinds = Counter(f.kind for f in self.files)
        return kinds.most_common(1)[0][0] if kinds else "other"

    @property
    def size(self) -> int:
        return len(self.files)

    def media_share(self) -> float:
        return sum(1 for f in self.files if f.kind in MEDIA_KINDS) / max(1, self.size)


@dataclass
class Node:
    name: str
    rationale: str = ""
    children: List["Node"] = field(default_factory=list)
    units: List[Unit] = field(default_factory=list)
    centroid: Vec = field(default_factory=dict)

    def file_count(self) -> int:
        return sum(u.size for u in self.units) + sum(c.file_count() for c in self.children)


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------

def _parse_date(f: Dict[str, Any]) -> Tuple[Optional[datetime], str]:
    exif = f.get("exif") or {}
    dt = exif.get("datetime_original") or ""
    if dt:
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
            try:
                return datetime.strptime(dt[:19] if " " in dt else dt[:10], fmt), "exif"
            except ValueError:
                continue
    m = _DATE_IN_NAME.search(f.get("filename", ""))
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))), "filename"
        except ValueError:
            pass
    mt = f.get("modified_time")
    if mt:
        try:
            return datetime.fromisoformat(str(mt)[:19]), "modified"
        except ValueError:
            pass
    return None, ""


def _rel_dirs(path: str, scan_root: str) -> List[str]:
    if not path:
        return []
    p = os.path.normpath(path)
    if scan_root:
        for cand_p, root in ((p, os.path.normpath(scan_root)),
                             (os.path.realpath(p), os.path.realpath(scan_root))):
            if cand_p.startswith(root + os.sep):
                rel = cand_p[len(root) + 1:]
                return [x for x in rel.split(os.sep)[:-1] if x]
    return [x for x in os.path.dirname(p).split(os.sep) if x][-3:]


def profile_file(idx: int, f: Dict[str, Any], scan_root: str,
                 read_content: Callable[[str], str] = None) -> FileProfile:
    read_content = read_content or (lambda p: extract_text(p, max_chars=CONTENT_CHARS))
    path = f.get("path", "")
    filename = f.get("filename") or os.path.basename(path)
    ext = (f.get("extension") or os.path.splitext(filename)[1]).lower()
    kind = EXT_KIND.get(ext, "other")
    rel = _rel_dirs(path, scan_root)

    terms: Counter = Counter()
    stem = os.path.splitext(filename)[0]
    for t in tokenize(stem):
        terms[t] += 3.0
    # Meaningful folder names above the file carry the user's own intent
    meaningful = [d for d in rel if not is_generic_folder(d)]
    for depth, d in enumerate(reversed(meaningful)):
        for t in tokenize(d):
            terms[t] += max(0.8, 2.0 - 0.4 * depth)
    if kind not in MEDIA_KINDS and kind not in {"audio", "installer", "archive", "font"}:
        content = ""
        try:
            content = read_content(path) if path else ""
        except Exception:
            content = ""
        counts = Counter(tokenize(content))
        for t, c in counts.items():
            terms[t] += 1.0 + math.log(c)          # sub-linear tf

    date, source = _parse_date(f)
    exif = f.get("exif") or {}
    gps = None
    if exif.get("gps_lat") is not None and exif.get("gps_lon") is not None:
        gps = (float(exif["gps_lat"]), float(exif["gps_lon"]))
    low = _fold(filename)
    is_shot = kind == "photo" and bool(re.search(r"screen ?shot|capture d.?ecran|screen_?\d|scrnli", low))
    return FileProfile(idx, path, filename, rel, kind, terms, date, source, gps, is_shot)


# ---------------------------------------------------------------------------
# Units: keep curated folders whole, dissolve dump folders
# ---------------------------------------------------------------------------

def build_units(profiles: List[FileProfile]) -> List[Unit]:
    total = len(profiles)
    cap = max(UNIT_MAX_FILES_FLOOR, int(total * UNIT_MAX_SHARE))

    subtree_count: Counter = Counter()
    direct_count: Counter = Counter()
    child_dirs: Dict[Tuple[str, ...], set] = defaultdict(set)
    for p in profiles:
        direct_count[tuple(p.rel_dirs)] += 1
        for i in range(1, len(p.rel_dirs) + 1):
            subtree_count[tuple(p.rel_dirs[:i])] += 1
            if i < len(p.rel_dirs):
                child_dirs[tuple(p.rel_dirs[:i])].add(p.rel_dirs[i])

    def unit_key_for(p: FileProfile) -> Optional[Tuple[str, ...]]:
        for i, d in enumerate(p.rel_dirs):
            prefix = tuple(p.rel_dirs[:i + 1])
            if is_generic_folder(d):
                continue
            n = subtree_count[prefix]
            has_named_children = any(not is_generic_folder(c) for c in child_dirs.get(prefix, ()))
            if has_named_children:
                key = re.sub(r"[^a-z]", "", _fold(d))
                wrapper = direct_count[prefix] == 0 and len(child_dirs[prefix]) == 1
                if n > cap or wrapper or key in _CONTAINER_FOLDERS:
                    continue  # container ("Work", "Projects"): its children become the units
            if n < 2:
                return None  # a named folder with one file says little — place the file
            return prefix
        return None

    groups: Dict[Tuple[str, ...], List[FileProfile]] = defaultdict(list)
    units: List[Unit] = []
    for p in profiles:
        key = unit_key_for(p)
        if key is None:
            units.append(Unit(key=f"file:{p.id}", files=[p]))
        else:
            groups[key].append(p)
    for key, files in groups.items():
        units.append(Unit(key="dir:" + "/".join(key), files=files, name=key[-1], base_dirs=list(key)))
    return units


def vectorize_units(units: List[Unit]) -> Dict[str, float]:
    """TF-IDF unit vectors. Returns the idf table (used for routing later)."""
    raw: List[Counter] = []
    for u in units:
        acc: Counter = Counter()
        for f in u.files:
            for t, w in f.terms.items():
                acc[t] += w / u.size ** 0.5
        if u.name:
            for t in tokenize(u.name):
                acc[t] += 4.0
        raw.append(acc)

    n = len(units)
    df: Counter = Counter()
    for acc in raw:
        df.update(acc.keys())
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    too_common = {t for t, c in df.items() if n >= 12 and c > 0.6 * n}
    for u, acc in zip(units, raw):
        v = {t: w * idf[t] for t, w in acc.items() if t not in too_common}
        # terms seen in one unit only can't group anything but they name kept folders
        shared = {t: w for t, w in v.items() if df[t] > 1}
        u.vec = _normalize(_top(shared or ({} if not u.name else v), MAX_TERMS_PER_VECTOR))
    return idf


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _kmeans(units: List[Unit], k: int, iters: int = 12) -> List[List[Unit]]:
    """Deterministic spherical k-means with farthest-point initialisation."""
    pts = [u for u in units if u.vec]
    if len(pts) <= k:
        return [[u] for u in pts]
    weights = [u.size for u in pts]
    first = max(range(len(pts)), key=lambda i: (weights[i], len(pts[i].vec)))
    centers = [pts[first].vec]
    best_sim = [_cos(p.vec, centers[0]) for p in pts]
    while len(centers) < k:
        i = min(range(len(pts)), key=lambda j: (best_sim[j], -weights[j]))
        centers.append(pts[i].vec)
        best_sim = [max(s, _cos(p.vec, centers[-1])) for s, p in zip(best_sim, pts)]
    assign = [-1] * len(pts)
    for _ in range(iters):
        changed = False
        for i, p in enumerate(pts):
            c = max(range(len(centers)), key=lambda j: _cos(p.vec, centers[j]))
            if c != assign[i]:
                assign[i] = c
                changed = True
        buckets: List[List[int]] = [[] for _ in centers]
        for i, c in enumerate(assign):
            buckets[c].append(i)
        centers = [
            _centroid(pts[i].vec for i in b) if b else centers[j]
            for j, b in enumerate(buckets)
        ]
        if not changed:
            break
    out: List[List[Unit]] = [[] for _ in centers]
    for i, c in enumerate(assign):
        out[c].append(pts[i])
    return [g for g in out if g]


def _files(group: List[Unit]) -> int:
    return sum(u.size for u in group)


def cluster_units(units: List[Unit], max_k: int) -> List[List[Unit]]:
    """Group units by topic; fold tiny groups; merge near-duplicate groups."""
    with_vec = [u for u in units if u.vec]
    if len(with_vec) < 2:
        return [with_vec] if with_vec else []
    # Over-cluster, then let merging / folding settle the real number of topics
    k = max(2, min(max_k, len(with_vec) // 3))
    groups = _kmeans(with_vec, k)

    # Merge near-duplicates
    merged = True
    while merged and len(groups) > 1:
        merged = False
        cents = [_centroid(u.vec for u in g) for g in groups]
        best = (0.0, -1, -1)
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                s = _cos(cents[i], cents[j])
                if s > best[0]:
                    best = (s, i, j)
        if best[0] >= MERGE_SIMILARITY:
            _, i, j = best
            groups[i].extend(groups.pop(j))
            merged = True

    # Fold tiny groups into their nearest neighbour
    while len(groups) > 1:
        small = [i for i, g in enumerate(groups) if _files(g) < MIN_GROUP_FILES]
        if not small:
            break
        i = min(small, key=lambda x: _files(groups[x]))
        g = groups.pop(i)
        cents = [_centroid(u.vec for u in other) for other in groups]
        for u in g:
            j = max(range(len(groups)), key=lambda x: _cos(u.vec, cents[x]))
            groups[j].append(u)
    groups.sort(key=_files, reverse=True)
    return groups


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def _distinctive_terms(units: List[Unit], group_cent: Vec, parent_cent: Vec,
                       siblings: List[Vec], n: int = 3) -> List[str]:
    """Words that describe this group and not its siblings, favouring words
    shared by many of its members over one loud file."""
    with_vec = [u for u in units if u.vec] or units
    scores = {}
    for t, w in group_cent.items():
        sib = max((s.get(t, 0.0) for s in siblings), default=0.0)
        coverage = sum(1 for u in with_vec if t in u.vec) / max(1, len(with_vec))
        scores[t] = (w - 0.6 * sib - 0.3 * parent_cent.get(t, 0.0)) * (0.3 + coverage)
    return [t for t, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s > 0][:n]


def _keyword_name(terms: List[str]) -> str:
    return terms[0].capitalize() if terms else "General"


def _examples(units: List[Unit], n: int = 4) -> List[str]:
    out = []
    for u in sorted(units, key=lambda x: -x.size):
        out.append(f"{u.name}/ ({u.size} files)" if u.name else u.files[0].filename)
        if len(out) >= n:
            break
    return out


def _dedupe(names: List[str], fallbacks: List[List[str]]) -> List[str]:
    seen: Counter = Counter()
    out = []
    for name, fb in zip(names, fallbacks):
        key = name.lower()
        if seen[key]:
            extra = next((t.capitalize() for t in fb if t.capitalize() not in name), None)
            name = f"{name} {extra}" if extra else f"{name} {seen[key] + 1}"
        seen[name.lower()] += 1
        seen[key] += 1
        out.append(name)
    return out


_BAD_LLM_NAMES = {"group", "folder", "category", "misc", "other", "uncategorized", "files", "none", "n/a"}


def _llm_names(namer: Callable[[str], str], parent: str,
               items: List[Tuple[List[str], List[str]]]) -> Dict[int, str]:
    """Ask the local LLM for short folder names for one sibling set."""
    lines = []
    for i, (terms, examples) in enumerate(items):
        lines.append(f"{i}: keywords: {', '.join(terms) or '-'} | examples: {'; '.join(examples)}")
    prompt = (
        "You are organising someone's computer. Give each group of files a short, clear "
        "folder name (1 to 3 words, Title Case, no slashes, no dates, no file extensions). "
        "Names must describe the subject, be different from each other, and use the same "
        "language as the keywords.\n"
        f"Parent folder: {parent or '(top level)'}\n\n"
        "Groups:\n" + "\n".join(lines) + "\n\n"
        "Answer with one line per group, exactly like:\n0: Taxes\n1: Client Projects\n"
    )
    try:
        text = namer(prompt) or ""
    except Exception as e:  # pragma: no cover - network errors
        print(f"[Architect] naming call failed: {e}", flush=True)
        return {}
    out: Dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s*[:.)-]\s*(.+)$", line)
        if not m:
            continue
        i = int(m.group(1))
        name = _clean_name(m.group(2).strip("*`\"' "))
        if not (0 <= i < len(items)) or not name or len(name.split()) > 4:
            continue
        if name.lower() in _BAD_LLM_NAMES:
            continue
        out[i] = name
    return out


def name_siblings(nodes: List[Node], parent: Optional[Node], namer: Optional[Callable[[str], str]]) -> None:
    if not nodes:
        return
    parent_cent = parent.centroid if parent else {}
    cents = [n.centroid for n in nodes]
    terms = [
        _distinctive_terms(n.units or [u for c in n.children for u in c.units],
                           c, parent_cent, cents[:i] + cents[i + 1:])
        for i, (n, c) in enumerate(zip(nodes, cents))
    ]
    names = [_keyword_name(t) for t in terms]
    if namer and len(nodes) > 0:
        llm = _llm_names(namer, parent.name if parent else "", [
            (t, _examples(n.units or [u for c in n.children for u in c.units], 4))
            for t, n in zip(terms, nodes)
        ])
        names = [llm.get(i, nm) for i, nm in enumerate(names)]
    names = _dedupe([_clean_name(n) or "General" for n in names], terms)
    for node, nm, t in zip(nodes, names, terms):
        node.name = nm
        ex = _examples(node.units or [u for c in node.children for u in c.units], 3)
        node.rationale = (
            f"Grouped by content ({', '.join(t) if t else 'shared words'}) — e.g. {', '.join(ex)}"
        )


# ---------------------------------------------------------------------------
# Topic branch
# ---------------------------------------------------------------------------

def build_topic_nodes(units: List[Unit], namer, parent: Optional[Node], depth: int,
                      max_depth: int = 1) -> List[Node]:
    max_k = TOP_LEVEL_MAX_TOPICS if depth == 0 else SUB_MAX_TOPICS
    groups = cluster_units(units, max_k)
    nodes = [Node(name="", units=g, centroid=_centroid(u.vec for u in g)) for g in groups]
    if depth == 0 or len(nodes) > 1:
        name_siblings(nodes, parent, namer)
    for node in nodes:
        if depth < max_depth and node.file_count() >= SPLIT_MIN_FILES and len(node.units) >= SPLIT_MIN_UNITS:
            subs = build_topic_nodes(node.units, namer, node, depth + 1, max_depth)
            if len(subs) > 1:
                node.children = subs
                node.units = []
    return nodes


def assign_areas(nodes: List[Node], areas: List[str],
                 namer: Optional[Callable[[str], str]]) -> Dict[int, str]:
    """Put top-level subject folders under the user's main areas (Work, Family...).
    The LLM decides when available; otherwise words shared between the area
    name and the folder decide. Folders matching no area stay at the top."""
    if not areas or not nodes:
        return {}
    out: Dict[int, str] = {}
    for i, n in enumerate(nodes):           # a folder already named like an area
        for a in areas:
            if n.name.lower() == a.lower():
                out[i] = a
    if namer:
        letters = "ABCDEFGH"
        prompt = (
            "Someone organises their computer into these main areas:\n"
            + "\n".join(f"{letters[j]}: {a}" for j, a in enumerate(areas))
            + "\n\nFor each folder below, answer with the letter of the area it belongs to, "
            "or 'none' if it fits none of them.\n\n"
            + "\n".join(f"{i}: {n.name} — {n.rationale[:120]}" for i, n in enumerate(nodes))
            + "\n\nAnswer one line per folder, like:\n0: A\n1: none\n"
        )
        try:
            text = namer(prompt) or ""
        except Exception as e:  # pragma: no cover
            print(f"[Architect] area assignment failed: {e}", flush=True)
            text = ""
        for line in text.splitlines():
            m = re.match(r"^\s*(\d+)\s*[:.)-]\s*([A-Ha-h])\b", line)
            if m:
                i, j = int(m.group(1)), letters.index(m.group(2).upper())
                if 0 <= i < len(nodes) and j < len(areas) and i not in out:
                    out[i] = areas[j]
    for i, n in enumerate(nodes):
        if i in out:
            continue
        name_terms = set(tokenize(n.name))
        best, best_s = None, 0.0
        for a in areas:
            terms = tokenize(a)
            score = sum(n.centroid.get(t, 0.0) for t in terms) + (0.5 if name_terms & set(terms) else 0.0)
            if score > best_s:
                best, best_s = a, score
        if best and best_s >= 0.05:
            out[i] = best
    return out


# ---------------------------------------------------------------------------
# Media branch: albums + events
# ---------------------------------------------------------------------------

_CITY_TABLE = [
    (48.85, 2.35, "Paris"), (43.30, 5.37, "Marseille"), (43.53, 5.45, "Aix-en-Provence"),
    (45.76, 4.84, "Lyon"), (43.70, 7.27, "Nice"), (44.84, -0.58, "Bordeaux"),
    (43.60, 1.44, "Toulouse"), (47.22, -1.55, "Nantes"), (50.63, 3.06, "Lille"),
    (48.57, 7.75, "Strasbourg"), (51.51, -0.13, "London"), (40.71, -74.01, "New York"),
    (34.05, -118.24, "Los Angeles"), (37.77, -122.42, "San Francisco"), (41.39, 2.17, "Barcelona"),
    (40.42, -3.70, "Madrid"), (41.90, 12.50, "Rome"), (52.52, 13.40, "Berlin"),
    (52.37, 4.90, "Amsterdam"), (46.20, 6.14, "Geneva"), (47.37, 8.54, "Zurich"),
    (50.85, 4.35, "Brussels"), (38.72, -9.14, "Lisbon"), (35.68, 139.69, "Tokyo"),
    (1.35, 103.82, "Singapore"), (22.32, 114.17, "Hong Kong"), (25.04, 121.57, "Taipei"),
    (31.23, 121.47, "Shanghai"), (39.90, 116.40, "Beijing"), (32.04, 120.78, "Jiangdu"),
    (-33.87, 151.21, "Sydney"), (-37.81, 144.96, "Melbourne"), (-27.47, 153.02, "Brisbane"),
    (-31.95, 115.86, "Perth"), (25.20, 55.27, "Dubai"), (45.50, -73.57, "Montreal"),
    (43.65, -79.38, "Toronto"), (-22.91, -43.17, "Rio de Janeiro"), (13.76, 100.50, "Bangkok"),
]


def nearest_place(lat: float, lon: float, max_km: float = 60) -> Optional[str]:
    best, best_d = None, float("inf")
    for c_lat, c_lon, name in _CITY_TABLE:
        dlat = (lat - c_lat) * 111
        dlon = (lon - c_lon) * 111 * math.cos(math.radians(lat))
        d = math.hypot(dlat, dlon)
        if d < best_d:
            best, best_d = name, d
    return best if best_d <= max_km else None


def _event_label(files: List[FileProfile]) -> str:
    start = min(f.date for f in files)
    end = max(f.date for f in files)
    places = Counter(
        p for p in (nearest_place(*f.gps) for f in files if f.gps) if p
    )
    place = places.most_common(1)[0][0] if places else ""
    label = start.strftime("%Y-%m-%d")
    if end.date() != start.date():
        label += f" to {end.strftime('%m-%d') if end.year == start.year else end.strftime('%Y-%m-%d')}"
    return f"{label} {place}".strip()


def build_events(photos: List[FileProfile]) -> List[Tuple[str, str, List[FileProfile]]]:
    """Split dated photos into events by time gaps. Returns (year, label, files)."""
    dated = sorted((f for f in photos if f.date), key=lambda f: f.date)
    events: List[List[FileProfile]] = []
    for f in dated:
        if events and (f.date - events[-1][-1].date).total_seconds() <= EVENT_GAP_HOURS * 3600:
            events[-1].append(f)
        else:
            events.append([f])
    # A continuous stream of photos (daily shots) is not one event: split by month
    split: List[Tuple[List[FileProfile], bool]] = []
    for ev in events:
        if (ev[-1].date - ev[0].date).days > EVENT_MAX_DAYS:
            months: Dict[str, List[FileProfile]] = defaultdict(list)
            for f in ev:
                months[f.date.strftime("%Y-%m")].append(f)
            split.extend((m, True) for m in months.values())
        else:
            split.append((ev, False))
    out: List[Tuple[str, str, List[FileProfile]]] = []
    leftovers: Dict[str, List[FileProfile]] = defaultdict(list)
    for ev, is_month in split:
        if len(ev) >= EVENT_MIN_PHOTOS:
            label = ev[0].date.strftime("%Y-%m") if is_month else _event_label(ev)
            out.append((ev[0].date.strftime("%Y"), label, ev))
        else:
            leftovers[ev[0].date.strftime("%Y-%m")].extend(ev)
    for month, files in leftovers.items():
        out.append((month[:4], f"{month} other", files))
    out.sort(key=lambda e: (e[0], e[1]))
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

@dataclass
class Placement:
    file_id: int
    path: List[str]           # folder components of the new location
    rationale: str


class TreeArchitect:
    def __init__(self, scan_root: str = "", namer: Optional[Callable[[str], str]] = None,
                 read_content: Optional[Callable[[str], str]] = None,
                 prefs: Optional[Preferences] = None):
        self.scan_root = scan_root
        self.prefs = prefs or Preferences()
        self.namer = namer
        self.read_content = read_content
        self.idf: Dict[str, float] = {}
        self.leaf_profiles: List[Dict[str, Any]] = []

    # -- public -----------------------------------------------------------
    def build(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not files:
            return {"tree": [], "summary": {}, "model": {}}
        return self._build_from_profiles(self._profile_all(files), files)

    def preview_choices(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """The preference check: a few questions, each option previewed with what
        the user's OWN files would look like. Builds the tree a handful of times
        from one profiling pass, without LLM calls (keyword names are fine for a
        preview)."""
        if not files:
            return {"questions": [], "suggested_areas": [], "protect_candidates": [], "preferences": self.prefs.to_dict()}
        profiles = self._profile_all(files, progress=False)
        base_prefs, namer = self.prefs, self.namer
        self.namer = None
        try:
            def variant(**changes) -> List[Dict[str, Any]]:
                self.prefs = replace(base_prefs, **changes)
                return self._build_from_profiles(profiles, files)["tree"]

            base = variant()
            questions = []

            fixed = {"Photos", "Videos", "Music", "Software & Archives", TO_SORT}
            topics = [n for n in base if n["category"] not in fixed]
            if topics:
                biggest = max(topics, key=lambda n: n["count"])["category"]
                opts = []
                for value, label in (("auto", "Just by subject"), ("year", "By year"), ("type", "By file type")):
                    tree = variant(inside_topics=value, areas=[])
                    node = next((n for n in tree if n["category"] == biggest), None)
                    opts.append({"value": value, "label": label, "preview": _preview_lines(node, 6)})
                questions.append({
                    "id": "inside_topics",
                    "question": f"Inside a subject folder like “{biggest}”, how should files be arranged?",
                    "options": opts,
                })

            n_photos = sum(1 for p in profiles if p.kind == "photo" and not p.is_screenshot)
            if n_photos >= 10:
                opts = []
                for value, label in (("events", "By trip or event"), ("months", "By year and month")):
                    node = next((n for n in variant(photos=value) if n["category"] == "Photos"), None)
                    opts.append({"value": value, "label": label, "preview": _preview_lines(node, 6, skip=("Albums", "Screenshots"))})
                questions.append({"id": "photos", "question": f"How should your {n_photos} photos be organised?", "options": opts})

            opts = []
            for value, label in (("shallow", "Simple: few levels"), ("detailed", "Detailed: more sub-folders")):
                tree = variant(depth=value)
                folders = {"/".join([n["category"]] + s["subcategory"].split("/")[:i])
                           for n in tree for s in n["subbuckets"]
                           for i in range(len([x for x in s["subcategory"].split("/") if x]) + 1)}
                opts.append({"value": value, "label": label,
                             "preview": [f"{len(tree)} top folders, {len(folders)} folders in total"]
                                        + [f"{n['category']} ({n['count']})" for n in tree[:5]]})
            questions.append({"id": "depth", "question": "How deep should the tree go?", "options": opts})

            kept = [u for u in build_units(profiles) if u.name]
            kept.sort(key=lambda u: -u.size)
            candidates = [{
                "path": os.path.join(self.scan_root, *u.base_dirs) if self.scan_root else "/".join(u.base_dirs),
                "name": "/".join(u.base_dirs),
                "files": u.size,
            } for u in kept[:12]]
            # Only ask what makes a visible difference for THESE files
            questions = [q for q in questions
                         if len({tuple(o["preview"]) for o in q["options"]}) > 1]
            return {
                "questions": questions,
                "suggested_areas": SUGGESTED_AREAS,
                "protect_candidates": candidates,
                "preferences": base_prefs.to_dict(),
            }
        finally:
            self.prefs, self.namer = base_prefs, namer

    def _build_from_profiles(self, all_profiles: List[FileProfile], files: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.idf, self.leaf_profiles = {}, []
        prefs = self.prefs
        profiles = [p for p in all_profiles if not prefs.is_protected(p.path)]
        protected = len(all_profiles) - len(profiles)
        if not profiles:
            return {"tree": [], "summary": {"files": 0, "protected": protected}, "model": self.model()}
        units = build_units(profiles)

        media_units, audio_units, software_units, topic_units = [], [], [], []
        for u in units:
            k = u.kind
            if u.media_share() >= 0.7:
                media_units.append(u)
            elif k == "audio":
                audio_units.append(u)
            elif not u.name and k in {"installer", "archive", "font"}:
                software_units.append(u)
            else:
                topic_units.append(u)

        self.idf = vectorize_units(topic_units) if topic_units else {}
        placements: List[Placement] = []
        top_nodes: List[Node] = []

        # Topic folders
        signal = [u for u in topic_units if u.vec]
        no_signal = [u for u in topic_units if not u.vec]
        if signal:
            if len(signal) == 1 or _files(signal) < MIN_GROUP_FILES * 2:
                n = Node(name="", units=signal, centroid=_centroid(u.vec for u in signal))
                name_siblings([n], None, self.namer)
                top_nodes = [n]
            else:
                top_nodes = build_topic_nodes(signal, self.namer, None, 0,
                                              max_depth=0 if prefs.depth == "shallow" else 1)
        areas = assign_areas(top_nodes, prefs.areas, self.namer)
        for i, node in enumerate(top_nodes):
            area = areas.get(i)
            if area and area.lower() == node.name.lower():
                node.name, area = area, None          # the folder IS the area
            self._place_topic(node, [area] if area else [], placements)

        self._place_media(media_units, placements)
        self._place_audio(audio_units, placements)
        self._place_software(software_units, placements)
        self._place_unsorted(no_signal, placements)

        tree = self._to_legacy(placements, files)
        summary = self._summary(profiles, placements)
        summary["protected"] = protected
        summary["preferences"] = prefs.to_dict()
        return {"tree": tree, "summary": summary, "model": self.model()}

    def _profile_all(self, files: List[Dict[str, Any]], progress: bool = True) -> List[FileProfile]:
        """Profile every file, emitting the categorize_progress events the UI shows."""
        import time
        start = time.monotonic()
        total = len(files)
        profiles = []
        for i, f in enumerate(files):
            profiles.append(profile_file(i, f, self.scan_root, self.read_content))
            done = i + 1
            if progress and (done % 100 == 0 or done == total):
                elapsed = time.monotonic() - start
                print(json.dumps({
                    "event": "categorize_progress",
                    "progress": round(0.9 * done / total, 3),   # last 10%: clustering + naming
                    "files_done": done,
                    "files_total": total,
                    "elapsed_seconds": round(elapsed, 1),
                    "eta_seconds": round(elapsed / done * (total - done), 1),
                }), flush=True)
        return profiles

    def model(self) -> Dict[str, Any]:
        top_idf = dict(sorted(self.idf.items(), key=lambda kv: kv[1])[:8000])
        return {"version": 1, "idf": top_idf, "leaves": self.leaf_profiles,
                "preferences": self.prefs.to_dict()}

    # -- placement ----------------------------------------------------------
    def _place_units(self, units: List[Unit], path: List[str], rationale: str,
                     placements: List[Placement], keep_folders: bool = True) -> None:
        for u in units:
            if u.name and keep_folders:
                why = f"Kept your folder '{u.name}' together ({u.size} files) — {rationale}"
                for f in u.files:
                    inner = [d for d in f.rel_dirs[len(u.base_dirs):] if not is_generic_folder(d)]
                    placements.append(Placement(f.id, path + [_clean_name(u.name)] + [_clean_name(d) for d in inner], why))
            else:
                for f in u.files:
                    placements.append(Placement(f.id, list(path), rationale))

    def _place_topic(self, node: Node, prefix: List[str], placements: List[Placement]) -> None:
        path = prefix + [node.name]
        if node.children:
            for c in node.children:
                self._place_topic(c, path, placements)
            return
        self.leaf_profiles.append({
            "path": "/".join(path),
            "centroid": {k: round(v, 4) for k, v in _top(node.centroid, 30).items()},
        })
        loose = [u for u in node.units if not u.name]
        kinds = Counter(u.kind for u in loose)
        years = Counter(u.files[0].date.strftime("%Y") if u.files[0].date else "Undated" for u in loose)
        style = self.prefs.inside_topics
        for u in node.units:
            sub: List[str] = []
            if not u.name:
                if style == "year" and len(years) > 1:
                    f = u.files[0]
                    sub = [f.date.strftime("%Y") if f.date else "Undated"]
                elif style == "type" and len(kinds) > 1:
                    sub = [KIND_LABEL.get(u.kind, "Other files")]
                elif style == "auto" and len(loose) >= 30 and len(kinds) > 1 and kinds[u.kind] >= 8:
                    # many loose files of different kinds in one folder → light kind split
                    sub = [KIND_LABEL.get(u.kind, "Other files")]
            self._place_units([u], path + sub, node.rationale, placements)

    def _place_media(self, units: List[Unit], placements: List[Placement]) -> None:
        if not units:
            return
        albums = [u for u in units if u.name]
        loose = [f for u in units if not u.name for f in u.files]
        for u in albums:
            why = f"Album: your folder '{u.name}' kept together ({u.size} files)"
            for f in u.files:
                inner = [d for d in f.rel_dirs[len(u.base_dirs):] if not is_generic_folder(d)]
                top = "Videos" if u.kind == "video" else "Photos"
                placements.append(Placement(f.id, [top, "Albums", _clean_name(u.name)] + [_clean_name(d) for d in inner], why))
        photos = [f for f in loose if f.kind == "photo" and not f.is_screenshot]
        shots = [f for f in loose if f.is_screenshot]
        videos = [f for f in loose if f.kind == "video"]
        for f in shots:
            when = f.date.strftime("%Y") if f.date else "Undated"
            path = ["Photos", "Screenshots", when] if len(shots) >= SMALL_BRANCH_FILES * 2 else ["Photos", "Screenshots"]
            placements.append(Placement(f.id, path, "Screenshots" + (", filed by year" if len(path) == 3 else "")))
        self._place_events(photos, "Photos", placements)
        self._place_events(videos, "Videos", placements)

    def _place_events(self, items: List[FileProfile], top: str, placements: List[Placement]) -> None:
        if not items:
            return
        if self.prefs.photos == "months":
            months: Dict[str, List[FileProfile]] = defaultdict(list)
            for f in items:
                if f.date:
                    months[f.date.strftime("%Y-%m")].append(f)
            nested = self.prefs.depth != "shallow" and len({m[:4] for m in months}) > 1
            for month, fs in sorted(months.items()):
                path = [top, month[:4], month] if nested else [top, month]
                for f in fs:
                    placements.append(Placement(f.id, path, f"{top} from {month}, filed by month"))
            for f in items:
                if not f.date:
                    placements.append(Placement(f.id, [top, "Undated"], "No date found in EXIF or filename"))
            return
        events = build_events(items)
        years = {y for y, _, _ in events} if self.prefs.depth != "shallow" else set()
        for year, label, files in events:
            src = Counter(f.date_source for f in files).most_common(1)[0][0]
            why = f"{len(files)} {top.lower()} taken {label} (dates from {src})"
            path = [top, year, label] if len(years) > 1 else [top, label]
            for f in files:
                placements.append(Placement(f.id, path, why))
        for f in items:
            if not f.date:
                placements.append(Placement(f.id, [top, "Undated"], "No date found in EXIF or filename"))

    def _place_audio(self, units: List[Unit], placements: List[Placement]) -> None:
        for u in units:
            if u.name:
                self._place_units([u], ["Music"], "Album/artist folder", placements)
            else:
                for f in u.files:
                    placements.append(Placement(f.id, ["Music", "Singles"], "Loose audio file"))

    def _place_software(self, units: List[Unit], placements: List[Placement]) -> None:
        flat = sum(u.size for u in units) < SMALL_BRANCH_FILES
        for u in units:
            for f in u.files:
                label = KIND_LABEL.get(f.kind, "Other files")
                path = ["Software & Archives"] + ([] if flat else [label])
                placements.append(Placement(f.id, path, "Installers and archives — their content can't be read"))

    def _place_unsorted(self, units: List[Unit], placements: List[Placement]) -> None:
        flat = sum(u.size for u in units if not u.name) < SMALL_BRANCH_FILES
        for u in units:
            if u.name:
                self._place_units([u], [TO_SORT], "Nothing in common with other files yet", placements)
                continue
            for f in u.files:
                path = [TO_SORT] + ([] if flat else [KIND_LABEL.get(f.kind, "Other files")])
                placements.append(Placement(f.id, path,
                                            "Not enough signal (no readable text or meaningful name) to file it confidently"))

    # -- output ---------------------------------------------------------------
    @staticmethod
    def _to_legacy(placements: List[Placement], files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_cat: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        for p in placements:
            cat = p.path[0] if p.path else TO_SORT
            sub = "/".join(p.path[1:])
            bucket = by_cat[cat].setdefault(sub, {"subcategory": sub, "files": [], "rationale": p.rationale})
            bucket["files"].append(p.file_id)
        tree = []
        for cat, subs in by_cat.items():
            buckets = sorted(subs.values(), key=lambda s: (s["subcategory"] == "", s["subcategory"]))
            rationale = buckets[0]["rationale"] if len(buckets) == 1 else (
                buckets[0]["rationale"].split(" — e.g.")[0] if buckets[0]["rationale"].startswith("Grouped") else ""
            )
            tree.append({
                "category": cat,
                "subbuckets": buckets,
                "rationale": rationale,
                "count": sum(len(b["files"]) for b in buckets),
            })
        order = {TO_SORT: 3, "Software & Archives": 2}
        tree.sort(key=lambda n: (order.get(n["category"], 0), -n["count"]))
        return tree

    def _summary(self, profiles: List[FileProfile], placements: List[Placement]) -> Dict[str, Any]:
        def stats(paths: List[Tuple[str, ...]]) -> Dict[str, Any]:
            folders = set()
            for p in paths:
                for i in range(1, len(p) + 1):
                    folders.add(p[:i])
            per_leaf = Counter(paths)
            return {
                "folders": len(folders),
                "max_depth": max((len(p) for p in paths), default=0),
                "loose_files": per_leaf.get((), 0),
                "single_file_folders": sum(1 for p, c in per_leaf.items() if p and c == 1),
            }
        before = stats([tuple(p.rel_dirs) for p in profiles])
        after_paths = [tuple(p.path) for p in placements]
        after = stats(after_paths)
        after["top_level"] = len({p[0] for p in after_paths if p})
        unsorted = sum(1 for p in after_paths if p and p[0] == TO_SORT)
        return {
            "files": len(profiles),
            "before": before,
            "after": after,
            "to_sort": unsorted,
            "kept_folders": len({tuple(p.path) for p in placements if "Kept your folder" in p.rationale or p.rationale.startswith("Album")}),
            "llm_named": bool(self.namer),
        }


def _preview_lines(node: Optional[Dict[str, Any]], n: int, skip: Tuple[str, ...] = ()) -> List[str]:
    """'Category/sub (count)' lines for a preview, biggest first."""
    if not node:
        return []
    subs = [s for s in node["subbuckets"] if not any(s["subcategory"].startswith(x) for x in skip)]
    subs.sort(key=lambda s: -len(s["files"]))
    lines = [f"{node['category']}/{s['subcategory']} ({len(s['files'])})" if s["subcategory"]
             else f"{node['category']} ({len(s['files'])} files directly inside)" for s in subs[:n]]
    if len(subs) > n:
        lines.append(f"… and {len(subs) - n} more")
    return lines


# ---------------------------------------------------------------------------
# Routing new files into an existing tree ("keep it live")
# ---------------------------------------------------------------------------

class TreeRouter:
    """Suggests the best existing folder for a new file using the saved model."""

    def __init__(self, model: Dict[str, Any]):
        self.idf = model.get("idf", {}) or {}
        self.leaves = model.get("leaves", []) or []
        self.prefs = Preferences.from_dict(model.get("preferences"))

    def route(self, f: Dict[str, Any], scan_root: str = "") -> Dict[str, Any]:
        p = profile_file(0, f, scan_root)
        if p.kind == "photo":
            if p.is_screenshot:
                return {"path": f"Photos/Screenshots/{p.date.year if p.date else 'Undated'}", "confidence": 0.9,
                        "rationale": "Screenshot"}
            fmt = "%Y/%Y-%m" if self.prefs.photos == "months" and self.prefs.depth != "shallow" else (
                "%Y-%m" if self.prefs.photos == "months" else "%Y")
            when = p.date.strftime(fmt) if p.date else "Undated"
            return {"path": f"Photos/{when}", "confidence": 0.7, "rationale": "Photo, filed by date"}
        if p.kind == "video":
            return {"path": f"Videos/{p.date.strftime('%Y') if p.date else 'Undated'}", "confidence": 0.7,
                    "rationale": "Video, filed by date"}
        if p.kind == "audio":
            return {"path": "Music/Singles", "confidence": 0.6, "rationale": "Audio file"}
        if p.kind in {"installer", "archive", "font"}:
            label = KIND_LABEL[p.kind]
            return {"path": f"Software & Archives/{label}", "confidence": 0.8, "rationale": label}
        vec = _normalize(_top({t: w * self.idf[t] for t, w in p.terms.items() if t in self.idf}, MAX_TERMS_PER_VECTOR))
        best, best_s = None, 0.0
        for leaf in self.leaves:
            s = _cos(vec, leaf.get("centroid", {}))
            if s > best_s:
                best, best_s = leaf, s
        if best and best_s >= ROUTE_MIN_SIMILARITY:
            shared = [t for t in sorted(vec, key=lambda t: -vec[t]) if t in best["centroid"]][:3]
            return {"path": best["path"], "confidence": round(min(0.95, 0.4 + best_s), 2),
                    "rationale": f"Matches {best['path']} on: {', '.join(shared)}"}
        return {"path": f"{TO_SORT}/{KIND_LABEL.get(p.kind, 'Other files')}", "confidence": 0.0,
                "rationale": "No existing folder matches well enough"}


MODEL_PATH = os.path.expanduser("~/.the-maid/tree_model.json")


def save_model(model: Dict[str, Any], path: str = MODEL_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(model, fh)
    except OSError as e:  # pragma: no cover
        print(f"[Architect] could not save tree model: {e}", flush=True)


def load_model(path: str = MODEL_PATH) -> Dict[str, Any]:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
