# Data Migration

No account, battle, report, model, or log data was copied from the source project.

This repository deliberately starts with a new database under `data`. The source reference and code hashes are recorded in `SOURCE_SNAPSHOT.json`; runtime data remains ignored by Git.

On first open, existing databases gain an `accounts.enabled` column plus `battle_stats.luck_score_total` and `battle_stats.luck_score_count`, all with zero/default values. This migration preserves all account and statistics rows.

Account merges aggregate every stored statistics period into the selected target account and then delete the source accounts. Delete, clear, and merge operations create an automatic backup first.
