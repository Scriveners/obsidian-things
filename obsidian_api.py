import os
import re
import hashlib

class ObsidianAPI:
    """
    Parser and updater for Obsidian Daily Log markdown files.
    """
    def __init__(self, vault_path, relative_logs_path):
        self.vault_path = vault_path
        self.logs_dir = os.path.join(vault_path, relative_logs_path)
        # Regex to parse markdown tasks (optionally extracts legacy %%things:UUID%% if present)
        self.task_regex = re.compile(r'^(\s*)-\s+\[([ xX])\]\s+(.*?)(?:\s+%%things:([a-zA-Z0-9_-]+)%%)?$')

    def get_daily_log_path(self, date_str):
        """Returns the absolute path to a daily log file for a given YYYYMMDD date string."""
        return os.path.join(self.logs_dir, f"{date_str}.md")

    def parse_daily_log(self, filepath):
        """
        Parses a markdown file and returns a list of task dicts.
        If the file does not exist, returns an empty list.
        Each task contains a unique content-based hash to identify it in the metadata database.
        """
        if not os.path.exists(filepath):
            return []

        tasks = []
        # Keep track of duplicate task titles in the same file to generate unique hashes
        title_occurrences = {}
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for idx, line in enumerate(lines):
                stripped_line = line.rstrip('\r\n')
                match = self.task_regex.match(stripped_line)
                if match:
                    indent = match.group(1)
                    status_char = match.group(2)
                    title = match.group(3).strip()
                    legacy_uuid = match.group(4) # Legacy inline UUID if exists
                    
                    # Track occurrence to prevent duplicate title hashes
                    occurrence = title_occurrences.get(title, 0)
                    title_occurrences[title] = occurrence + 1
                    
                    # Generate a unique hash key based on the task title and its occurrence index
                    hash_input = f"{title}_{occurrence}"
                    task_hash = hashlib.md5(hash_input.encode('utf-8')).hexdigest()
                    
                    tasks.append({
                        "line_no": idx,
                        "indent": indent,
                        "completed": status_char.lower() == 'x',
                        "title": title,
                        "hash": task_hash,
                        "legacy_uuid": legacy_uuid,
                        "raw_line": stripped_line
                    })
        except Exception as e:
            raise RuntimeError(f"Error parsing daily log {filepath}: {e}")
            
        return tasks

    def update_task_status(self, filepath, line_no, title, completed=True):
        """
        Updates a task's status to completed ([x]) or incomplete ([ ]) in the Obsidian file.
        Attempts to use line_no first, and falls back to searching by title if line_no doesn't match.
        Returns True if the task was found and updated, False otherwise.
        """
        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            target_char = 'x' if completed else ' '
            updated = False

            def update_line(line, target_status):
                match = self.task_regex.match(line.rstrip('\r\n'))
                if match:
                    status_char = match.group(2)
                    # Replace the first occurrence of f"[{status_char}]" with the target status
                    return line.replace(f"[{status_char}]", f"[{target_status}]", 1)
                return line

            # Try exact line number first
            if line_no < len(lines):
                line = lines[line_no]
                match = self.task_regex.match(line.rstrip('\r\n'))
                if match and match.group(3).strip() == title:
                    status_char = match.group(2)
                    current_completed = status_char.lower() == 'x'
                    if current_completed != completed:
                        lines[line_no] = update_line(line, target_char)
                        updated = True

            # Fallback: scan all lines if not updated at line_no
            if not updated:
                for idx, line in enumerate(lines):
                    match = self.task_regex.match(line.rstrip('\r\n'))
                    if match and match.group(3).strip() == title:
                        status_char = match.group(2)
                        current_completed = status_char.lower() == 'x'
                        if current_completed != completed:
                            lines[idx] = update_line(line, target_char)
                            updated = True
                            break

            if updated:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                return True
            
            return False
        except Exception as e:
            raise RuntimeError(f"Error updating task status in daily log {filepath}: {e}")
