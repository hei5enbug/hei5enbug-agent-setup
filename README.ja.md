# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | **日本語** | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

AIコーディングエージェント向けのカスタムスキル集です。ホストごとに書き直すことなく、複数のエージェントホストでそのまま共有できるように作られています。

## 概要

プラグインに含まれる各スキルは `skills/` 配下にあり、手順・参照資料・スクリプトが一式まとまっています。
プラグインに含めないスキルは `standalone-skills/` 配下にあります。
同じ `SKILL.md` が、対応するすべてのホストで変更なしに動作します。

## 対応ホスト

- Claude Code
- Codex
- OpenCode（[Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) プラグイン使用）

## 構成

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── AGENTS.md
├── AGENTS.ko.md
├── CLAUDE.md
├── CLAUDE.ko.md
├── hooks/hooks.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       └── common.md
├── scripts/
│   ├── agent_guard.py
│   ├── datagrip_guard.py
│   ├── language_guard.py
│   ├── session_approval_guard.py
│   └── session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/
│   │   ├── scout.ko.md
│   │   └── worker.ko.md
│   ├── scout.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-scout.toml
│   └── codex-worker.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── orca-plugin-refresh/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

各プラグインスキルのフォルダは自身の `SKILL.md` と、必要な参照資料・スクリプトを保持しています。
プラグインマニフェストは、ホストごとのディレクトリにスキルをコピーせず、同じ `skills/` ディレクトリを Codex と Claude Code 向けにパッケージ化します。
`standalone-skills/` ディレクトリは、どちらのプラグインのスキル検出パスにも含まれません。

`agents/` ディレクトリは Claude Code プラグインに同梱されるため、バンドルをインストールすると
`hei5enbug-agent-setup:scout` と `hei5enbug-agent-setup:worker` サブエージェントが追加されます。手動コピーは不要です。
マニフェストはこの二つの英語定義だけを列挙するため、`agents/ko/` の韓国語訳はサブエージェントとして登録されません。

Codex はサブエージェントを `~/.codex/agents/` と `.codex/agents/` からのみ検出するため、プラグインでは登録できません。
代わりにセッションフックが、`~/.codex/agents/scout.toml` と `~/.codex/agents/worker.toml` がそれぞれ存在しない場合に
かぎり、`standalone-agents/codex-scout.toml` と `standalone-agents/codex-worker.toml` をその場所にコピーします。
これらのファイルは Claude Code と同じ名前の `scout` と `worker` エージェントを定義し、推論の強さとサンドボックスを
固定します。プラグインの `worker` は Codex 組み込みの `worker` を置き換え、`scout` は組み込みの `explorer` に手を
加えません。編集したファイルは決して上書きせず、次の Codex セッションから利用できます。編集したコピーは
更新されないため、モデルは指定せず、Codex の指示が起動のたびに固定モデルを渡します。フックは以前のバージョンが書き込んだ
`explorer.toml` を削除し `worker.toml` を置き換えますが、そのバージョンで配布したファイルとバイト単位で一致する場合に
かぎるため、編集したファイルは残ります。プラグインを無効にすると、インストール済みの `worker` ロールは編集を拒否せず、
通常の実装ワーカーとして動作します。

`PreToolUse` フックの `scripts/agent_guard.py` が、両方のホストで組み込みサブエージェントを防ぎます。Claude Code では、
種類を省略した呼び出しと、`general-purpose`、`Explore`、`Plan`、`claude`、フォークという組み込みの種類をすべて
拒否します。目的が限定された組み込みの `claude-code-guide` と `statusline-setup` は、プラグインのエージェントや、
ユーザー・プロジェクト・CLI・管理設定が提供する定義と同様に通過します。Codex では、種類を省略した呼び出し、`default`、
`explorer`、ロールファイルのない種類をすべて拒否し、プラグインのロールができる前の組み込み `worker` も拒否します。独立した読み取り専用の
ワーカーを求めるスキルは `scout` を使い、試行出力を書くスキルは別の `claude -p` または `codex exec` プロセスを実行します。

### 応答言語

言語ガードの `scripts/language_guard.py` は、すべての返信と進捗報告が応答言語で書かれているかを確認します。
Claude Code は `language` 設定から言語を決めます。ローカルプロジェクト設定、プロジェクト設定、ユーザー設定の順に読み、
設定がなければ何も強制しません。Codex は `HEI5ENBUG_RESPONSE_LANGUAGE` を読み、未設定なら韓国語を使います。
固有の文字体系を持つ言語だけを検査します。韓国語、日本語、中国語、ロシア語、ウクライナ語、ギリシャ語、アラビア語、
ヘブライ語、タイ語、ヒンディー語です。英語やフランス語など、それ以外の言語には指示だけが適用されます。

検査ではコード、引用、URL を除外します。文字のうち対象の文字体系が 30% 以上なら通過し、ごく短いテキストは常に通過します。
返信が通過しなければ `Stop` フックが書き直しを求め、1 ターンにつき最大 3 回までです。
別の言語で書かれた進捗報告の後には、`PostToolUse` フックがリマインダーを追加します。
ユーザーが別の言語で求めたテキストは、コードブロックまたは引用ブロックに入れてください。

### DataGrip クエリガード

`PreToolUse` フックと `PermissionRequest` フックの `scripts/datagrip_guard.py` は、DataGrip MCP ツール `execute_sql_query`
の実行前に動作します。ガードは `projectPath` が指す DataGrip プロジェクトの `.idea/dataSources.xml` から接続を読み取ります。名前に `승인`
を含む接続は常に承認を求めます。PostgreSQL と SQL Server の読み取りは承認なしで実行され、PostgreSQL
の読み取りは読み取り専用トランザクション内で実行されます。書き込み、ガードが分類できないクエリ、不明な接続、その他のデータベース種別は常に承認を求めます。ガードが呼び出しを拒否することはありません。Codex では `/hooks`
でこのフックを信頼してください。

任意で `pglast` パーサーを一度インストールできます。

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

パーサーがない場合、PostgreSQL はより厳格なテキスト検査に切り替わります。承認を求める頻度が増えることがありますが、承認なしで書き込みが実行されることはありません。

### セッション承認

Claude Code 専用のセッション承認ガード `scripts/session_approval_guard.py` は、外部に影響する特定の書き込み操作を、セッションごとに一度だけ承認すれば済むようにします。対象は、
git タグの作成、設定済みのリモートへのタグのプッシュ、タグとフラグ `--title`, `--notes`, `--target`, `--generate-notes`, `--notes-from-tag`,
`--latest`, `--draft`, `--prerelease`, `--verify-tag` だけを使う `gh release create` と `gh release edit`、
名前に書き込みを表す動詞を含む MCP ツールです。一度承認すると、そのセッションが終わるまで同じ種類の操作は確認なしで実行されます。ツールやコマンドの種類ごとに別々に承認します。

元に戻せない操作は常に承認を求めます。強制プッシュ、リモートブランチやタグの削除、タグの削除、`gh release delete`、`gh repo delete`、削除・ゴミ箱への移動・除去を行う MCP ツールが該当します。
`gh release upload` は任意のローカルファイルを公開できるため、常に承認を求めます。URL、一覧にないリモート、`--repo` へのタグのプッシュや、`--tags` のプッシュにブランチが混ざる場合、添付ファイル、
`--notes-file`、その他のフラグが付いた `gh release create` と `gh release edit` も同様です。ガードが確認できない部分を含む複合コマンドも常に承認を求めます。
サブエージェントは承認を引き継ぎません。承認はセッションとともに失効し、プラグインのデータディレクトリに保存されます。通常のプッシュとその他のコマンドは、従来どおりの権限フローのままです。

これらの操作に `permissions.ask` ルールを追加しないでください。ask ルールは、セッション承認の後でも毎回確認を求めます。

## プラグインのインストール

GitHub リポジトリからバンドルを一度インストールします。

### Codex

```bash
codex plugin marketplace add hei5enbug/hei5enbug-agent-setup --ref main
codex plugin add hei5enbug-agent-setup@hei5enbug
```

### Claude Code

```bash
claude plugin marketplace add hei5enbug/hei5enbug-agent-setup
claude plugin install hei5enbug-agent-setup@hei5enbug
```

## 指示の自動適用

macOS と Linux では、フックが `instructions/session/common.md` と現在のホスト用の
`codex.md` または `claude-code.md` を組み合わせます。
セッションの開始・再開・初期化・コンテキスト圧縮後と、サブエージェントの開始時に実行します。
`instructions/` の詳細は該当する操作の前だけに読み込みます。
ツール呼び出しの完了後と返信の終了時にも、言語ガードがそれぞれ `PostToolUse` と `Stop` で実行されます。
DataGrip クエリガードは `execute_sql_query` の実行前に `PreToolUse` と `PermissionRequest` で実行されます。
Claude Code では、セッション承認ガードが Bash と MCP ツールに対して `PreToolUse` と `PostToolUse` で実行されます。
`python3` で実行できる Python 3.12 以上と、フックの有効化が必要です。
Codex ではフックを信頼する承認も必要です。エージェントガード、言語ガード、DataGrip クエリガードなど、更新で追加されたフックは `/hooks` で信頼するまでスキップされます。
セッション承認ガードは Claude Code でのみ動作するため、この信頼手順は適用されません。
プラグイン更新後は新しいセッションを開始してください。
参照、エラー、制限の詳細は[英語の説明](README.md#automatic-instructions)を参照してください。

## プラグインの更新

2つのプラグインマニフェスト、`pyproject.toml`、`uv.lock` は同じセマンティックバージョンを使用します。
`HEAD` から到達できる最新の `v<version>` タグがリリースの基準です。基準の後の最初の変更が、同じコミットでこれらの
ファイルの次バージョンを決めます。これらのファイルにしかないバージョンは、すでに `main` にあっても計画中の次
バージョンなので、再度上げずに、その後の未公開の変更をすべてそこにまとめます。リリースではコミットを追加しません。
下記の開発チェックが `HEAD` ですべて通った後、`HEAD` に `v<version>` タグを付けてタグをプッシュします。

リリース公開後に Codex を更新します。

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

リリース公開後に Claude Code を更新します。

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

更新後は新しい Codex スレッドを開始するか Claude Code を再起動して、ホストに新しいスキルと指示を読み込ませます。

## 開発チェック

同梱スクリプトは PyYAML を入れた Python 3.12 以上を必要とし、Node テストには Node.js が必要です。
`.github/workflows/validate.yml` が macOS と Linux で実行する 3 つのチェックを、同じコマンドで実行します。

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
```

Orca CLI が必要なテストは、Orca がインストールされていない場合はスキップされるため、CI は Orca なしでも通過します。
Orca をインストールした後に `python3 -m pytest` を再実行すると、これらのテストも確認できます。

## 手順の言語

英語ファイルをスキル、参照資料、エージェント、セッション指示の実行可能な正本とします。
人が読む英語の Markdown ファイルには、同じ意味の韓国語 `.ko.md` を隣に置きます。
韓国語版は非正規の参考資料であり、実行時には読み込みません。原本と翻訳は一緒に変更、移動、削除します。
コード、スキーマ、テストデータ、生成物、英語以外の文書に韓国語の複製は不要です。
韓国語は、トリガー語句や出力例など対象言語データとしてのみ実行ファイルに残せます。

## スキル一覧

| スキル | 内容 |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | 複数セッションにわたる作業を意思決定チケットに分け、実装ルートが明確になるまでチケットを一つずつ解決します。 |
| [`deep-interview`](skills/deep-interview/SKILL.md) | 回答ごとに要件の曖昧さをスコアで測るソクラテス式インタビューを行い、そのスコアが閾値以下になるまで実行段階に進みません。[韓国語ガイド](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | SVG、HTML/CSS、Figma、draw.io のどのツールで作っても一つのデザインシステムのように見えるようにするフローチャート共通デザイン基準です。 |
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | 主張・数値・確信度をそのまま保ったまま既存の文章を自然に読めるよう書き直し、AIが書いたような韓国語も直します。[韓国語ガイド](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Markdown、HTML、PDF、DOCX、Google Docs を Confluence ページに変換し、文書構造と添付ファイルを保ち、以後の原本変更も同期します。 |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 下書き → テスト → レビュー → 改善のループを通じて、エージェントスキルを作成・検証・パッケージ化します。 |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | ステージ済みと未ステージの変更をまとめて、または指定した範囲を、直近のコミット履歴とともに読み取り、このリポジトリのスタイルに合ったコミットメッセージを5件提案します。コミットを依頼すると、最も適切な件名を1つ選んでそのままコミットします。 |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 開発設計ドキュメントを新しく書く、または整理する際のルールと、目次を段階的に絞り込む5ステップの手順です。[韓国語ガイド](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 現在のエージェントと相手側のClaude/Codexセッションが、交換回数を制限した議論を行い、論点を洗い出し収束させます。[韓国語ガイド](skills/tiki-taka/SKILL.ko.md) |

## 関連リンク

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) は独立したソースとして残り、
  プラグインのスキル一覧には含まれません。
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 独立したスキルがモデルルーティングを更新するプラグインシステム

## ライセンス

このリポジトリは Apache License 2.0 の下で公開されています。全文は [`LICENSE`](./LICENSE) を参照してください。
