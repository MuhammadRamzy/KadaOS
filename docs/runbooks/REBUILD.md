# Rebuild
1. Install Ubuntu, `sudo apt install git`, copy/clone this folder (back it up: it's in ~/KadaOS, also restic'd via dotfiles/Projects – consider `git init` + private GitHub repo).
2. `bash scripts/bootstrap.sh` → log out/in → `bash scripts/healthcheck.sh`.
3. Recover the Restic password from the password manager, mount the HDD, inspect snapshots, and restore into a fresh `~/Restore` staging directory. Compare files before copying them into the live home. See `BACKUP_RECOVERY.md`.
4. Re-run manual steps in docs/STATUS.md.
