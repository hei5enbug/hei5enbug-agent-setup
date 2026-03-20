# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | **日本語** | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

AIエージェントharnessにおいて、各エージェントの役割に合わせたモデルとvariantを割り当てた設定です。

## 概要

harnessのエージェントごとに求められる能力は異なります。この設定は、エージェントの役割とタスクカテゴリに合わせて `model`、`variant`、フォールバックチェーンを最適化します。

## 対応ツール

- [OpenCode](https://github.com/code-yeongyu/oh-my-opencode)（[Oh My OpenCode](https://github.com/code-yeongyu/oh-my-opencode) プラグイン使用）

## 構成

```
hei5enbug-agent-setup/
├── oh-my-opencode.json       # スキルが読み取り・編集する設定ファイル
├── available-models.json     # スキルがモデル変更時の検証に使用するallowlist
└── .opencode/
    └── skills/
        └── omo-model-config/ # 安全な設定編集のためのカスタムスキル
            └── SKILL.md
```

## カスタムスキル

### omo-model-config

エージェントのモデル割り当てを安全に編集するワークフローです。以下のルールを適用します：

- **GitHub優先解釈** — 上流の [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) ドキュメントがモデルとロールのマッチングにおける主要な基準
- **可用性ゲート** — すべてのモデルは `available-models.json` のallowlistに存在する必要あり
- **プロバイダ多様性ゲート** — 各エージェントのフォールバックチェーンに必須プロバイダが含まれる必要あり
- **編集範囲の制限** — `model`、`variant`、`fallback_models` フィールドのみ変更し、その他はすべて保持

詳細は [`.opencode/skills/omo-model-config/SKILL.md`](.opencode/skills/omo-model-config/SKILL.md) を参照してください。

## 使い方

対応するエージェントツールでプロジェクトルートとして開きます。セッション開始時に設定が自動で読み込まれます。

```bash
cd hei5enbug-agent-setup
opencode
```

### モデル割り当ての変更

エージェントセッション内で `omo-model-config` スキルを呼び出します：

```
/omo-model-config
```

またはエージェントに直接リクエストできます：

```
"Oracleのprimary modelをclaude-opus-4-6に変更して"
"Librarianのfallbackにgpt-5.4を追加して"
```

スキルがallowlistと照合して変更を検証し、プロバイダ多様性ルールを確認してから反映します。

## 設定

| キー | 値 | 説明 |
|---|---|---|
| `runtime_fallback` | `true` | プライマリモデルが利用不可の場合、自動的に次のモデルにフォールバック |
| `disabled_hooks` | `["no-sisyphus-gpt"]` | Sisyphusエージェントで GPT モデルの使用を許可 |

## 関連リンク

- [Oh My OpenCode](https://github.com/code-yeongyu/oh-my-opencode) — 設定を駆動するプラグインシステム
- [oh-my-openagent docs](https://github.com/code-yeongyu/oh-my-openagent) — 上流ドキュメントおよびモデルマッチングガイド
