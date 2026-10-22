# offline-library

`kiwix-sync` keeps the newest Kiwix ZIM dumps on an external disk, for use when the internet is not available. The default books are the full English Wikipedia with images (`wikipedia_en_all_maxi`, approximately 127 GB) and WikiProjectMed's medical wiki (`mdwiki_en_all_maxi`, approximately 2 GB, the content of the WikiMed app).

## How it works

1. The script reads the folder listing on `download.kiwix.org` and finds the newest `<name>_YYYY-MM.zim` for each book in `config.json`.
2. If the disk does not have that version, aria2c downloads it from the mirror's metalink into `<disk>/Kiwix/.partial/`. The metalink gives several mirrors and a SHA-1 hash for each 4 MB piece. A stopped download continues from the last good piece.
3. The script then calculates the SHA-256 of the full file and compares it with the metalink value. If the values are the same, it moves the file into `<disk>/Kiwix/` and deletes the older version. If they are not the same, it deletes the partial file and keeps the old version.
4. It sends a banner and a Discord DM when a new dump is in place, and when a download fails or the disk does not have sufficient free space.

The old dump stays until the new one passes its check, so the disk always holds one complete dump. During a swap the disk needs space for both versions.

## Schedule

The launchd job `com.exobrain.kiwix-sync` starts on every volume mount, at login, and on Sunday at 4:00 AM. If the disk is not mounted, it stops at once. It checks the mirror at most once every `check_every_hours` (20). An unfinished download continues at the next start, without this limit. Kiwix publishes a new English Wikipedia dump approximately every one to six months.

## Commands

```
offline-library/bin/kiwix-sync --status    # local versions and partial downloads
offline-library/bin/kiwix-sync --dry-run   # what it would download, and the free space
offline-library/bin/kiwix-sync --force     # check now, ignore the 20 h limit
```

Log: `~/Library/Logs/exobrain/kiwix-sync.log`. Disk state: `<disk>/Kiwix/.kiwix-sync.json`.

## Install

```
cp offline-library/com.exobrain.kiwix-sync.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.kiwix-sync.plist
```

## Read the files

Open a `.zim` file in the Kiwix desktop app, or serve the folder to a local network with `kiwix-serve` from [kiwix-tools](https://github.com/kiwix/kiwix-tools/releases).

## Notes

- A FAT32 disk cannot hold a file over 4 GB. The script refuses such a disk. exFAT and APFS are correct.
- If you eject the disk during a download, the eject helper (`disk-eject/`) stops aria2c with SIGTERM. aria2c saves its state, and the next mount continues the download.
- To add a book, put its file prefix and mirror folder in `config.json`. The full list is at <https://download.kiwix.org/zim/>.
