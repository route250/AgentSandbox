# Agent Sandbox Manager

Bubblewrap で隔離した OpenCode イメージを作成・起動・接続するための FastAPI 管理画面です。

## 必要な環境

- Linux
- Python 3.11 以降
- `bubblewrap`（`bwrap`）
- `~/.opencode/bin/opencode`
- OpenCode が参照するモデル設定と接続先

依存パッケージをインストールします。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 管理画面を起動する

リポジトリのルートで実行します。

```bash
./scripts/run-app.sh
```

標準ポートは `3013` です。ブラウザーで次のURLを開きます。

```text
http://127.0.0.1:3013/manager/
```

別のポートを使う場合は `MANAGER_PORT` を指定します。

```bash
MANAGER_PORT=31013 ./scripts/run-app.sh
```

`run-app.sh` は `agent_sandbox.app:app` を Uvicorn で起動し、外部からの接続を受け付けます。リモートホストで起動した場合は、`127.0.0.1` をそのホストのアドレスに置き換えてください。

## 画像の使い方

管理画面からイメージを作成し、起動して接続します。イメージIDは英数字、`-`、`_` を使用でき、先頭は英数字にします。長さは1〜64文字です。

起動中のイメージには管理画面が `18100`〜`18199` のポートから空きを割り当てます。停止・起動・接続の管理は管理画面から行ってください。

## CLIで直接起動する

既存のイメージを指定して、管理画面を経由せず起動できます。

```bash
./scripts/image-cli.sh --id <image-id> --port <port>
```

新しいイメージ領域を作成して起動する場合は `--create` を指定します。

```bash
./scripts/image-cli.sh --id <image-id> --port <port> --create
```

## ディレクトリ構成

```text
agent_sandbox/                 FastAPIアプリケーションと静的ファイル
base/_sbox/                    サンドボックス起動用ファイル
base/skel/                     ホームディレクトリ初期化用の追加設定
profile/opencode/              OpenCodeプロファイル
scripts/run-app.sh             管理画面の起動スクリプト
scripts/image-cli.sh           サンドボックスの起動スクリプト
images/<image-id>/fs/          イメージごとのホームディレクトリ
tmp/runtime/                   起動中イメージのメタデータ
logs/                          イメージごとの起動ログ
```

`images/`、`tmp/`、`logs/` は実行時に作成されます。
