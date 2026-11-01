# Existing database changes

`database/schema.sql` is the baseline for a fresh database. Do not rerun it on
an existing database or drop existing tables to apply a change.

Add numbered SQL files here for future structural or reference-data changes.
Document their required starting state and data impact. Run them in numerical
order, with `psql -v ON_ERROR_STOP=1`, and record successful applications locally.
There is no automatic migration runner in this project.

`001_add_taiwan.sql` adds 台湾 to an existing 47-prefecture seed. It is safe
to rerun. Fresh databases receive the same entry from `database/seed.sql`.
Reapply `database/views.sql` when updating the existing view definitions.
