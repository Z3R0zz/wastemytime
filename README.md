# wastemytime

local daemon that monitors my Metropolia student inbox so i don't have to

because after 4 years of professional software engineering i still need a university to teach me how to `git checkout -b`. two years into the degree. revolutionary stuff

## why this exists

Metropolia sends a lot of emails. most of them are noise. career fairs for people who don't have careers yet, internship offers for people who already have jobs, newsletters that could've just been `/dev/null`

the ones that actually matter, exam dates, deadlines, thesis stuff are buried under 47 emails about a hackathon sponsored by some consulting firm you've never heard of, or fuck if i know if they send hackathon emails. i don't read them anyways.

so instead of reading any of it i wrote a daemon that reads it for me, classifies it with a local LLM, and pings me only when something actually matters. the rest goes where it belongs

## things my university has taught me that i already knew

- **git branching.** in year two. i've been making PRs professionally since before some of my classmates had GitHub accounts. the course dedicated an entire week to `git merge`. a week
- **scrum.** we had a lecture about stand-ups. i have stood up in like a thousand stand-ups. but sure let me write a reflection paper about the Agile Manifesto
- **how to make a pull request.** the professor showed us the green button on GitHub. i mass-produce these daily at work but thanks for the guided tour i guess

## setup

### 1. pull the AI model

```bash
ollama pull qwen2.5:14b-instruct
```

### 2. install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. configure

```bash
cp config.example.yaml config.yaml
chmod 600 config.yaml
```

edit `config.yaml` - set your Metropolia username (short-form, like `doejohn@metropolia.fi`). adjust the `profile` section if your situation is different from mine (probably isn't if you're using this)

### 4. store your password

```bash
python main.py --set-password
```

stores your IMAP password in the system keyring. not in a yaml file. not in a git repo. not in a Confluence page titled "passwords (DO NOT SHARE)"

no system keyring? env var works too:

```bash
export WASTEMYTIME_PASSWORD="your_password"
```

### 5. run it

```bash
python main.py
```

### 6. install the cli wrapper (optional)

lets you run `wastemytime` from anywhere instead of activating the venv and cd-ing into the project

```bash
ln -sf $(pwd)/wastemytime ~/.local/bin/wastemytime
```

make sure `~/.local/bin` is in your PATH (it probably already is)

## usage

```
wastemytime                      # check inbox now
wastemytime --daemon             # poll every 15min, weekly digest on mondays
wastemytime --digest             # generate weekly digest
wastemytime --deadlines          # print upcoming deadlines which you will miss anyway
wastemytime --dismiss 42         # dismiss a tracked item
wastemytime --status             # show stats
wastemytime --set-password       # store/update IMAP password
```

or if you didn't do step 6, `python main.py` from the project dir with the venv active works the same

## run as a systemd service

the systemd service can't access your desktop session's keyring so it needs the password via env file:

```bash
echo 'WASTEMYTIME_PASSWORD=your_password_here' > ~/.wastemytime_env
chmod 600 ~/.wastemytime_env
```

then install the service:

```bash
cp wastemytime.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now wastemytime

# logs
journalctl --user -u wastemytime -f
```

## how it works

connects to `imap.metropolia.fi` (read-only, never marks anything as read), feeds each email to a local Ollama model with your profile context, classifies it:

- **critical** - needs action or deadline within 7 days
- **important** - worth knowing, not urgent
- **noise** - career fairs, recruiter spam, newsletters, "opportunities"

important and critical stuff gets saved to a local SQLite DB and written to `~/school_deadlines.md`. desktop notifications fire via `notify-send` when the AI is confident enough

job fairs and career events are hardcoded as noise. no exceptions. i have a job. oh and i never read any internship related emails so could anyone let me know when i should let my school know that i am doing the mandatory internship for my degree right now? no clue how that process even works, but i assume it's important. thanks
