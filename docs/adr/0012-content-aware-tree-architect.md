# ADR 0012: Content-Aware Tree Architect

## Status
Accepted — supersedes the "LLM picks a category per folder" pipeline in `models.py`.

## Context
The first tree builder asked a small LLM to choose one of 12 fixed categories for each
*folder*, from its name and three sample filenames, and kept the original folder path as
the subcategory. The result was the user's existing tree with a generic word in front
("Law > Cryocare services/CIMC"), prompts tuned to one test drive, batch-order dependent
output, and an execution step that created the category folders inside every existing
folder.

## Decision
`the_maid/tree_architect.py` designs the tree deterministically and only uses the LLM to
name folders:

1. **Profile** each file: content words (PDF, Word, Excel, text), filename words,
   meaningful parent-folder words, kind, date (EXIF > filename > mtime), GPS.
2. **Units**: a curated, named folder is kept whole (with its inner structure); generic
   dump folders (Downloads, Misc, New folder, DCIM, years...) are dissolved; container
   folders (Projects, Clients, Work...) pass through to their children.
3. **Branches**: photos/videos by event (time gaps, place) plus albums for named media
   folders; music; installers & archives; everything else by topic.
4. **Cluster** topic units with TF-IDF + spherical k-means (≤ 2 levels), merge
   near-duplicates, fold groups under 3 files into their nearest neighbour.
5. **Name** each sibling set with one LLM call (validated, keyword fallback).
6. **Explain** every folder (keywords + examples, kept folder, event dates/place) and return
   a before/after structure summary.
7. **Route**: leaf-folder profiles are saved to `~/.the-maid/tree_model.json`;
   `POST /tree/route` suggests where new files go.

Execution moves files to `<scanned folder>/<Category>/<sub path>/`, never overwrites
(adds " (2)"), leaves "To Sort" files in place and removes folders it emptied.

## Consequences
- Works without an LLM (keyword names) and is reproducible for the same input.
- ~3 s for 10,000 files of profiling + clustering on a laptop, excluding text extraction.
- Files with no readable signal are honestly put in "To Sort" instead of a guessed bucket.
