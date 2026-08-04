# MiniMax-H3 Workspace requirements

## Runtime

- SGLang Ref2VA runs on 8 H100 GPUs at `127.0.0.1:30011`.
- FastAPI serves the API and built Vue application at `127.0.0.1:7861`.
- SQLite, assets and outputs live under `H3_DATA_ROOT`.
- The worker executes one generation at a time.

## Queue

- A running task is never preempted.
- Queued tasks sort by current user weight descending, then creation time ascending.
- Changing a user's weight immediately reorders that user's queued tasks.
- Users may cancel only queued tasks.
- Administrators may remove any task except one currently submitting or generating.

## Accounts

- The first visit creates the administrator.
- Administrators create, disable and reactivate users and set weights from 0 to 100.
- Passwords use `hashlib.scrypt` with per-password salts.
- Sessions use HTTP-only same-site cookies and CSRF tokens for writes.

## Media

- Images: up to 9, 25 MiB each.
- Videos: up to 3, 2-15 seconds each, 15 seconds total, 500 MiB each.
- Audio: up to 3, 2-15 seconds each, 15 seconds total, 200 MiB each.
- At most 12 references and 2 GiB per task.
- Audio cannot be the only reference.
- Assets and successful outputs are retained until an administrator removes their records.

## Frontend

- Vue Router routes: setup, login, create, jobs, job detail, assets, users, queue and system.
- Prompt references use `@图N`, `@视频N` and `@音频N` and compile to the SGLang canonical labels.
- Reordering references preserves the referenced asset identity.
- The interface supports desktop, 390 px mobile width, light mode and dark mode.
