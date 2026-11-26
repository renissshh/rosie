# Reliability: backups, limits, recovery

What keeps Rosie (and your data) safe when things go wrong.

## Vault backups

Every day at 03:00 Rosie zips rosie-vault (without its `.git` folder) to
`D:\Rosie\backups\rosie-vault-YYYY-MM-DD.zip` and keeps the newest 14. If the laptop was
asleep at 03:00, the backup runs once when it wakes. The zip is written under a
temporary name and renamed when complete, so a crash never leaves half a backup.

On top of that, rosie-vault is a git repository: every change can be undone from
history, and with a remote it's also on GitHub.

Restore: close Rosie, rename the broken `rosie-vault` folder, unzip the backup into a
new `rosie-vault` folder, then run `rosie vault` to reconnect it to git.
