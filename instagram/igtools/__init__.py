"""igtools: read-only Instagram toolkit backing the `ig` CLI.

Borrows the logged-in browser session (exported cookies) and reads the same
private web endpoints the instagram.com front end calls. Never writes: no
likes, follows, comments, or DMs.
"""
