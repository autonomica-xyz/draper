# Runbook: SQLite Backup and Restore

**Last verified:** 2026-07-06
**Applies to:** Draper Marketing Pipeline v2 Phase 5+

## When to use

Use this runbook to take a consistent snapshot of the SQLite runtime
state before a deploy, schema migration, or destructive filesystem
operation; and to restore from such a snapshot after a bad deploy or
data corruption event.

## Production Assumptions

- Production checkout: `/opt/draper`
- SQLite database: `data/marketing_pipeline.sqlite3`
- WAL sidecars (present when SQLite is in WAL journal mode, which is the
  default for this app):
  - `data/marketing_pipeline.sqlite3-wal`
  - `data/marketing_pipeline.sqlite3-shm`
- Service user: `draper`
- Both services (`draper-dashboard`, `draper-worker`) keep open handles
  to the database.

## Backup

The `sqlite3 ... ".backup"` command produces a consistent snapshot
without requiring service downtime and without racing the WAL. This is
the preferred backup method.

1. Take the snapshot:

   ```bash
   BACKUP_DIR=/var/backups/draper
   BACKUP_NAME="draper-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
   sudo mkdir -p "$BACKUP_DIR"
   sudo -u draper sqlite3 /opt/draper/data/marketing_pipeline.sqlite3 \
        ".backup '$BACKUP_DIR/$BACKUP_NAME'"
   ```

2. Verify the backup is readable and counts match the live DB:

   ```bash
   sudo -u draper sqlite3 "$BACKUP_DIR/$BACKUP_NAME" \
        "SELECT COUNT(*) FROM projects; SELECT COUNT(*) FROM reviews; SELECT COUNT(*) FROM jobs;"
   ```

3. (Optional) Also copy binary artifacts that are NOT in SQLite (these
   must be backed up separately):

   ```bash
   sudo -u draper tar -C /opt/draper/data \
        -czf "$BACKUP_DIR/media-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" \
        media/ videos/
   ```

4. Scrub before publishing: backups may contain project content and
   integration secrets. Do not commit or publish backups unless they
   have been scrubbed.

### Plain file copy (fallback)

If the `sqlite3` CLI is unavailable, you can copy the file set directly
— but only when both services are stopped, otherwise the WAL may be
inconsistent:

```bash
sudo systemctl stop draper-worker draper-dashboard
sudo -u draper cp -a /opt/draper/data/marketing_pipeline.sqlite3 \
                     /var/backups/draper/draper-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
sudo -u draper cp -a /opt/draper/data/marketing_pipeline.sqlite3-wal \
                     /var/backups/draper/...sqlite3-wal 2>/dev/null || true
sudo -u draper cp -a /opt/draper/data/marketing_pipeline.sqlite3-shm \
                     /var/backups/draper/...sqlite3-shm 2>/dev/null || true
sudo systemctl start draper-dashboard draper-worker
```

Prefer the `.backup` command — it works while services are running.

## Restore

Restoring replaces live runtime state. Use only after a bad deploy, data
corruption, or an explicit decision to roll back data.

1. Stop both services:

   ```bash
   sudo systemctl stop draper-worker
   sudo systemctl stop draper-dashboard
   ```

2. Preserve the current (failed) state in case the restore itself needs
   reverting:

   ```bash
   cd /opt/draper/data
   sudo -u draper cp -a marketing_pipeline.sqlite3 \
                     marketing_pipeline.sqlite3.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)
   sudo -u draper cp -a marketing_pipeline.sqlite3-wal \
                     marketing_pipeline.sqlite3-wal.pre-restore-$(date -u +%Y%m%dT%H%M%SZ) 2>/dev/null || true
   sudo -u draper cp -a marketing_pipeline.sqlite3-shm \
                     marketing_pipeline.sqlite3-shm.pre-restore-$(date -u +%Y%m%dT%H%M%SZ) 2>/dev/null || true
   ```

3. Replace the database file (delete the WAL/SHM sidecars — they will be
   recreated cleanly by SQLite on next open):

   ```bash
   sudo -u draper cp -a /var/backups/draper/<backup-name>.sqlite3 \
                        marketing_pipeline.sqlite3
   sudo -u draper rm -f marketing_pipeline.sqlite3-wal marketing_pipeline.sqlite3-shm
   ```

4. Restart services and verify:

   ```bash
   sudo systemctl start draper-dashboard
   sudo systemctl start draper-worker
   sudo systemctl status draper-dashboard --no-pager
   sudo systemctl status draper-worker --no-pager
   curl -fsS -H "Authorization: Bearer $DRAPER_DASHBOARD_TOKEN" \
        http://localhost:8765/api/health/deep
   ```

## Reference

- `docs/production.md` — Data and Backups section
- `docs/data-and-media-storage.md` — full storage topology (which paths
  are in SQLite, which are on disk)
- `docs/runbooks/rollback.md` — when to roll back code vs restore data
