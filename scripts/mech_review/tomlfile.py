"""The TOML data files the engine reads (adapter files, the stack plan, co-change rules): one loader and one key check,
so each file names its errors the same way. tomllib (python 3.11+) is imported only when a file is read, so a repo
without such a file runs on older pythons."""


def loads(raw, where, error, what):
    """the dict a TOML file's bytes hold. where names the file in errors (a path, and the commit it is read at); error
    is the exception class raised, naming why; what is the file in the message for an old python ("an adapter file")."""
    try:
        import tomllib
    except ImportError:
        raise error(f"{where}: reading {what} needs python 3.11 or newer (tomllib)") from None
    try:
        # a UTF-8 BOM (some Windows editors write one) is not part of the TOML text
        return tomllib.loads((raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).decode("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise error(f"{where}: not valid TOML: {e}") from None
    except UnicodeDecodeError as e:  # tomllib decodes the bytes as UTF-8 and lets this through
        raise error(f"{where}: not valid TOML: not UTF-8 ({e.reason} at byte {e.start})") from None
    except RecursionError:  # tomllib nests one python frame per array or inline table
        raise error(f"{where}: not valid TOML: arrays or tables nested too deep") from None


def keys(d, field, allowed, required, err):
    """d's keys are among allowed and hold every one of required; else err(the key's dotted name, why). field: the
    table's dotted name, "" for the top level (its keys are named bare)."""
    for k in d:
        if k not in allowed:
            err(f"{field}.{k}" if field else k, "unknown key")
    for k in required:
        if k not in d:
            err(f"{field}.{k}" if field else k, "missing")
