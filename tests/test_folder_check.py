"""The folder-permission check (D122) reads Windows' SDDL; the parsing is
tested here with permission lists as Windows writes them."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import folder_check as fc  # noqa: E402

# A folder made by a user directly under C:\ (inherits from the C:\ root).
UNDER_C = ("O:S-1-5-21-1-2-3-1001G:S-1-5-21-1-2-3-513D:AI(A;ID;FA;;;BA)(A;OICIIOID;GA;;;BA)(A;ID;FA;;;SY)"
           "(A;OICIIOID;GA;;;SY)(A;OICIID;0x1200a9;;;BU)(A;ID;0x1301bf;;;AU)(A;OICIIOID;SDGXGWGR;;;AU)"
           "(A;OICIIOID;GA;;;CO)")
# The same folder after the recommended icacls line.
LOCKED = "D:PAI(A;OICI;FA;;;S-1-5-21-1-2-3-1001)(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"


class FolderCheckTest(unittest.TestCase):
    def test_a_folder_under_c_is_open_to_every_user_of_the_pc(self):
        found = {e["group"]: e for e in fc.broad_access(UNDER_C)}
        self.assertEqual(set(found), {"Brukere (Users)", "Godkjente brukere (Authenticated Users)"})
        self.assertEqual((found["Brukere (Users)"]["read"], found["Brukere (Users)"]["write"]), (True, False))
        au = found["Godkjente brukere (Authenticated Users)"]
        self.assertEqual((au["read"], au["write"]), (True, True))
        self.assertEqual(fc.describe(au | {"where": "datamappen"}),
                         "Godkjente brukere (Authenticated Users) kan lese og endre datamappen")

    def test_the_locked_folder_is_clean(self):
        self.assertEqual(fc.broad_access(LOCKED), [])

    def test_what_does_not_count(self):
        # deny entries, sub-folder-only inheritance, list-only rights, specific accounts
        self.assertEqual(fc.broad_access("D:(D;OICI;FA;;;WD)(A;CIIO;FA;;;AU)(A;;LC;;;AU)(A;OICI;FA;;;S-1-5-21-9-9-9-1500)"), [])

    def test_domain_users_and_everyone_by_sid(self):
        groups = {e["group"] for e in fc.broad_access("D:(A;OICI;FR;;;S-1-5-21-7-8-9-513)(A;;0x80000000;;;S-1-1-0)")}
        self.assertEqual(groups, {"Domenebrukere (Domain Users)", "Alle (Everyone)"})

    def test_the_fix_uses_sids_not_localised_names(self):
        cmd = fc.fix_command(Path("C:/Planlegger"), "domene\\kari")
        self.assertIn("/inheritance:r", cmd)
        self.assertIn('"domene\\kari:(OI)(CI)F"', cmd)
        self.assertIn("*S-1-5-32-544", cmd)
        self.assertIn("*S-1-5-18", cmd)

    def test_nothing_to_report_off_windows(self):
        if fc.os.name != "nt":
            self.assertIsNone(fc.status(Path("."), Path("."), "x"))


if __name__ == "__main__":
    unittest.main()
