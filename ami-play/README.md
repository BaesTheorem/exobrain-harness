# ami-play

Unofficial command-line client for **AMI Play**, the phone app for AMI Entertainment's bar
jukeboxes (formerly AMI Music / AMI BarLink). Find venues, read a jukebox's live play queue,
search the catalog, manage favorites and playlists, and queue a song, all from a terminal.

Nothing here is an official API. The wire format was recovered from the Android app
(`com.amientertainment.AMISmartBar` 5.2.0, Kotlin Multiplatform core over Ktor) and checked
against the live production server. AMI can change it at any time.

## Install / invoke

`bin/ami-play` is a stdlib-only Python 3.11+ script: no venv, no dependencies. It registers
itself with the tools registry through the `bin/` scan.

```sh
"ami-play/bin/ami-play" -h
```

## Quick tour

```sh
ami-play venues near 39.0997,-94.5786 --jukebox-only   # bars around a point (remembered)
ami-play venues search "zoo bar"                        # by name
ami-play venue 81943                                    # pricing, dynamic pricing, queue depth
ami-play queue --venue 81943                            # now playing + the queue, live
ami-play search "heilung" --venue 81943                 # songs / artists / albums
ami-play artist 1015638 --venue 81943                   # an artist's songs (--media albums)
ami-play album 1417811 --venue 81943                    # an album's tracks
ami-play lists --venue 81943                            # "Songs Hot Here", staff picks, featured playlists
ami-play list top_songs --venue 81943
ami-play featured 367 --venue 81943                     # songs in a featured playlist

ami-play login you@example.com                          # password prompted (or $AMI_PLAY_PASSWORD)
ami-play status                                         # session, checked-in venue, wallet
ami-play checkin 81943 --at venue                       # makes it the default venue
ami-play play 13619506                                  # queue a song (asks first; --yes to skip)
ami-play favorites; ami-play favorite 13619506
ami-play playlists; ami-play playlist show 12
ami-play raw POST location/v3/recent                    # any endpoint, auth added for you
```

Everything above the `login` line works **without an account**: venue search, venue
details, the play queue, and the whole catalog are public on the server. Check-in,
favorites, playlists, wallet, and playing a song need a login.

Add `--json` to any command to get the server's response verbatim.

## Logging in

The app offers Google, Facebook, and email sign-in. This CLI only speaks email + password
(`user/login`). If the account was created through Google or Facebook, run
`ami-play reset-password you@example.com`; the emailed reset link sets a password on the
same account, after which `ami-play login` works and the app keeps working too.

The session (player id + auth token, plus a client-generated device UUID) is kept in
`secrets/session.json`, mode 0600, gitignored. See `secrets/README.md`.

## Money

`play` is the only command that spends anything. It fetches fresh pricing, shows the
cost in credits and dollars next to your wallet, and asks before sending unless `--yes`
is given (and refuses to spend in a non-interactive session without `--yes`).

How a play is priced (from the app's `Device.Music.getPriceInPennies`):

| | |
| --- | --- |
| base | `basePrice` (one credit) |
| song not stored on the jukebox | + `downloadPrice` |
| `--priority` (jumps the queue) | + `priorityPrice` |
| `--video` | + `videoPrice` |
| free-play jukebox | 0 |

The server may add more on its own: dynamic pricing (`dpAdditionalCredits` at busy times)
and a long-song surcharge (`longSongUpchargeCredits` over `longSongDurationThreshold`
seconds). The CLI shows both when they apply; the receipt's `amountUsed` is what was
actually charged.

## Geocode

Venue search reports distance from a point. `--at LAT,LNG` sets it and it is remembered in
the session for later commands. Check-in sends a geocode too; `--at venue` reports the
venue's own coordinates. `--at none` sends nothing.

## Endpoint map

Base: `https://mobile-v2.amientertainment.net/mobileserver/mobile/` (`--env qa|eng` for
AMI's test hosts). GET sends params as a query string, everything else as a JSON body. Auth
is two body fields, `playerId` and `authentication`, returned by login. Every response
carries `result`; 0 is success, others are named in `amiplay/api.py` (`RESULT_CODES`);
9 and 26 mean the session is dead.

| Area | Endpoints |
| --- | --- |
| account | `user/login`, `SSO/v2/login`, `user/logout`, `password/v2/reset`, `user/v2/get`, `user/fundsBalance`, `transaction/v3/get` |
| venues | `location/v3/search`, `location/v3/recent`, `favorites/locations/v3/get`, `favorites/locations/set`, `location/id/{id}`, `location/checkin`, `location/checkout`, `promo/v2/redeemCode` |
| jukebox | `device/get/{deviceId}`, `device/getPlayQueue/{deviceType}/{deviceId}` |
| catalog | `media/search`, `media/song/{id}`, `media/album/{id}` (songs), `media/albumdetails/{id}` (metadata), `media/v2/artist/{id}`, `menu/locationLists/v2/getMetadata`, `menu/locationLists/getData`, `media/featuredPlaylist/{id}`, `playlist/getplaylistdetails/venue` |
| yours | `media/getPlayerFavorites`, `favorites/songs/set`, `media/checkFavorites`, `playlist/getplaylists`, `playlist/getplaylistdetails`, `playlist/create`, `playlist/delete`, `playlist/{id}/add`, `playlist/{id}/update` |
| spend | `transaction/v4/purchase` |

Sorting: `sortOrder` asc/desc plus `sortBy` of the form `song.title`, `song.popularity`,
`song.trackOrder`, `album.title`, `album.releaseYear`. Artist and album listings reject a
missing sort, so the client always sends one.

Not implemented: payments (Braintree/Adyen/PayPal/Venmo flows; add funds in the app),
trivia and arcade, and the "Iris" live feed (a raw TCP socket on
`mobile-iris.amientertainment.net:1235` that pushes queue changes; `queue` polls the REST
endpoint instead).

## Layout

| Path | What |
| --- | --- |
| `bin/ami-play` | entry point |
| `amiplay/api.py` | `AmiClient`: transport, envelope, one method per endpoint, purchase pricing |
| `amiplay/store.py` | `Session`: the gitignored session file |
| `amiplay/cli.py` | argparse commands and table output |
| `secrets/` | session file (gitignored) |
| `../tests/test_amiplay.py` | request-shape tests through a fake transport |
