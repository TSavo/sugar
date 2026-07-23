# Pandas Census Checkpoint and Isolation Design

## Goal

Make one commit-pinned, five-floor pandas census survive interruption and account
honestly for all 1,415 corpus files without increasing the 30-second per-file
bound.

## Durable row contract

All five floors use one append-only JSONL checkpoint implementation. Before any
child starts, the floor computes the complete sorted corpus manifest and its CID.
Every appended record carries a schema identifier, floor name, manifest CID,
relative file key, and the floor-specific result. The append is flushed and
`fsync`ed before the result is considered complete.

On resume, the loader validates every line. A malformed record, wrong floor,
wrong manifest CID, unknown file, or duplicate file is a loud checkpoint error.
Validated records are the completed set; only absent manifest files are run.
There is no synthesized row for an absent file.

## Per-file process boundary

Every file is constructed in a dedicated child process with a maximum wall bound
of 30 seconds. Normal testimony, ConstructionPanic, BackendDefect or other Python
failure, timeout, and native signal termination become distinct terminal rows.
The parent appends the typed terminal row and continues. Parent infrastructure
failure remains fatal rather than being multiplied into invented per-file rows.

Parallel floors consume futures in completion order so a slow earlier file does
not prevent already-finished later files from reaching disk. Control/effect moves
its construction and testimony into child mode; the parent only classifies,
checkpoints, and aggregates testimony.

## Finalization and reconciliation

A floor report is emitted only by conserving exactly one validated checkpoint row
for every manifest file. Interrupted checkpoints remain explicit partial state and
cannot produce a measured final report. The reconciler requires all five expected
floors, measured summaries, identical non-empty corpus manifests and CIDs, and
exact row/file conservation before it writes `validated-summary.json`.

The production census is launched in detached tmux on battleaxe from one pinned
commit. It is resumed from the same receipt directory after incidental disconnect
or host interruption and is not rebased or restarted when later changes merge.

## Discrimination tests

1. A runner completes and durably appends an early file, is killed while another
   file is in flight, then resumes. The early file is not executed twice and the
   final checkpoint accounts for the entire manifest.
2. Three files run with a child crash planted between two successful files. The
   checkpoint contains both success rows and the typed crash row, proving the
   crash did not abort the run.
3. Foreign-CID, duplicate, malformed, and incomplete checkpoints remain loud.
4. Reconciliation refuses divergent manifests or any incomplete floor.

