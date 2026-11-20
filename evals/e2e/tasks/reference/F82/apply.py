import sys

from patch_tools import replace

repo, file = sys.argv[1], "src/SettingsPanel.tsx"
replace(repo, file, "flexDirection: \"column\", gap: 12 }}", "flexDirection: \"column\", gap: 16 }}")
replace(repo, file, "<span>Display name</span>", "<span>Full name</span>")
replace(repo, file, "<span>Notifications</span>", "<span>Email alerts</span>")
replace(repo, file, "<Button variant=\"ghost\">Cancel</Button>", "<Button variant=\"secondary\">Cancel</Button>")
