"""The Claude Code built-in subagent types this plugin denies, shared by the agent guard hook and the host settings rules."""

NAMES = ("general-purpose", "Explore", "Plan", "claude")
DENIAL = (
    "The built-in agent is disabled while hei5enbug-agent-setup is installed. Use `hei5enbug-agent-setup:scout` or "
    "`hei5enbug-agent-setup:worker`, another defined agent, or the main session."
)


def is_denied(tool_input: dict) -> bool:
    """A spawn is denied when its type is a built-in name or, with no resume of an earlier agent, is missing."""
    name = tool_input.get("subagent_type")
    if isinstance(name, str) and name.strip():
        return name.strip().casefold() in {item.casefold() for item in NAMES}
    return not tool_input.get("resume")
