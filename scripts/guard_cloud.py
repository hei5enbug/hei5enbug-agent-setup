"""kubectl, helm, az, terraform, aws, gcloud, docker, podman, curl, and SQL rules for the approval guard."""
import functools
import hashlib
import json
import os
import re
from collections import namedtuple
from pathlib import Path
from urllib.parse import urlsplit
import approval_state
import db_read_policy
from approval_state import Outcome
import guard_shell
from guard_shell import (
    GLOBAL_VALUE_OPTIONS, _contains, _datagrip, _destructive, _has_flag, _matches, _read, _unclassified, option_value,
    option_values,
)
from guard_paths import _sensitive


GCLOUD_READ_VERBS = frozenset({"list", "describe", "ls", "cat"})
GCLOUD_WRITE_VERBS = frozenset({
    "create", "update", "delete", "set", "deploy", "start", "stop", "reset", "resize", "patch", "import", "export",
    "run", "submit", "ssh", "scp", "cp", "mv", "rsync",
})
GCLOUD_WRITE_PREFIXES = ("set-", "add-", "remove-")
Rules = namedtuple("Rules", "secret dry_run always read target sensitive write critical",
                   defaults=(False, False, False, False, None, False, False, None))


def _secret_resource(args):
    for arg in args:
        if arg.startswith("-"):
            continue
        for part in arg.split(","):
            if part.split("/")[0].lower() in ("secret", "secrets"):
                return True
    return False


OUTPUT_SECRET_FORMATS = ("jsonpath", "go-template", "template", "custom-columns")
KUBE_LIST_INDEX = r"\[\*\]"
KUBE_METADATA_PATH = re.compile(
    r"(?:\.items" + KUBE_LIST_INDEX + r")?(?:"
    r"\.metadata\.(?:name|namespace|uid|creationTimestamp|deletionTimestamp|resourceVersion|generation|generateName)"
    r"|\.metadata\.labels(?:\.[A-Za-z0-9_-]+)?"
    r"|\.metadata\.finalizers(?:" + KUBE_LIST_INDEX + r")?"
    r"|\.metadata\.ownerReferences(?:" + KUBE_LIST_INDEX + r")?(?:\.[A-Za-z0-9_-]+)*"
    r"|\.(?:type|kind|apiVersion|immutable))"
)
KUBE_RANGE_PATH = re.compile(
    r"\.items(?:" + KUBE_LIST_INDEX + r")?"
    r"|(?:\.items" + KUBE_LIST_INDEX + r")?\.metadata\.(?:finalizers|ownerReferences)(?:" + KUBE_LIST_INDEX + r")?"
)
KUBE_QUOTED_LITERAL = r'"(?:\\.|[^"\\])*"' + r"|'(?:\\.|[^'\\])*'"
KUBE_JSONPATH_EXPRESSION = re.compile(r"\{((?:" + KUBE_QUOTED_LITERAL + r"|[^{}'\"])*?)\}")
KUBECTL_READS = (
    ("get",), ("describe",), ("logs",), ("top",), ("explain",), ("api-resources",), ("api-versions",),
    ("version",), ("cluster-info",), ("events",), ("diff",), ("auth", "can-i"), ("auth", "whoami"),
    ("config", "view"), ("config", "get-contexts"), ("config", "current-context"), ("config", "get-clusters"),
    ("rollout", "status"), ("rollout", "history"),
)


def _metadata_path(path, context=""):
    if not path.startswith((".", "$")):
        return ""
    return path[1:] if path.startswith("$") else context + path


def _metadata_output(output):
    name, separator, template = output.partition("=")
    if not separator or not template:
        return False
    if name.lower() == "custom-columns":
        columns = [column.partition(":") for column in template.split(",")]
        return all(header.strip() and colon and KUBE_METADATA_PATH.fullmatch(_metadata_path(path.strip()))
                   for header, colon, path in columns)
    if name.lower() != "jsonpath":
        return False
    contexts = [""]
    offset = 0
    for match in KUBE_JSONPATH_EXPRESSION.finditer(template):
        if "{" in template[offset:match.start()] or "}" in template[offset:match.start()]:
            return False
        expression = match[1].strip()
        if expression.startswith("range "):
            path = _metadata_path(expression[6:].strip(), contexts[-1])
            if not KUBE_RANGE_PATH.fullmatch(path):
                return False
            contexts.append(path if path.endswith("]") else path + "[*]")
        elif expression == "end":
            if len(contexts) == 1:
                return False
            contexts.pop()
        elif not re.fullmatch(KUBE_QUOTED_LITERAL, expression) and not KUBE_METADATA_PATH.fullmatch(
                _metadata_path(expression, contexts[-1])):
            return False
        offset = match.end()
    return len(contexts) == 1 and "{" not in template[offset:] and "}" not in template[offset:]


def _kube_context(args, env, cwd, explicit_context):
    argv = ["kubectl"]
    if option_value(args, longs=("--kubeconfig",)):
        argv += ["--kubeconfig", option_value(args, longs=("--kubeconfig",))]
    return explicit_context or guard_shell._lookup([*argv, "config", "current-context"], env, cwd) or "(current)"


def _production_name(name):
    """Whether a target name cannot be shown to be non-production; `/` separates the parts of a target."""
    return db_read_policy.is_production(name.replace("/", " "))


def _kube_target(args, env, cwd, explicit_context, context=None):
    kubeconfig = option_value(args, longs=("--kubeconfig",)) or env.get("KUBECONFIG") or "(default)"
    context = context or _kube_context(args, env, cwd, explicit_context)
    namespace = option_value(args, "-n", ("--namespace",)) or "(default)"
    return f"{kubeconfig} {context}/{namespace}"


def _kubectl_rules(kind, args, env, cwd):
    secret = _matches(kind, (("create", "token"),)) or (kind[:2] == ["config", "view"] and _has_flag(args, "--raw"))
    if kind[:1] == ["get"]:
        raw = option_value(args, longs=("--raw",))
        output = option_value(args, "-o", ("--output",)) or ""
        output_name = output.split("=", 1)[0].lower()
        output_secret = output_name in ("json", "yaml") or output_name.startswith(OUTPUT_SECRET_FORMATS)
        if (output_secret and option_value(args, longs=("--template",)) is None
                and not any(arg.startswith("--allow-missing-template-keys") for arg in args)
                and _metadata_output(output)):
            output_secret = False
        secret = secret or (raw is not None and "secrets" in raw) or (_secret_resource(args) and output_secret)
    dry_run = _has_flag(args, "--dry-run=client", "--dry-run=server") or option_value(
        args, longs=("--dry-run",)) in ("client", "server")
    own_args = args[:args.index("--")] if "--" in args else args
    forced = any(arg in ("--force", "--prune") or arg.startswith(("--force=", "--prune=")) for arg in own_args)

    @functools.cache
    def context():
        return _kube_context(args, env, cwd, option_value(args, longs=("--context",)))

    def target():
        return _kube_target(args, env, cwd, None, context())

    return Rules(secret=secret, dry_run=dry_run, always=forced, read=_matches(kind, KUBECTL_READS), target=target,
                 write=kind[:1] == ["config"], critical=lambda: _destructive(kind) and _production_name(context()))


HELM_READS = (
    ("list",), ("ls",), ("status",), ("history",), ("show",), ("search",), ("template",), ("lint",), ("version",),
    ("env",), ("get", "notes"), ("get", "hooks"), ("get", "metadata"), ("repo", "list"), ("dependency", "list"),
    ("plugin", "list"),
)
HELM_SENSITIVE = (("get", "all"), ("get", "manifest"), ("get", "values"))


def _helm_rules(kind, args, env, cwd):
    @functools.cache
    def context():
        return _kube_context(args, env, cwd, option_value(args, longs=("--kube-context",)) or env.get("HELM_KUBECONTEXT"))

    def target():
        return _kube_target(args, env, cwd, None, context())

    sensitive = _matches(kind, HELM_SENSITIVE)
    return Rules(always=sensitive, read=_matches(kind, HELM_READS), target=target, sensitive=sensitive,
                 write=kind[:2] in (["repo", "remove"], ["repo", "rm"]),
                 critical=lambda: _destructive(kind) and _production_name(context()))


AZ_READ_WORDS = frozenset({"list", "show", "exists", "query"})
AZ_READ_PREFIXES = ("get-", "list-", "show-", "check-", "query-")
AZ_READ_PATHS = (("find",), ("version",), ("account", "show"), ("account", "list"))
AZ_SECRET_PATHS = (
    ("keyvault", "secret", "show"), ("keyvault", "secret", "download"), ("keyvault", "key", "download"),
    ("keyvault", "certificate", "download"), ("account", "get-access-token"), ("acr", "credential", "show"),
)
AZ_SECRET_WORDS = frozenset({"list-keys", "keys", "list-credentials", "show-connection-string", "list-connection-strings"})


def _az_rules(kind, args, env, cwd):
    secret = _matches(kind, AZ_SECRET_PATHS) or any(word in AZ_SECRET_WORDS for word in kind)
    read = (
        any(word in AZ_READ_WORDS or word.startswith(AZ_READ_PREFIXES) for word in kind)
        or _matches(kind, AZ_READ_PATHS) or _has_flag(args, "--version")
    )
    method = (option_value(args, "-m", ("--method",)) or "").upper()
    rest = kind[:1] == ["rest"]
    if rest:
        url = option_value(args, "-u", ("--url", "--uri")) or ""
        lowered = url.lower()
        parsed = _split_url(lowered)
        vault_secret = ((parsed.hostname or "").endswith(".vault.azure.net")
                        and re.search(r"/(?:secrets|keys)(?:/|$)", parsed.path))
        secret = secret or (method == "GET" and bool(vault_secret))
        read = (method == "GET" and (lowered.startswith("https://management.azure.com/") or url.startswith("$"))
                and not _has_flag(args, "--resource")
                and not any(word in lowered for word in (
                    "secret", "listkeys", "list-keys", "connectionstring", "listcredentials")))

    @functools.cache
    def target():
        subscription = option_value(args, longs=("--subscription",)) or guard_shell._lookup(
            ["az", "account", "show", "--query", "id", "-o", "tsv"], env, cwd) or "(current)"
        group = option_value(args, "-g", ("--resource-group",)) or "(default)"
        return f"{subscription}/{group}"

    always = rest and method == "DELETE"
    return Rules(secret=secret, always=always, read=read, target=target,
                 critical=lambda: (always or _destructive(kind)) and _production_name(target()))


TF_READS = (
    ("plan",), ("show",), ("validate",), ("version",), ("providers",), ("graph",), ("state", "list"),
    ("workspace", "list"), ("workspace", "show"),
)
TF_SENSITIVE = (("state", "show"), ("state", "pull"))


def _read_workspace(directory):
    try:
        return Path(directory, ".terraform", "environment").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _terraform_rules(kind, args, env, cwd):
    sensitive_output = kind[:1] == ["output"] and (_has_flag(args, "-json") or _has_flag(args, "-raw"))
    sensitive = _matches(kind, TF_SENSITIVE) or sensitive_output
    always = sensitive or (kind[:1] == ["apply"] and _has_flag(args, "-destroy"))
    plain_output = kind[:1] == ["output"] and not sensitive_output
    read = _matches(kind, TF_READS) or plain_output or (kind[:1] == ["fmt"] and _has_flag(args, "-check"))

    def target():
        chdir = option_value(args, longs=("-chdir",))
        directory = os.path.normpath(os.path.join(cwd, chdir)) if chdir else cwd
        workspace = env.get("TF_WORKSPACE") or _read_workspace(directory) or "default"
        return f"{directory}:{workspace}"

    destroys = kind[:1] == ["destroy"] or (kind[:1] == ["apply"] and _has_flag(args, "-destroy"))
    return Rules(always=always, read=read, target=target, sensitive=sensitive, critical=lambda: destroys)


AWS_SECRET = (
    ("secretsmanager", "get-secret-value"), ("kms", "decrypt"), ("ecr", "get-login-password"),
    ("sts", "assume-role"), ("sts", "get-session-token"), ("configure", "get"), ("rds", "generate-db-auth-token"),
    ("secretsmanager", "batch-get-secret-value"),
)
AWS_READ_PREFIXES = ("describe-", "list-", "get-")
AWS_READS = (("s3", "ls"), ("sts", "get-caller-identity"), ("configure", "list"))


def _aws_rules(kind, args, env, cwd):
    operation = kind[1] if len(kind) > 1 else ""
    secret = _matches(kind, AWS_SECRET) or (
        kind[:1] == ["ssm"] and operation.startswith("get-parameter") and _has_flag(args, "--with-decryption"))
    read = operation.startswith(AWS_READ_PREFIXES) or _matches(kind, AWS_READS)

    def target():
        profile = option_value(args, longs=("--profile",)) or env.get("AWS_PROFILE") or "(default)"
        region = option_value(args, longs=("--region",)) or env.get("AWS_REGION") or "(default)"
        return f"{profile}/{region}"

    always = kind[:2] == ["s3", "sync"] and _has_flag(args, "--delete")
    return Rules(secret=secret, always=always, read=read, target=target,
                 critical=lambda: (always or _destructive(kind)) and _production_name(target()))


GCLOUD_SECRET = (
    ("secrets", "versions", "access"), ("auth", "print-access-token"), ("auth", "print-identity-token"),
    ("sql", "generate-login-token"),
)


def _project_target(args, env):
    return option_value(args, longs=("--project",)) or env.get("CLOUDSDK_CORE_PROJECT") or "(current)"


def _gcloud_verb_read(kind):
    """The first verb in the command path decides: a read verb reads, a write verb or no verb is a write."""
    for word in kind:
        if word in GCLOUD_READ_VERBS or word.startswith("get-"):
            return True
        if word in GCLOUD_WRITE_VERBS or word.startswith(GCLOUD_WRITE_PREFIXES):
            return False
    return False


def _gcloud_rules(kind, args, env, cwd):
    secret = any(_contains(kind, sequence) for sequence in GCLOUD_SECRET)
    return Rules(secret=secret, read=_gcloud_verb_read(kind), target=lambda: _project_target(args, env),
                 critical=lambda: _destructive(kind) and _production_name(_project_target(args, env)))


def _gsutil_rules(kind, args, env, cwd):
    return Rules(read=_gcloud_verb_read(kind), target=lambda: _project_target(args, env),
                 critical=lambda: _destructive(kind) and _production_name(_project_target(args, env)))


DOCKER_READ_FIRST = frozenset({"ps", "images", "inspect", "logs", "version", "info"})
DOCKER_OBJECTS = frozenset({
    "container", "image", "network", "volume", "context", "plugin", "node", "service", "stack", "secret", "config",
})
DOCKER_READS = (("context", "show"), ("compose", "ps"), ("compose", "logs"), ("compose", "config"))
DOCKER_METADATA_FIELD = re.compile(r"\.(?:Labels|Name|Driver|Mountpoint|CreatedAt|Id|RepoTags|Size)(?:\.[\w-]+)*")
DOCKER_TEMPLATE_ACTION = re.compile(r"\{\{(.*?)\}\}", re.S)
DOCKER_TEMPLATE_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|`[^`]*`')


def _metadata_template(template):
    """Whether a Go template has at least one action and each action only names metadata fields: the labels, name,
    driver, mount point, creation time, ID, tags, and size, with the `json` and `index` helpers."""
    actions = DOCKER_TEMPLATE_ACTION.findall(template)
    outside = DOCKER_TEMPLATE_ACTION.sub("", template)
    if not actions or "{{" in outside or "}}" in outside:
        return False
    for action in actions:
        words = DOCKER_TEMPLATE_STRING.sub(" ", action).split()
        if not words or not all(word in ("json", "index") or DOCKER_METADATA_FIELD.fullmatch(word) for word in words):
            return False
    return True


def _docker_metadata_inspect(cli, kind, args, env):
    """A local `docker volume|image|network inspect` whose format template shows only metadata fields."""
    templates = option_values(args, "-f", ("--format",))
    return (cli == "docker" and kind[:2] in (["volume", "inspect"], ["image", "inspect"], ["network", "inspect"])
            and bool(templates) and all(isinstance(template, str) and _metadata_template(template) for template in templates)
            and _local_engine(args, env, cli))


def _docker_rules(kind, args, env, cwd, engine="docker"):
    read = (
        (bool(kind) and kind[0] in DOCKER_READ_FIRST)
        or (len(kind) >= 2 and kind[0] in DOCKER_OBJECTS and kind[1] in ("ls", "inspect"))
        or _matches(kind, DOCKER_READS)
        or kind[:2] == ["system", "df"] and engine == "docker" and _local_engine(args, env, engine)
    )
    always = (kind[:2] == ["compose", "down"] and (_has_flag(args, "-v") or _has_flag(args, "--volumes"))
              and not _local_engine(args, env, engine))

    def target():
        return (option_value(args, longs=("--context",)) or env.get("DOCKER_CONTEXT")
                or env.get("DOCKER_HOST") or "(current)")

    return Rules(always=always, read=read, target=target)


def _classify_sql(cli, args, env, cwd, command):
    postgres = cli == "psql"
    if postgres:
        commands = option_values(args, "-c", ("--command",))
        files = option_values(args, "-f", ("--file",))
        known = option_value(args, "-h", ("--host",)) or env.get("PGHOST")
        database = option_value(args, "-d", ("--dbname",)) or env.get("PGDATABASE") or "(default)"
        service = env.get("PGSERVICE") or ""
    else:
        commands = option_values(args, "-Q") + option_values(args, "-q")
        files = option_values(args, "-i")
        known = option_value(args, "-S")
        database = option_value(args, "-d") or "(default)"
        service = ""
    host = known or "(default)"
    if not commands or files or any(value is None for value in commands):
        return _unclassified(cli, command)
    datagrip = _datagrip()
    if all(datagrip.is_read(value, postgres) for value in commands):
        return Outcome("read", [], [], "psql" if postgres else None)
    facts = [datagrip.query_facts(value, postgres) for value in commands]
    if any(keywords is None for keywords, _ in facts):
        return _unclassified(cli, command)
    label = "+".join(sorted(set().union(*(keywords for keywords, _ in facts))))
    target = f"{host}/{database}"
    kind_name = "always" if any(destructive for _, destructive in facts) else "write"
    return Outcome(kind_name, [f"{cli}:{label}@{target}"], [f"{cli} {label} on {target}"],
                   every_time=kind_name == "always",
                   critical=kind_name == "always" and (not known or _production_name(f"{target} {service}")))


def _split_url(url):
    try:
        return urlsplit(url)
    except ValueError:
        return urlsplit("")


def _curl_origin(url):
    """Return scheme://host[:port] for a URL; a malformed port or IPv6 bracket falls back to the scheme and host."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
        scheme = parsed.scheme
    except ValueError:
        match = re.match(r"([a-zA-Z][a-zA-Z0-9+.-]*)://([^/?#]*)", url)
        if not match:
            return None
        scheme, authority = match[1].lower(), match[2].rpartition("@")[2]
        host = authority[1:].partition("]")[0] if authority.startswith("[") else authority.partition(":")[0]
        port = None
    if not host:
        return None
    if ":" in host:
        host = "[" + host + "]"
    return f"{scheme}://{host}" + (f":{port}" if port else "")


def _classify_curl(args, command):
    headers = option_values(args, "-H", ("--header",))
    credentials = (_has_flag(args, "-u", "--user") or bool(option_values(args, "-u", ("--user",)))
                   or any(value and re.match(r"authorization\s*:", value, re.I) for value in headers))
    outcome = _classify_curl_method(args, command)
    if not credentials or outcome.kind in ("pass", "forbidden", "secret") or outcome.every_time:
        return outcome
    if outcome.kind == "read":
        return _sensitive(command)
    return Outcome("sensitive", [approval_state.SENSITIVE_KEY], outcome.descriptions, None, outcome.keys)


def _classify_curl_method(args, command):
    data = any(
        arg in ("-d", "-F", "-T") or arg.startswith(("--data", "--form", "--upload-file", "--json"))
        or (arg.startswith(("-d", "-F", "-T")) and len(arg) > 2) for arg in args
    )
    upload = any(arg == "-T" or arg.startswith(("-T", "--upload-file")) for arg in args)
    method = option_value(args, "-X", ("--request",))
    method = (method or ("PUT" if upload else "POST" if data else "HEAD" if _has_flag(args, "-I", "--head") else "GET")).upper()
    if method in ("GET", "HEAD") and not data:
        return _read()
    targets = set()
    value_options = {
        "-X", "--request", "-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode",
        "--json", "-F", "--form", "--form-string", "-T", "--upload-file", "-H", "--header", "-u", "--user",
        "-x", "--proxy", "-o", "--output", "-b", "--cookie", "-c", "--cookie-jar", "--cacert", "--cert", "--key",
        "--connect-timeout", "--max-time", "-m",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in value_options:
            index += 2
            continue
        if arg == "--url" and index + 1 < len(args):
            index += 1
            arg = args[index]
        url = arg.partition("=")[2] if arg.startswith("--url=") else arg
        origin = _curl_origin(url) if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*://", url) else None
        if origin:
            targets.add(origin)
        index += 1
    if not targets:
        return _unclassified("curl", command)
    destructive = _destructive([method])
    return Outcome("always" if destructive else "write", [f"curl:{method}@{target}" for target in sorted(targets)],
                   [f"curl {method} on {target}" for target in sorted(targets)], every_time=destructive)


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
ENGINE_REMOTE_LONG = frozenset({"--host", "--remote", "--url", "--connection", "--identity"})
ENGINE_REMOTE_SHORT = ("-c", "-H", "-r")
ENGINE_VALUE_OPTIONS = GLOBAL_VALUE_OPTIONS | frozenset({
    "-c", "-l", "--log-level", "--config", "--tlscacert", "--tlscert", "--tlskey", "--identity", "--url", "--connection",
})
PODMAN_SYSTEM_CONFIGS = ("/etc/containers/containers.conf", "/usr/share/containers/containers.conf")
PODMAN_REMOTE_SETTING = re.compile(r"^\s*(?:active_service\s*=\s*[\"'][^\"'\n]+[\"']|remote\s*=\s*true\b)", re.M | re.I)


def _config_text(path):
    """The text of a config file, None when it does not exist; any other failure is raised as OSError or ValueError."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None


def _docker_context_local(name, config_dir):
    """Whether a named Docker context points at a local socket, from its metadata file in the Docker config folder; a
    missing, unreadable, or malformed file, a missing host, or any other scheme counts as remote."""
    if name == "default":
        return True
    try:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        text = _config_text(Path(config_dir) / "contexts" / "meta" / digest / "meta.json")
        host = json.loads(text)["Endpoints"]["docker"]["Host"] if text is not None else None
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return isinstance(host, str) and host.startswith(("unix://", "npipe://"))


def _docker_context_name(config_dir, env):
    """The context the config selects, "default" when none, None when the config cannot be read."""
    try:
        text = _config_text(Path(config_dir) / "config.json")
        data = json.loads(text) if text is not None else {}
    except (OSError, ValueError):
        return None
    current = data.get("currentContext", "") if isinstance(data, dict) else None
    return (current or "default") if isinstance(current, str) else None


def _podman_remote_default(env):
    """Whether containers.conf or the saved system connection makes podman talk to a remote service by default; an
    unreadable file counts as remote."""
    config_home = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "containers"
    files = [env["CONTAINERS_CONF"]] if env.get("CONTAINERS_CONF") else []
    files += [str(config_home / "containers.conf"), *PODMAN_SYSTEM_CONFIGS]
    try:
        for file in list(files):
            folder = Path(file + ".d")
            if folder.is_dir():
                files += sorted(str(item) for item in folder.glob("*.conf"))
        for file in files:
            text = _config_text(file)
            if text is not None and PODMAN_REMOTE_SETTING.search(text):
                return True
        saved = _config_text(config_home / "podman-connections.json")
        if saved is not None:
            connection = json.loads(saved).get("Connection")
            return not isinstance(connection, dict) or bool(connection.get("Default"))
    except (OSError, ValueError, AttributeError):
        return True
    return False


def _local_engine(args, env, engine="docker"):
    """Whether a docker or podman call talks to the engine on this machine: no remote option before the subcommand, no
    context or host variable or saved configuration that names a remote. A named Docker context is local when its
    metadata names a unix socket."""
    index, config_dir, context = 0, None, None
    while index < len(args) and args[index].startswith("-"):
        arg = args[index]
        if engine == "docker" and arg == "--context" and index + 1 < len(args):
            context = args[index + 1]
        elif engine == "docker" and arg.startswith("--context="):
            context = arg.partition("=")[2]
        elif engine == "docker" and arg == "-c" and index + 1 < len(args):
            context = args[index + 1]
        elif engine == "docker" and arg.startswith("-c") and not arg.startswith("--") and len(arg) > 2:
            context = arg[2:].lstrip("=")
        elif arg.split("=", 1)[0] in ENGINE_REMOTE_LONG or (not arg.startswith("--") and arg[:2] in ENGINE_REMOTE_SHORT):
            return False
        elif arg == "--config" and index + 1 < len(args):
            config_dir = args[index + 1]
        elif arg.startswith("--config="):
            config_dir = arg.partition("=")[2]
        index += 2 if arg in ENGINE_VALUE_OPTIONS else 1
    if env.get("CONTAINER_HOST") or env.get("CONTAINER_CONNECTION"):
        return False
    host = (env.get("DOCKER_HOST") or "").strip()
    if host and not host.startswith(("/", "unix://")) and not (
            "://" not in host and (_split_url("//" + host).hostname or "").lower() in LOCAL_HOSTS):
        return False
    if engine == "podman":
        return (env.get("DOCKER_CONTEXT") or "default") == "default" and not _podman_remote_default(env)
    config_dir = config_dir or env.get("DOCKER_CONFIG") or str(Path.home() / ".docker")
    name = context or env.get("DOCKER_CONTEXT") or _docker_context_name(config_dir, env)
    return name is not None and _docker_context_local(name, config_dir)
