# Azure and Kubernetes protected values

Ask for explicit user approval before accessing, listing, retrieving, decoding, or using Azure or
Kubernetes protected security values, except for Azure access authorized below.

Protected values include credentials, tokens, keys, certificates, kubeconfigs, Key Vault values,
and Kubernetes Secrets.
This rule applies to CLIs, SDKs, APIs, files, environment variables, keychains, logs, and indirect retrieval.

## Azure skill authorization

When the user explicitly invokes a skill that requires Azure access, treat the request as approval
to use the Azure protected values required by that skill.
Do not ask for separate Azure credential approval within the skill's stated execution scope.

Always ask before Azure access outside that scope and before any Kubernetes protected value access.
Never print or expose protected values.
