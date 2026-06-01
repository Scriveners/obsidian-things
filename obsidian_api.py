import os
import re
import tempfile

class ObsidianAPI:
    """
    Parser and updater for Obsidian Daily Log markdown files.
    """
    def __init__(self, vault_path, relative_logs_path):
        self.vault_path = vault_path
        self.logs_dir = os.path.join(vault_path, relative_logs_path)
        # Regex to parse markdown tasks and extract Things UUID from comment %%things:UUID%%
        self.task_regex = re.compile(r'^(\s*)-\s+\[([ xX])\]\s+(.*?)(?:\s+%%things:([a-zA-Z0-9_-]+)%%)?$')

    def get_daily_log_path(self, date_str):
        """Returns the absolute path to a daily log file for a given YYYYMMDD date string."""
        return os.path.join(self.logs_dir, f"{date_str}.md")

    def parse_daily_log(self, filepath):
        """
        Parses a markdown file and returns a list of task dicts.
        If the file does not exist, returns an empty list.
        """
        if not os.path.exists(filepath):
            return []

        tasks = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for idx, line in enumerate(lines):
                # Remove newline for parsing
                stripped_line = line.rstrip('\r\n')
                match = self.task_regex.match(stripped_line)
                if match:
                    indent = match.group(1)
                    status_char = match.group(2)
                    title = match.group(3).strip()
                    uuid = match.group(4) # Will be None if missing
                    
                    tasks.append({
                        "line_no": idx,
                        "indent": indent,
                        "completed": status_char.lower() == 'x',
                        "title": title,
                        "uuid": uuid,
                        "raw_line": stripped_line
                    })
        except Exception as e:
            raise RuntimeError(f"Error parsing daily log {filepath}: {e}")
            
        return tasks

    def update_tasks_in_file(self, filepath, updates):
        """
        Applies a list of updates to a markdown file atomically.
        updates: dict mapping line_no (int) to new_line_content (str)
        """
        if not os.path.exists(filepath):
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Apply updates
            for line_no, new_content in updates.items():
                if 0 <= line_no < len(lines):
                    # Maintain the original newline character if possible, default to \n
                    orig_line = lines[line_no]
                    newline_char = '\r\n' if orig_line.endswith('\r\n') else '\n'
                    lines[line_no] = new_content.rstrip('\r\n') + newline_char

            # Atomic write using temp file
            dir_name = os.path.dirname(filepath)
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as temp_file:
                temp_file.writelines(lines)
                temp_path = temp_file.name

            os.replace(temp_path, filepath)
        except Exception as e:
            raise RuntimeError(f"Failed to update daily log {filepath}: {e}")

    def add_task_to_section(self, filepath, task_title, task_uuid, section_header="## Tasks"):
        """
        Appends a new task to a specific section (default: '## Tasks') in the daily log.
        If the file doesn't exist, it creates it.
        If the section doesn't exist, it appends it to the end of the file.
        """
        task_line = f"- [ ] {task_title} %%things:{task_uuid}%%"

        if not os.path.exists(filepath):
            # Create a new daily log with the task
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(f"\n{section_header}\n{task_line}\n")
                return
            except Exception as e:
                raise RuntimeError(f"Failed to create daily log {filepath}: {e}")

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Find the section index
            section_idx = -1
            for idx, line in enumerate(lines):
                if line.strip() == section_header:
                    section_idx = idx
                    break

            if section_idx != -1:
                # Find the end of the section (either next header '##' or '---' or end of file)
                insert_idx = len(lines)
                for idx in range(section_idx + 1, len(lines)):
                    stripped = lines[idx].strip()
                    # If we find another header or section separator
                    if stripped.startswith('##') or stripped == '---':
                        insert_idx = idx
                        break

                # Backtrack to find the last non-empty line before the next header to avoid inserting inside empty lines
                while insert_idx > section_idx + 1 and lines[insert_idx - 1].strip() == "":
                    insert_idx -= 1
                
                # Append task inside the section
                lines.insert(insert_idx, task_line + '\n')
            else:
                # If section doesn't exist, append header and task to the end
                if len(lines) > 0 and not lines[-1].endswith('\n'):
                    lines[-1] = lines[-1] + '\n'
                lines.append('\n' + section_header + '\n')
                lines.append(task_line + '\n')

            # Atomic write
            dir_name = os.path.dirname(filepath)
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as temp_file:
                temp_file.writelines(lines)
                temp_path = temp_file.name

            os.replace(temp_path, filepath)
        except Exception as e:
            raise RuntimeError(f"Failed to append task to daily log {filepath}: {e}")
