# Backup and recovery

The working copies live on the internal Linux filesystem. Restic stores an
encrypted backup on the external HDD at `/mnt/backup-hdd/07-Backups/restic`.
The HDD is absent as of the current handoff, so no backup has been verified.
Add a second encrypted off-site copy later; one HDD cannot protect against
loss of both the laptop and drive.

## First backup

1. Attach the HDD and inspect `lsblk -f` before changing its filesystem.
   Mount it by UUID at `/mnt/backup-hdd` and verify with
   `mountpoint /mnt/backup-hdd`. Do not format an existing drive without
   checking its contents and recovery path. For an ext4 drive, an `/etc/fstab`
   entry can use `UUID=<actual-uuid> /mnt/backup-hdd ext4
   defaults,nofail,x-systemd.device-timeout=5s 0 2`; adapt the filesystem and
   options if the drive is not ext4. Test with `sudo mount -a` and `findmnt`.
   Then prepare only the backup directory:

   ```bash
   sudo mkdir -p /mnt/backup-hdd/07-Backups
   sudo chown "$USER:$USER" /mnt/backup-hdd/07-Backups
   mkdir -p ~/.config/setup
   findmnt -n -o UUID --target /mnt/backup-hdd > ~/.config/setup/hdd-uuid
   chmod 600 ~/.config/setup/hdd-uuid
   ```
2. Phase 5 creates `~/.config/restic/password` with user-only permissions.
   Save its exact contents in a password manager or another independent secure
   place. Without it, the encrypted repository cannot be restored.
3. After verifying that independent copy, create the confirmation marker:
   `touch ~/.config/restic/password-backed-up`. This marker is a deliberate
   gate; `backup.sh` refuses to initialize a repository without it.
4. Compare `~/Scripts/backup.sh` and `~/Scripts/verify-backups.sh` with their
   templates in `KadaOS/config/backup/`. Phase 5 preserves existing
   helpers and writes `.setup-new` copies when the template changes.
   Review those differences before the first run. Then run `~/Scripts/backup.sh`.
   It creates the repository if needed, backs up
   existing project and configuration paths, then applies the documented
   daily/weekly/monthly retention rule.
5. Run `~/Scripts/verify-backups.sh`. It checks repository data and restores
   two representative files to a temporary directory for byte comparison.

The backup includes `KadaOS`, `Projects`, `Workspaces`, `Documents`, `Scripts`, `DocsVault`,
dotfiles, selected lab and container definitions, SSH keys, age/sops keys, and
portable desktop settings when those paths exist. It excludes common build
outputs and caches. `Downloads` is deliberately excluded (transient, ~4 GB);
move anything worth keeping into `Documents` or a project. The Restic password file itself must be preserved outside
the laptop; storing it only inside its own encrypted repository is circular.
The generated backup excludes directories named `node_modules` or `.venv`
anywhere under selected roots; move any irreplaceable data out of those names.
For an intentional non-HDD test repository, set `BACKUP_ALLOW_LOCAL_REPO=1`
alongside `RESTIC_REPOSITORY`. Normal backups require the configured HDD UUID
to match the mounted filesystem.

## Restore drill or recovery

Set `RESTIC_REPOSITORY` to the mounted repository and
`RESTIC_PASSWORD_FILE` to a recovered local password file, then run
`restic snapshots` and `restic check`. Restore to an empty staging directory:

```bash
mkdir -p ~/Restore
restic restore latest --target ~/Restore
```

Inspect paths and compare a representative file before copying data into the
live home directory. Restic recreates the original absolute path underneath
the staging directory, such as `~/Restore/home/USER/Projects`. Restore
private keys with restrictive permissions and inspect them before use. Rebuild
system packages from `KadaOS` instead of copying system directories
out of the file backup. Timeshift is for local system rollback, not a substitute
for the encrypted file backup. Keep the Windows BitLocker recovery key backed
up before repartitioning.

Restic references: [restore](https://restic.readthedocs.io/en/stable/050_restore.html),
[repository checks](https://restic.readthedocs.io/en/stable/045_working_with_repos.html),
[password file variables](https://restic.readthedocs.io/en/stable/075_scripting.html).
