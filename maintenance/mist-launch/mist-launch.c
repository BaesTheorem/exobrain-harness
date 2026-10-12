/* mist-launch: exec the given program with its arguments, nothing else.
 *
 * Why it exists. launchd gives a job the TCC grants of the program its plist
 * DECLARES (Full Disk Access on /bin/bash is what lets the harness's scripts
 * under ~/Documents run), and Login Items labels the job after that program's
 * signing identity. Apple's bash and Homebrew's python carry no developer
 * identity, so the pane showed 43 rows named "bash" and 46 named "python".
 * Declaring every job through this one Team-signed binary, granted Full Disk
 * Access once, (1) groups them under MIST Console in Login Items via the
 * plist's AssociatedBundleIdentifiers, and (2) ends the TCC re-grants that
 * every Homebrew Python minor bump used to need (four since 2026-08).
 *
 * Build and install: maintenance/mist-launch/install.sh. Verified 2026-10-12
 * on macOS 26: the association only takes when the declared executable is
 * signed by the app's team.
 */
#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: mist-launch <program> [args...]\n");
        return 64;
    }
    execvp(argv[1], argv + 1);   /* PATH search, as launchd itself does for a bare program name */
    perror(argv[1]);
    return 126;
}
