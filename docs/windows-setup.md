# Working on this repo from Windows

The Mac is home base (Conductor is Mac-only). Windows is a second desk:
pull, work, push. GitHub is the only sync between the two. The bot itself
runs on GitHub Actions, so neither computer has to be on for it to trade.

## Before anything: stop the old Windows bot

The bot used to run on Windows from Task Scheduler (`run_silent.vbs`,
`summary_silent.vbs`, folder `C:\Users\Daniel\OneDrive\Documents\claude trading`).
If those tasks still exist, a second, outdated bot trades the same paper
account alongside GitHub Actions.

- [ ] Open Task Scheduler (or run `schtasks /query /fo list | findstr /i "wheel silent"`)
      and disable or delete any task that runs `run_silent.vbs` or `summary_silent.vbs`.
- [ ] Leave the old OneDrive folder alone or archive it. Don't work in it.

## One-time setup

- [ ] Install Git for Windows, Python 3.10+ (tick "Add to PATH"), and Node.js
      (only needed for the Wheel Lab tests).
- [ ] Clone outside OneDrive, Dropbox or iCloud. Cloud drives corrupt `.git`.
      ```powershell
      cd $HOME\projects
      git clone https://github.com/danielkwon7607-del/wheelagent "wheel strategy"
      cd "wheel strategy"
      ```
- [ ] Bot venv:
      ```powershell
      python -m venv .venv
      .venv\Scripts\activate
      pip install -r requirements.txt
      pytest
      ```
- [ ] Copy the secrets over by hand (never commit them, never put them in a cloud drive):
      - `.env.paper`: Alpaca paper keys (`.env.example` shows the format)
      - `.env.trigger`: only if you'll run `setup_trigger.py` from Windows
- [ ] Research venv, only if you'll run research or rebuild Lab data:
      ```powershell
      python -m venv research\.venv
      research\.venv\Scripts\pip install -r research\requirements.txt
      ```
- [ ] Rebuild the gitignored data, only if you need it (see `lab/README.md`).
      Run `research\.venv\Scripts\python research\fetch_data.py`, then
      `research\prefetch.py`, then `lab\build_data.py`.

## Every session

- [ ] Start: `git pull`.
- [ ] Work on a branch, not `main`. Bot code on `main` goes live on the next run.
- [ ] Finish: commit and `git push`, then `git pull` on the Mac before working there.
- [ ] Don't have agents on the same branch on both machines at once.

## What doesn't follow you

- Secrets and data files (above).
- Claude's personal memory (kept in the home folder on each machine). The
  project memory in `.kiln/index.md` is committed, so it does follow you.
- Uncommitted or unpushed work on the other machine.
