# Failure and maintenance

Classify a failure before retrying. Missing executables or hook files, denied capabilities, permission
boundaries, and known quota exhaustion require changed conditions or an authorized working path, not an
unchanged retry. An apparently transient error permits at most one unchanged retry. After another failure,
diagnose it and obtain evidence of a changed input, environment, or service state before trying again.
Service access still follows its existing per-path fallback rules.

If a plugin hook path is missing, stop actions that depend on it and report the exact blocker. Never remove
hook entries, fake a successful guard, lower trust, or copy a different version into the old directory.
Recover the exact verified version or use the host's supported fresh-session path with the required approval.
When a host-generated Stop loop is outside agent control, report the external recovery step; neither a missing
script nor an instruction can guarantee that the host's loop ends.

Do not start a cache-replacing plugin update inside an active coding-agent session. An idle prompt still
holds a live session. Use the updater's explicit offline boundary after affected sessions have ended, or
apply an already-installed version. Preserve installed files and guard behavior when an update is deferred.
This does not control manual updates or another process deleting a loaded directory.
