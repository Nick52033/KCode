import sqlite3
import sys

path = sys.argv[1]
con = sqlite3.connect(path)
print("== sessions (latest 20) ==")
for row in con.execute(
    "select id, title, updated_at_ms, event_count, archived, in_project "
    "from sessions order by updated_at_ms desc limit 20"
):
    print(row)

print()
print("== sessions with title = 'Xin Hui Hua' ==")
for row in con.execute(
    "select count(*) from sessions where title = ?", ("\u65b0\u4f1a\u8bdd",)
):
    print("count:", row[0])

print()
print("== total sessions ==")
for row in con.execute("select count(*) from sessions"):
    print("count:", row[0])
