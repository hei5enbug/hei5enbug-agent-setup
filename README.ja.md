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
├── standalone-skills/
│   ├── omo-model-config/
│   └── portable-opencode-setup/
└── skills/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

各フォルダは自身の `SKILL.md` と、必要な参照資料・スクリプトを保持しています。
プラグインは `skills/` のみを検出し、`standalone-skills/` は検出しません。

## スキル一覧

| スキル | 内容 |
|---|---|
| [`deep-interview`](skills/deep-interview/SKILL.md) | 回答ごとに要件の曖昧さをスコアで測るソクラテス式インタビューを行い、そのスコアが閾値以下になるまで実行段階に進みません。 |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | SVG、HTML/CSS、Figma、draw.io のどのツールで作っても一つのデザインシステムのように見えるようにするフローチャート共通デザイン基準です。 |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | 内容はそのままに、AIが書いたような韓国語の文章を人が書いたように自然な韓国語へ書き直します。 |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | MarkdownドキュメントをConfluenceページとして公開し、以降の編集でも目次マクロ・本文画像・添付・画像化した図が正しく保たれるようにします。 |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 下書き → テスト → レビュー → 改善のループを通じて、エージェントスキルを作成・検証・パッケージ化します。 |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 現在のdiffと直近のコミット履歴を読み取り、このリポジトリのスタイルに合ったコミットメッセージを5件提案します。 |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 開発設計ドキュメントを新しく書く、または整理する際のルールと、目次を段階的に絞り込む5ステップの手順です。 |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 現在のエージェントと相手側のClaude/Codexセッションが、交換回数を制限した議論を行い、論点を洗い出し収束させます。 |

## 関連リンク

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) と
  [`portable-opencode-setup`](standalone-skills/portable-opencode-setup/SKILL.md) は独立したソースとして残り、
  プラグインのスキル一覧には含まれません。
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 独立した OpenCode スキルが設定するプラグインシステム
