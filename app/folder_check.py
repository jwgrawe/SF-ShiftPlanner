"""Who can open the app's files, outside the app (D122).

The login (D121) guards the app's pages. It can't guard the files: anyone who
can read the folder can copy the database and open it with any SQLite tool,
and anyone who can change the code can switch the login off. On Windows that
is decided by the folder's permissions – and a folder made directly under
C:\\ usually inherits «Godkjente brukere: endre», i.e. every user who can log
on to that PC.

This asks Windows for the folder's permission list (as SDDL, through
advapi32 with ctypes – nothing to install) and reports any entry that lets
a broad group (Alle, Godkjente brukere, Brukere, Interaktive, Domenebrukere,
Anonym) read or change it. Elsewhere than Windows it reports nothing.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Well-known broad groups, by SDDL alias and by SID.
BROAD = {
    "WD": "Alle (Everyone)", "S-1-1-0": "Alle (Everyone)",
    "AU": "Godkjente brukere (Authenticated Users)", "S-1-5-11": "Godkjente brukere (Authenticated Users)",
    "BU": "Brukere (Users)", "S-1-5-32-545": "Brukere (Users)",
    "IU": "Interaktive (Interactive)", "S-1-5-4": "Interaktive (Interactive)",
    "DU": "Domenebrukere (Domain Users)",
    "AN": "Anonym", "S-1-5-7": "Anonym",
}
DOMAIN_USERS = re.compile(r"^S-1-5-21-\d+-\d+-\d+-513$")

READ_CODES = {"GA", "GR", "FA", "FR"}
WRITE_CODES = {"GA", "GW", "FA", "FW", "WD", "WO", "SD"}
READ_BITS = 0x1 | 0x80000000 | 0x10000000            # FILE_READ_DATA, GENERIC_READ, GENERIC_ALL
WRITE_BITS = 0x2 | 0x4 | 0x40000000 | 0x10000000 | 0x40000 | 0x80000 | 0x10000   # write/append, generic, DAC, owner, delete


def _rights(text: str) -> tuple[bool, bool]:
    """(read, write) granted by an SDDL rights field."""
    if text.lower().startswith("0x"):
        mask = int(text, 16)
        return bool(mask & READ_BITS), bool(mask & WRITE_BITS)
    codes = {text[i:i + 2] for i in range(0, len(text), 2)}
    return bool(codes & READ_CODES), bool(codes & WRITE_CODES)


def broad_access(sddl: str) -> list[dict]:
    """The allow-entries in an SDDL string that open the folder (or the files
    in it) to a broad group: [{"group", "read", "write"}], merged per group."""
    found: dict[str, dict] = {}
    dacl = sddl.split("D:", 1)[1] if "D:" in sddl else ""
    dacl = dacl.split("S:", 1)[0]
    for ace in re.findall(r"\(([^()]*)\)", dacl):
        parts = ace.split(";")
        if len(parts) < 6 or parts[0] not in ("A", "OA"):
            continue
        flags, rights, sid = parts[1], parts[2], parts[5]
        inherit_only = "IO" in flags
        if inherit_only and "OI" not in flags:
            continue                                    # only reaches sub-folders, not files
        group = BROAD.get(sid) or ("Domenebrukere (Domain Users)" if DOMAIN_USERS.match(sid) else None)
        if group is None:
            continue
        read, write = _rights(rights)
        if not (read or write):
            continue
        entry = found.setdefault(group, {"group": group, "read": False, "write": False})
        entry["read"] |= read
        entry["write"] |= write
    return list(found.values())


def folder_sddl(path: Path) -> str:
    """The folder's permission list as SDDL (Windows only)."""
    import ctypes
    from ctypes import byref, c_void_p, c_wchar_p

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, SDDL_REVISION_1 = 1, 4, 1
    descriptor, dacl = c_void_p(), c_void_p()
    error = advapi32.GetNamedSecurityInfoW(c_wchar_p(str(path)), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                           None, None, byref(dacl), None, byref(descriptor))
    if error:
        raise OSError(error, f"GetNamedSecurityInfoW feilet ({error})")
    try:
        text = c_wchar_p()
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, SDDL_REVISION_1, DACL_SECURITY_INFORMATION, byref(text), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value or ""
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.LocalFree(descriptor)


def fix_command(folder: Path, account: str) -> str:
    """The icacls line that leaves the folder to the given account,
    Administratorer and SYSTEM (by SID, so it works on Norwegian Windows)."""
    return (f'icacls "{folder}" /inheritance:r /grant:r "{account}:(OI)(CI)F" '
            '"*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F"')


def status(root: Path, data: Path, account: str) -> dict | None:
    """None off Windows; else {"folder", "ok", "open", "error", "fix"} for the
    app folder (the code: whoever can change it can switch the login off) and
    the data folder (the database, imports and keys: whoever can read it has
    the data). "open" lists [{"where", "group", "read", "write"}]."""
    if os.name != "nt":
        return None
    out = {"folder": str(root), "ok": False, "open": [], "error": "", "fix": fix_command(root, account)}
    try:
        for where, folder in (("appmappen", root), ("datamappen", data)):
            if folder.exists():
                out["open"] += [{"where": where, **e} for e in broad_access(folder_sddl(folder))]
        out["ok"] = not out["open"]
    except OSError as exc:                              # pragma: no cover - Windows only
        out["error"] = str(exc)
    return out


def describe(entry: dict) -> str:
    what = "lese og endre" if entry["read"] and entry["write"] else "lese" if entry["read"] else "endre"
    return f"{entry['group']} kan {what} {entry.get('where', 'mappen')}"
