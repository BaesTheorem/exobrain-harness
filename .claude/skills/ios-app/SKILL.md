---
name: ios-app
description: Build, sign, install, and debug iOS (and companion macOS) apps from the command line -- Xcode setup, XcodeGen projects, xcconfig, code signing, device pairing via devicectl, build-log forensics, vendored-framework inspection, and Xcode-free macOS builds with raw swiftc. Use when the user mentions Xcode, an iOS/iPhone app build, a Swift app project, code signing, provisioning, sideloading, a simulator, devicectl, XcodeGen, an .xcodeproj/.xcconfig, "put it on my phone", TestFlight prep, or a build/install failure on an Apple platform. Battle-tested on the Plaud companion app (Plaud-dev repo).
---

# iOS App Development (CLI-first)

Workflows and hard-won gotchas for driving Apple-platform development from the
terminal, without babysitting the Xcode GUI. Everything here was verified live
on this Mac (Xcode 26.x, macOS 26) building the Plaud One companion app
(`~/Documents/Plaud-dev/ios/PlaudOneCompanion`, see its README and
`scripts/build-ios.sh` / `scripts/build-macos.sh` for working examples).

## Toolchain setup

**Xcode vs Command Line Tools.** The CLT alone cannot build iOS apps (no
iPhoneOS SDK), but it CAN typecheck Swift and build full macOS apps (see the
desktop section). Check what's active: `xcode-select -p`.

**Use DEVELOPER_DIR instead of xcode-select.** Switching the active developer
dir globally needs sudo; a per-command env var does not:

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild -version
```

Export it once per script. Every `xcrun`/`xcodebuild` below assumes it.

**Installing Xcode headlessly mostly fails.** `mas install 497799835` demands
a sudo password (non-starter in a non-interactive session) and App Store GUI
downloads stall silently (watch `/Applications/Xcode.appdownload` size; if it
sits still for 6+ minutes, the store is waiting on a click or Apple ID prompt;
`open "macappstore://apps.apple.com/app/id497799835"` surfaces the page). Plan
for the user to click Install themselves.

**Xcode ships without the iOS platform.** First build attempts fail with
"iOS X.Y is not installed. Please download and install the platform." Fix:

```bash
xcodebuild -downloadPlatform iOS      # ~8.5 GB, includes simulator runtime
xcodebuild -runFirstLaunch            # registers components
```

Gotchas proven the hard way:
- A killed `-downloadPlatform` leaves a half-registered state: the SDK shows
  in `xcodebuild -showsdks` but destinations still error. Re-run the download.
- Session restarts kill background children. For multi-GB downloads, detach:
  `nohup env DEVELOPER_DIR=... xcodebuild -downloadPlatform iOS > /tmp/dl.log 2>&1 & disown`
  and poll the log. It survives anything short of a reboot.
- The device platform can register (destinations resolve) while the simulator
  runtime is still installing; device builds work at that point.
- Progress lines in the log are \r-separated: `tail -c 4000 | tr '\r' '\n'`.

## Project generation: XcodeGen

Prefer `project.yml` + `xcodegen generate` over a committed `.xcodeproj`
(gitignore the generated project). Critical consequence: **anything set in the
Xcode GUI is wiped on the next regenerate.** Signing teams, capabilities,
build settings changed by clicking must be persisted into `project.yml` or an
xcconfig, or they silently vanish.

Pattern that works: a gitignored `Config/PartnerConfig.xcconfig` (with a
committed `.example`) holding per-machine and secret-adjacent settings
(backend hosts, `DEVELOPMENT_TEAM`, `CODE_SIGN_STYLE = Automatic`), wired in
project.yml via `configFiles:`. Harvest a GUI-set team with:

```bash
grep -o "DEVELOPMENT_TEAM = [A-Z0-9]*" *.xcodeproj/project.pbxproj | head -1
```

**xcconfig gotchas:** a literal `//` starts a comment, so URLs with schemes
cannot be stored (store bare hosts, add the scheme in code). Values pass into
the app via Info.plist `$(VAR)` substitution.

## Hand-authored Info.plist

With `GENERATE_INFOPLIST_FILE: NO`, the plist MUST contain
`CFBundleExecutable` (`$(EXECUTABLE_NAME)`) and should contain
`CFBundlePackageType` (`APPL`). Missing CFBundleExecutable compiles and signs
fine, then fails at install with `MissingBundleExecutable` (MIInstallerError
11). Also remember usage-description keys for any capability touched
(`NSBluetoothAlwaysUsageDescription` etc.); missing ones crash on first use.
For dev against a plain-http local backend, add ATS
`NSAppTransportSecurity > NSAllowsLocalNetworking = true`.

## Building from the CLI

Compile check without signing (proves code + SDK linkage, no Apple ID needed):

```bash
xcodebuild -project App.xcodeproj -scheme App \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build/dd CODE_SIGNING_ALLOWED=NO build
```

Signed device build: same but `-allowProvisioningUpdates`,
`DEVELOPMENT_TEAM=<id>`, `CODE_SIGN_STYLE=Automatic`.

Signing identity check: `security find-identity -v -p codesigning`. Zero
identities means the Apple ID was never added to Xcode on this machine; that
step is GUI-only (Xcode > Settings > Accounts, needs the user's password/2FA).
A free personal team signs 7-day sideloads; distribution needs the paid
program.

## Vendored binary frameworks

Interrogate before trusting:

```bash
file FW.framework/FW                    # "ar archive" = STATIC: link, don't embed
lipo -info FW.framework/FW              # arch slices
ls FW.xcframework/                      # slice dirs, e.g. ios-arm64 only
```

- Static frameworks (`ar archive`): `embed: false` in project.yml. Embedding
  a static lib wastes space and can break validation.
- Device-only (arm64, no simulator slice): simulator builds FAIL with
  "cannot find Swift declaration" errors (canImport passes via the ObjC
  module, then Swift symbols are missing). Guard SDK code with
  `#if canImport(Module)` and accept that the simulator runs a UI shell only;
  build for a real device to exercise the SDK.
- The full public API lives in
  `FW.framework/Modules/FW.swiftmodule/arm64-apple-ios.swiftinterface` and the
  generated `Headers/FW-Swift.h`. Grep these for real signatures instead of
  guessing; diff two vendored copies of an SDK with sorted grep of
  `public (func|var)` lines.

## Device pairing + install (devicectl)

```bash
xcrun devicectl list devices                       # pairing state
xcrun devicectl device install app --device <UDID> path/to/App.app
xcrun devicectl device info apps --device <UDID>   # verify installed
xcrun devicectl device process launch --device <UDID> <bundle-id>
```

Pairing sequence for a fresh phone: data cable (not charge-only), unlock,
Trust This Computer, then Settings > Privacy & Security > Developer Mode > on
(reboots; the toggle only appears after first Xcode contact). State
`connected (no DDI)` means developer support isn't loaded yet; give Xcode's
Devices window time to prepare. First launch of a personal-team app needs
Settings > General > VPN & Device Management > Trust.

**Local backend for on-device testing:** the phone cannot reach the Mac's
`127.0.0.1`; bind the server to `0.0.0.0`, point the app at the Mac's LAN IP
(`ipconfig getifaddr en0`), and keep phone + Mac on the same WiFi.

## Build-log forensics

Xcode GUI build logs are gzipped SLF0 files; readable enough for grep:

```bash
log=$(ls -t ~/Library/Developer/Xcode/DerivedData/<App>-*/Logs/Build/*.xcactivitylog | head -1)
gunzip -c "$log" | strings | grep -iE "error:|signing|provision" | sort -u | head
```

This answers "the build failed :(" without asking the user to copy anything.
Install failures land in the error the GUI shows (MIInstallerErrorDomain
codes); compile failures show as normal `path:line: error:` lines.

## macOS desktop builds without Xcode

A SwiftUI iOS codebase with no UIKit imports compiles as a native macOS app
using only the CLT; invaluable for end-to-end testing app logic before
Xcode/devices are available. Recipe (working example:
`Plaud-dev/scripts/build-macos.sh`):

1. `xcrun --sdk macosx swiftc -swift-version 5 -parse-as-library
   -target arm64-apple-macos13.0 -O -o Out.app/Contents/MacOS/Name <sources>`
2. Hand-write `Contents/Info.plist` (CFBundleExecutable, CFBundleIdentifier,
   usage descriptions, config values baked in since there's no xcconfig
   substitution).
3. `codesign --force --sign - Out.app` (ad-hoc is enough locally; TCC
   permission prompts like Bluetooth need the bundle + usage strings).

Platform notes: `LabeledContent` needs macOS 13 / iOS 16; guard iOS-only bits
with `#if os(iOS)`; device-only vendored SDKs drop out via canImport and can
be replaced by native equivalents (e.g. CoreBluetooth) behind `#if os(macOS)`.

Fast pre-Xcode validation of the whole tree (no SDK frameworks involved):

```bash
swiftc -typecheck -swift-version 5 Sources/**/*.swift
```

## Simulators (when they apply)

```bash
xcrun simctl list devices available
xcrun simctl boot <UDID> && xcrun simctl install <UDID> App.app
xcrun simctl launch <UDID> <bundle-id>
```

Remember: new iOS runtimes ship only current-generation device models, and
none of it matters for device-only vendored SDKs (UI shell only).

## Debugging device connect issues (BLE apps)

A BLE peripheral holds one connection. If a vendor's official app is
installed on the same phone it will auto-connect in the background and steal
the device; force-quit it (and any Mac app holding the link) and power-cycle
the peripheral before blaming the code. Read SDK status codes from the
delegate callbacks and map them before guessing (connect-state vs bind-status
enums differ).
