# Active project layout

The recommended repositories are now `Task 1`, `Task 2`, `Task 3`, and `Task 4`. Keep all four.
Task 1 uses `task1/data/stl10_binary`. Tasks 2â€“4 also need root `data/`.
Task 3 uses Task 2's shared helpers, split and source-only baseline.
Root `shared/` is legacy code and is not used by active notebooks.
Use RECOVERY_RUN_ORDER.md for recovery training and review. Restart kernels after renaming.

FOLDER_RENAME_AUDIT.json records migrated paths and Task 4 source fingerprints.
The Task 4 fingerprint mismatch was traced to one empty code cell and resolved. The remaining path-only change was verified against the original lock.
