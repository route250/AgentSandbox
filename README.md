# OpenCode Sandbox Manager

FastAPI の管理画面を起動する。

```bash
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 3000
```

ブラウザーで `http://127.0.0.1:3000` を開く。

画面で作成したイメージは `images/<image-id>/fs` に保存する。

OpenCode の起動中メタデータとログは `.runtime/` に保存する。

`start.sh` は次の形式で単独起動にも使用できる。

```bash
./start.sh --id <image-id> --port <port>
```
