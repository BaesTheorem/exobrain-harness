"""Feature modules for the MIST Discord bot.

Each module exposes a top-level `setup(ctx)` that registers commands and
event handlers on ctx.handler. bot.py discovers and loads every module in
this package at startup (the clean equivalent of Fletcher's autoload loop).
"""
