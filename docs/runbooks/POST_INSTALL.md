# Post-install completion

Run these steps after `bash scripts/bootstrap.sh` exits. Do not run another package
manager while bootstrap is still active.

1. Check the final phase and failures in `setup.log`, then run
   `bash scripts/postflight.sh`. Read `docs/HEALTH_REPORT.md` and
   `docs/INSTALL_MANIFEST.md`; a listed command does not prove its service works.
2. Log out and back in so Docker and libvirt group membership applies. Verify
   `docker compose version`, `docker run --rm hello-world`, `nvidia-smi`, and
   `gh auth status`. Authenticate GitHub with `gh auth login` if needed.
3. Attach the external HDD, inspect it with `lsblk -f`, and decide its filesystem
   before changing partitions. Record its UUID and filesystem. Mount it at
   `/mnt/backup-hdd` by UUID through `/etc/fstab`, using `nofail` and a short
   device timeout so a disconnected drive cannot block boot. Verify with
   `sudo mount -a`, `mountpoint /mnt/backup-hdd`, and `findmnt -no UUID
   /mnt/backup-hdd`. Save that exact UUID in `~/.config/setup/hdd-uuid`.
   Create `/mnt/backup-hdd/07-Backups` and grant your user ownership of that
   directory only. See `BACKUP_RECOVERY.md` for the commands.
4. Store `~/.config/restic/password` in the password manager and verify the
   saved copy. Create `~/.config/restic/password-backed-up` only then. Once
   the HDD is mounted, compare installed helpers in `~/Scripts` with
   `config/backup/` and review any `.setup-new` copy. Run
   `~/Scripts/backup.sh`, then `~/Scripts/verify-backups.sh` and
   inspect a restored representative file. Confirm the snapshot includes
   `~/KadaOS` before relying on it as the rebuild source.
5. Test a small project build and a ROS workspace build. Try a Hyprland login
   session and verify the GNOME extensions after logging back into GNOME.

Optional phase 7 tools and Hyprland should be chosen based on actual projects;
they are not prerequisites for the core workstation.
