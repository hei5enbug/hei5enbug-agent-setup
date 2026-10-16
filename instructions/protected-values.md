# Protected values

Protected values include credentials, tokens, keys, certificates, kubeconfigs, Key Vault values, Kubernetes
Secrets, cloud secret-manager values, and connection strings with passwords. They can come from any CLI, SDK,
API, file, environment variable, keychain, or log.

- Never print, decode, log, copy into a file you read, or otherwise reveal a protected value.
- Never ask the user to paste a protected value.
- Use a protected value only through the helper described here.
- A CLI that reads its own credentials, such as `kubectl` with its kubeconfig or `az` after login, is not using a
  protected value; run it directly. Use the helper only when a command needs a value you would otherwise have to read.

## Use the helper

Run the command through the helper. `<Source directory>` is the line in the session context:

```text
python3 <Source directory>/scripts/secret_exec.py (--secret VAR=SOURCE | --file VAR=SOURCE)... [--timeout N] -- COMMAND [ARG...]
```

- `--secret VAR=SOURCE` sets environment variable `VAR` to the value.
- `--file VAR=SOURCE` writes the value to a temporary file and sets `VAR` to its path. The helper deletes the
  file when it exits.
- The helper masks the value in the command's stdout and stderr. The command runs without a shell, so pass
  `sh -c '...'` when you need one.

| Source | Value |
|---|---|
| `k8s:[<context>/]<namespace>/<secret>/<key>` | A Kubernetes Secret key |
| `keyvault:<vault>/<name>` | An Azure Key Vault secret |
| `aws:<secret id>[#<json key>]` | An AWS Secrets Manager secret, or one string field of its JSON |
| `gcp:<project>/<name>[/<version>]` | A Google Cloud Secret Manager version; the default is `latest` |

Example:

```text
python3 <Source directory>/scripts/secret_exec.py --secret API_TOKEN=aws:prod/app#api_token -- sh -c 'curl -H "Authorization: Bearer $API_TOKEN" https://api.example.com/v1/me'
```

Using the helper needs no separate approval. The command it runs follows the normal read and write approval
rules. A separate guard blocks commands that would print protected values.

## Azure skill access

When the user explicitly invokes a skill that requires Azure access, the invocation approves the Azure access
that the skill's stated scope needs. Do not ask for separate Azure credential approval within that scope.
Use the helper for every protected value that access requires.
