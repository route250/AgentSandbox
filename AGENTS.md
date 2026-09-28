# Agent Sandbox Manager

## Project overview
- FastAPI server code is in `app.py`.
- The manager UI is plain HTML, CSS, and JavaScript in `static/`.
- Runtime image data is stored under `images/` and `tmp/runtime/`; do not modify or remove user image data as part of UI work.

## UI conventions
- Keep the manager shell composed of a top menu bar, collapsible left menu, and main content area.
- Keep browser-facing labels in Japanese and the product title as `Agent Sandbox`.
- The create form may only send fields supported by the FastAPI API. Image IDs must comply with the server rule: 1–64 ASCII letters, digits, hyphens, or underscores, beginning with a letter or digit. Blank IDs request automatic naming.
- Show exactly these image states in Japanese: `停止中`, `起動中`, and `接続中`.
- A browser tab owns an image connection through its `sessionStorage` session ID. The server enforces one active owner per image; only that owner may use the HTTP/WebSocket proxy.
- The manager receives image status snapshots over a Server-Sent Events stream. Publish a snapshot immediately after image or connection state changes; do not add periodic client polling. The stream refreshes owned connection leases every 15 seconds and leases expire after 45 seconds without a live stream. Always release the current connection when navigating to another image or to the create page, and on page hide.
- Do not allow stopping an image while another session owns its connection.
- Preserve accessible labels, keyboard-operable buttons, and responsive behavior when changing the interface.
- Increment the static asset query version in `static/index.html` when changing cached CSS or JavaScript.

## Running locally
- Start the manager with `./scripts/run-app.sh` from the repository root. The default manager port is `3013`; set `MANAGER_PORT` to override it.
- The standalone sandbox launcher is `./scripts/image-cli.sh --id <image-id> --port <port>`.
