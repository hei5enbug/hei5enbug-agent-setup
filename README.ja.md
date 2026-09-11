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
├── LICENSE
├── pyproject.toml
├── standalone-agents/
│   ├── scout.md
│   └── codex-explorer.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── confluence-ops/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

各プラグインスキルのフォルダは自身の `SKILL.md` と、必要な参照資料・スクリプトを保持しています。
プラグインマニフェストは、ホストごとのディレクトリにスキルをコピーせず、同じ `skills/` ディレクトリを Codex と Claude Code 向けにパッケージ化します。
`standalone-skills/` ディレクトリは、どちらのプラグインのスキル検出パスにも含まれません。

`standalone-agents/` ディレクトリには、`CLAUDE.md` と `AGENTS.md` が名前で参照するサブエージェント定義があります。
`scout.md` は手動で `~/.claude/agents/` にコピーします。`codex-explorer.toml` は `~/.codex/agents/explorer.toml` にコピーします。
このファイルは Codex 組み込みの `explorer` を上書きし、推論の強さと読み取り専用サンドボックスを固定します。モデルは指定しないため
ホストの既定モデルをそのまま引き継ぎます。Claude Code の `scout` がモデルを一つに固定する点とは異なります。
どちらもプラグインバンドルの外に置くので、プラグインをインストールしてもサブエージェントは追加されません。

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

## プラグインの更新

2 つのプラグインマニフェストと `pyproject.toml` は同じセマンティックバージョンを持ち、現在の値は `0.2.0` です。
リリースを公開する前に、下記の開発チェックがすべて通ることを確認してから、`.codex-plugin/plugin.json`、
`.claude-plugin/plugin.json`、`pyproject.toml` のバージョンを一緒に上げます。

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

更新後は新しい Codex スレッドを開始するか Claude Code を再起動して、ホストに新しいスキルバージョンを読み込ませます。

## 開発チェック

同梱スクリプトは PyYAML を入れた Python 3.12 以上を必要とし、Node テストには Node.js が必要です。
`.github/workflows/validate.yml` が macOS と Linux で実行する 3 つのチェックを、同じコマンドで実行します。

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/markdown-to-confluence/tests/test_render_diagrams.mjs
```

## 手順の言語

エージェントが実行するスキル手順は英語で書かれています。スキルディレクトリ内の `README.ko.md` は、対応する英語文書と
同期して保たれる非正規の韓国語訳です。人が読むためのものであり、エージェントがスキル実行中に読み込んだり使ったりしてはいけません。
実行ファイル内の韓国語は、トリガー語句、例、必須の出力ラベル、評価用データのように韓国語そのものが対象データである場合にだけ残します。

## スキル一覧

| スキル | 内容 |
|---|---|
| [`confluence-ops`](skills/confluence-ops/SKILL.md) | Confluence作業のハウスルール: 汎用ツールではなく `confluence-cli` を選び、認証情報をコマンドラインに出さず、コメントのマークアップとメンションを正しく扱います。 |
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | 複数セッションにわたる作業を意思決定チケットに分け、実装ルートが明確になるまでチケットを一つずつ解決します。 |
| [`deep-interview`](skills/deep-interview/SKILL.md) | 回答ごとに要件の曖昧さをスコアで測るソクラテス式インタビューを行い、そのスコアが閾値以下になるまで実行段階に進みません。[韓国語ガイド](skills/deep-interview/README.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | SVG、HTML/CSS、Figma、draw.io のどのツールで作っても一つのデザインシステムのように見えるようにするフローチャート共通デザイン基準です。 |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | 内容はそのままに、AIが書いたような韓国語の文章を人が書いたように自然な韓国語へ書き直します。[韓国語ガイド](skills/humanize-korean/README.ko.md) |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | MarkdownドキュメントをConfluenceページとして公開し、以降の編集でも目次マクロ・本文画像・添付・画像化した図が正しく保たれるようにします。 |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 下書き → テスト → レビュー → 改善のループを通じて、エージェントスキルを作成・検証・パッケージ化します。 |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | ステージ済みと未ステージの変更をまとめて、または指定した範囲を、直近のコミット履歴とともに読み取り、このリポジトリのスタイルに合ったコミットメッセージを5件提案します。 |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 開発設計ドキュメントを新しく書く、または整理する際のルールと、目次を段階的に絞り込む5ステップの手順です。[韓国語ガイド](skills/technical-design-writer/README.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 現在のエージェントと相手側のClaude/Codexセッションが、交換回数を制限した議論を行い、論点を洗い出し収束させます。[韓国語ガイド](skills/tiki-taka/README.ko.md) |

## 関連リンク

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) は独立したソースとして残り、
  プラグインのスキル一覧には含まれません。
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 独立したスキルがモデルルーティングを更新するプラグインシステム

## ライセンス

このリポジトリは Apache License 2.0 の下で公開されています。全文は [`LICENSE`](./LICENSE) を参照してください。
