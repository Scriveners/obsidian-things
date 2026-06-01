import sqlite3
import subprocess
import json

class ThingsAPI:
    """
    Wrapper for Cultured Code's Things 3 database and AppleScript API.
    Uses direct SQLite read for fast querying, and AppleScript via osascript for safe writing.
    """
    def __init__(self, db_path):
        self.db_path = db_path

    def _run_applescript(self, script_code):
        """Runs AppleScript by piping the code into osascript stdin to avoid escaping issues."""
        try:
            process = subprocess.Popen(
                ['osascript'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=script_code)
            if process.returncode != 0:
                raise RuntimeError(f"AppleScript error: {stderr.strip()}")
            return stdout.strip()
        except Exception as e:
            raise RuntimeError(f"Failed to execute AppleScript: {e}")

    def get_task_by_uuid(self, uuid):
        """
        Reads task details directly from SQLite database.
        Status mapping in Things 3 SQLite:
        0 = Open/Incomplete
        1 = Canceled
        2 = Waiting/Scheduled?
        3 = Completed
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = "SELECT uuid, status, title, notes, trashed, type FROM TMTask WHERE uuid = ?;"
            cursor.execute(query, (uuid,))
            row = cursor.fetchone()
            if row:
                return {
                    "uuid": row[0],
                    "status": row[1],
                    "title": row[2],
                    "notes": row[3] if row[3] is not None else "",
                    "trashed": bool(row[4]),
                    "type": row[5]
                }
            return None
        except sqlite3.Error as e:
            raise RuntimeError(f"SQLite database error: {e}")
        finally:
            if conn:
                conn.close()

    def _escape_string(self, text):
        """Safely escapes strings for AppleScript."""
        if not text:
            return ""
        # Escape backslashes first, then quotes, then handle newlines
        return text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')

    def create_task(self, title, notes=""):
        """
        Creates a new task in Things 3 Inbox using AppleScript.
        Returns the generated UUID of the created task.
        """
        escaped_title = self._escape_string(title)
        escaped_notes = self._escape_string(notes)
        
        script = (
            'tell application "Things3"\n'
            '    set newTodo to make new to do at beginning of list "Inbox"\n'
            f'    set name of newTodo to "{escaped_title}"\n'
            f'    set notes of newTodo to "{escaped_notes}"\n'
            '    get id of newTodo\n'
            'end tell'
        )
        return self._run_applescript(script)

    def update_task_status(self, uuid, status_str):
        """
        Updates the task status in Things 3.
        status_str can be: 'completed', 'open', 'canceled'
        """
        if status_str not in ['completed', 'open', 'canceled']:
            raise ValueError("Status must be 'completed', 'open', or 'canceled'")
            
        script = (
            'tell application "Things3"\n'
            f'    set targetTodo to to do id "{uuid}"\n'
            f'    set status of targetTodo to {status_str}\n'
            'end tell'
        )
        self._run_applescript(script)

    def update_task_notes(self, uuid, notes):
        """Updates the notes field of an existing task."""
        escaped_notes = self._escape_string(notes)
        script = (
            'tell application "Things3"\n'
            f'    set targetTodo to to do id "{uuid}"\n'
            f'    set notes of targetTodo to "{escaped_notes}"\n'
            'end tell'
        )
        self._run_applescript(script)

    def get_tasks_by_tag(self, tag_title):
        """
        Fetches untrashed, open tasks that have a specific tag.
        Used for importing new items created in Things with a specific tag (e.g., 'obsidian').
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = """
                SELECT t.uuid, t.title, t.notes
                FROM TMTask t
                INNER JOIN TMTaskTag tt ON t.uuid = tt.tasks
                INNER JOIN TMTag tag ON tt.tags = tag.uuid
                WHERE tag.title = ? 
                  AND t.type = 0 
                  AND t.trashed = 0
                  AND t.status = 0;
            """
            cursor.execute(query, (tag_title,))
            tasks = []
            for row in cursor.fetchall():
                tasks.append({
                    "uuid": row[0],
                    "title": row[1],
                    "notes": row[2] if row[2] is not None else ""
                })
            return tasks
        except sqlite3.Error as e:
            raise RuntimeError(f"SQLite database error while fetching tagged tasks: {e}")
        finally:
            if conn:
                conn.close()
