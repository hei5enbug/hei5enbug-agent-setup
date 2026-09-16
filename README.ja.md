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
├── scripts/session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/scout.ko.md
│   └── scout.md
├── standalone-agents/
│   └── codex-explorer.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── document-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

各プラグインスキルのフォルダは自身の `SKILL.md` と、必要な参照資料・スクリプトを保持しています。
プラグインマニフェストは、ホストごとのディレクトリにスキルをコピーせず、同じ `skills/` ディレクトリを Codex と Claude Code 向けにパッケージ化します。
`standalone-skills/` ディレクトリは、どちらのプラグインのスキル検出パスにも含まれません。

`agents/` ディレクトリは Claude Code プラグインに同梱されるため、バンドルをインストールすると
`hei5enbug-agent-setup:scout` サブエージェントが追加されます。手動コピーは不要です。

Codex はサブエージェントを `~/.codex/agents/` と `.codex/agents/` からのみ検出するため、プラグインでは登録できません。
代わりにセッションフックが、`~/.codex/agents/explorer.toml` が存在しない場合にかぎり
`standalone-agents/codex-explorer.toml` をその場所に書き込みます。このファイルは Codex 組み込みの `explorer` を
上書きし、推論の強さと読み取り専用サンドボックスを固定します。既存の `explorer.toml` は決して上書きせず、
次の Codex セッションから利用できます。モデルは指定しないためホストの既定モデルを引き継ぎ、
Claude Code の `scout` がモデルを一つに固定する点とは異なります。

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
`python3` で実行できる Python 3.12 以上と、フックの有効化が必要です。
Codex ではフックを信頼する承認も必要です。プラグイン更新後は新しいセッションを開始してください。
参照、エラー、制限の詳細は[英語の説明](README.md#automatic-instructions)を参照してください。

## プラグインの更新

2つのプラグインマニフェスト、`pyproject.toml`、`uv.lock` は同じセマンティックバージョンを使用します。
下記の開発チェックがすべて通った後、リリースを公開する前にまとめて更新します。

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
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | 内容はそのままに、AIが書いたような韓国語の文章を人が書いたように自然な韓国語へ書き直します。[韓国語ガイド](skills/humanize-korean/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Markdown、HTML、PDF、DOCX、Google Docs を Confluence ページに変換し、文書構造と添付ファイルを保ち、以後の原本変更も同期します。 |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 下書き → テスト → レビュー → 改善のループを通じて、エージェントスキルを作成・検証・パッケージ化します。 |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | ステージ済みと未ステージの変更をまとめて、または指定した範囲を、直近のコミット履歴とともに読み取り、このリポジトリのスタイルに合ったコミットメッセージを5件提案します。 |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 開発設計ドキュメントを新しく書く、または整理する際のルールと、目次を段階的に絞り込む5ステップの手順です。[韓国語ガイド](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 現在のエージェントと相手側のClaude/Codexセッションが、交換回数を制限した議論を行い、論点を洗い出し収束させます。[韓国語ガイド](skills/tiki-taka/SKILL.ko.md) |

## 関連リンク

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) は独立したソースとして残り、
  プラグインのスキル一覧には含まれません。
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 独立したスキルがモデルルーティングを更新するプラグインシステム

## ライセンス

このリポジトリは Apache License 2.0 の下で公開されています。全文は [`LICENSE`](./LICENSE) を参照してください。
