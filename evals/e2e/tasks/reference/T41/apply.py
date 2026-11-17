import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "orders/dates.py", "SQL_DAY = \"strftime('%Y-%m-%d', {column})\"", "SQL_DAY = \"strftime('%d.%m.%Y', {column})\"")
replace(repo, "orders/dates.py", "    return value[:10]\n", "    year, month, day = value[:10].split(\"-\")\n    return f\"{day}.{month}.{year}\"\n")
