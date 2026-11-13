# Security: what the login protects, and what it doesn't (D122)

## Short version

- The **login** (D121) protects the app's *pages*. It stops another Windows
  user on the same PC from opening the administration in a browser (the app
  listens on `localhost`, which every session on that PC shares). It also
  records **who** did what in the log. Later, if the board or the app is
  opened on the internal network, the login becomes the main barrier.
- The login does **not** protect the *files*. Anyone who can read the app's
  folder can copy `data\sf_planlegger.db` and open it with any SQLite tool.
  Anyone who can change the code can switch the login off. Windows' folder
  permissions decide that, not the app.
- A folder made directly under `C:\` (such as `C:\Planlegger`) usually
  inherits **«Godkjente brukere: endre»**. That means every employee who can
  log on to that PC can read and change everything in it. Without tightening
  the folder, the login gives a false sense of security. Tightening the
  folder makes the login meaningful.

## What to do (once, takes a minute)

1. Look under Administrasjon → Tilgang → «Filene på PC-en». The app reads the
   folder's permissions and says whether broad groups (Alle, Godkjente
   brukere, Brukere, Domenebrukere) can reach it. It also warns at startup.
2. If they can: close the app, open a terminal and run the line the page
   shows. It is filled in with the account running the app:

   ```
   icacls "C:\Planlegger" /inheritance:r /grant:r "DOMENE\bruker:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F"
   ```

   This removes the inherited entries and grants access to that account,
   the PC's administrators (IT) and SYSTEM only. It uses SIDs, so it works on
   Norwegian Windows. You don't need administrator rights if you created the
   folder yourself.
3. Some other managers start the app or put HR exports in `data\import` from
   their own Windows account. Add each of them:
   `icacls "C:\Planlegger" /grant "DOMENE\bruker:(OI)(CI)M"`. Better still,
   ask IT for a group for the managers and grant that group once.
4. Ask IT to confirm that the PC's disk is encrypted with **BitLocker**
   (standard on hospital PCs). That covers a stolen PC or disk.

IT (local administrators) can always reach the files. That is normal and
can't be prevented from inside an app.

## Why not encrypt the database?

Encryption needs a key. The app must be able to start without someone
typing a password each time, so the key would live on the same PC, in a
place the app's Windows account can read. Anyone who can read that place
can decrypt, so it amounts to the same protection as the folder permissions,
plus new ways to lose data:

- A lost key means lost data.
- Another manager's account can't open the data.
- It needs an extra package (SQLCipher) that must be installed on a locked
  PC.

Tying the key to the Windows account (DPAPI) or using Windows' own file
encryption (EFS) gives about the same result as step 2, with more moving
parts. **Folder permissions plus BitLocker** is the simple, sufficient
combination. We can revisit this if the data ever moves to a shared drive
or server.

## What counts as personal data here

- The database (names, shifts, absences, including the absence type
  «Syk», and competencies)
- `data\import\` with `arkiv\` and `avvist\`
- `data\private\` (including the anonymiser key)
- The log, which is in the database

None of it is ever committed: the repository is public (D78), and
`.gitignore` covers it. Data older than 92 days is deleted automatically
(D94).

## Tracking who did what

Every change made through the administration is logged with the name of the
logged-in administrator: imports, plans, rules, competencies, access. Each
log panel shows these entries. Logins and logouts are logged too. Changes
made while access was still open (before the first administrator was added)
show no name.
