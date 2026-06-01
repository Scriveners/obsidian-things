import os
import sys
import json
import datetime
import urllib.parse
from things_api import ThingsAPI
from obsidian_api import ObsidianAPI

def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        print("Please copy config.json.example to config.json and fill in your settings.")
        sys.exit(1)
        
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        required_fields = ["obsidian_vault_path", "daily_logs_relative_path", "things_db_path"]
        for field in required_fields:
            if not config.get(field):
                print(f"Error: Missing or empty configuration field '{field}' in config.json")
                sys.exit(1)
        return config
    except Exception as e:
        print(f"Error reading configuration file: {e}")
        sys.exit(1)

def main():
    config = load_config()
    
    vault_path = config["obsidian_vault_path"]
    logs_relative = config["daily_logs_relative_path"]
    db_path = config["things_db_path"]
    sync_days = config.get("sync_days", 7)
    import_tag = config.get("things_import_tag", "obsidian")
    
    # Extract Obsidian vault name from path
    vault_name = os.path.basename(os.path.normpath(vault_path))
    
    print("Initializing sync...")
    print(f"Obsidian Vault: {vault_path} (Name: {vault_name})")
    print(f"Things DB: {db_path}")
    print(f"Sync Window: Last {sync_days} days")
    print(f"Things Import Tag: '{import_tag}'")
    print("-" * 50)
    
    try:
        things = ThingsAPI(db_path)
        obsidian = ObsidianAPI(vault_path, logs_relative)
    except Exception as e:
        print(f"Failed to initialize APIs: {e}")
        sys.exit(1)
        
    today = datetime.date.today()
    
    # 1. Sync tasks from Obsidian Daily Logs to Things
    print("Step 1: Syncing Obsidian Daily Logs -> Things 3")
    for i in range(sync_days):
        target_date = today - datetime.timedelta(days=i)
        date_str = target_date.strftime("%Y%m%d")
        filepath = obsidian.get_daily_log_path(date_str)
        
        if not os.path.exists(filepath):
            continue
            
        print(f"Scanning log: {date_str}.md")
        tasks = obsidian.parse_daily_log(filepath)
        
        updates = {}
        for task in tasks:
            line_no = task["line_no"]
            title = task["title"]
            completed = task["completed"]
            uuid = task["uuid"]
            indent = task["indent"]
            raw_line = task["raw_line"]
            
            # Case A: Task has no Things UUID -> Create it in Things
            if not uuid:
                # Create obsidian link for Things Notes
                rel_filepath = os.path.join(logs_relative, f"{date_str}.md")
                encoded_path = urllib.parse.quote(rel_filepath)
                obsidian_link = f"obsidian://open?vault={urllib.parse.quote(vault_name)}&file={encoded_path}"
                
                print(f"  [+] Creating task in Things: '{title}'")
                try:
                    new_uuid = things.create_task(title, notes=obsidian_link)
                    
                    # If it was already completed in Obsidian, mark it completed in Things too
                    if completed:
                        print(f"  [~] Marking task as completed in Things: '{title}'")
                        things.update_task_status(new_uuid, 'completed')
                        new_line = f"{indent}- [x] {title} %%things:{new_uuid}%%"
                    else:
                        new_line = f"{indent}- [ ] {title} %%things:{new_uuid}%%"
                        
                    updates[line_no] = new_line
                except Exception as e:
                    print(f"  [!] Failed to create task in Things: {e}")
            
            # Case B: Task has Things UUID -> Bidirectional Status Sync
            else:
                try:
                    things_task = things.get_task_by_uuid(uuid)
                    if not things_task:
                        print(f"  [!] Task with UUID {uuid} not found in Things DB (deleted/archived?). Skipping.")
                        continue
                        
                    if things_task["trashed"]:
                        continue
                        
                    things_status = things_task["status"]
                    
                    # Status mapping: 3 = Completed, 1 = Canceled, 0 = Open
                    if completed and things_status not in [3, 1]:
                        # Obsidian completed, Things is open -> Complete in Things
                        print(f"  [-> Things] Completing task: '{title}'")
                        things.update_task_status(uuid, 'completed')
                    elif not completed and things_status in [3, 1]:
                        # Obsidian is open, Things is completed/canceled -> Check off in Obsidian
                        status_name = "completed" if things_status == 3 else "canceled"
                        print(f"  [-> Obsidian] Syncing '{status_name}' status for: '{title}'")
                        new_line = f"{indent}- [x] {title} %%things:{uuid}%%"
                        updates[line_no] = new_line
                except Exception as e:
                    print(f"  [!] Error syncing status for task '{title}' ({uuid}): {e}")
                    
        # Apply updates to daily log file if there are any
        if updates:
            print(f"  [*] Writing {len(updates)} updates to {date_str}.md")
            try:
                obsidian.update_tasks_in_file(filepath, updates)
            except Exception as e:
                print(f"  [!] Failed to update file {filepath}: {e}")
                
    print("-" * 50)
    
    # 2. Import tagged tasks from Things -> Obsidian Today's Daily Log
    if import_tag:
        print(f"Step 2: Importing new tasks with tag '{import_tag}' from Things -> Obsidian Today")
        try:
            tagged_tasks = things.get_tasks_by_tag(import_tag)
            
            if not tagged_tasks:
                print("  No new tagged tasks found in Things.")
            else:
                today_date_str = today.strftime("%Y%m%d")
                today_filepath = obsidian.get_daily_log_path(today_date_str)
                
                # Fetch existing obsidian tasks to prevent duplicates
                existing_tasks = obsidian.parse_daily_log(today_filepath)
                existing_uuids = {t["uuid"] for t in existing_tasks if t["uuid"]}
                
                for t_task in tagged_tasks:
                    t_uuid = t_task["uuid"]
                    t_title = t_task["title"]
                    t_notes = t_task["notes"]
                    
                    # Skip if already imported
                    if t_uuid in existing_uuids:
                        continue
                        
                    # Skip if notes already contain obsidian link (double-safety)
                    if "obsidian://open" in t_notes:
                        continue
                        
                    print(f"  [+] Importing tagged task: '{t_title}'")
                    # Append task to today's daily log
                    obsidian.add_task_to_section(today_filepath, t_title, t_uuid)
                    
                    # Update Things notes to reference the daily log link
                    rel_filepath = os.path.join(logs_relative, f"{today_date_str}.md")
                    encoded_path = urllib.parse.quote(rel_filepath)
                    obsidian_link = f"obsidian://open?vault={urllib.parse.quote(vault_name)}&file={encoded_path}"
                    
                    new_notes = f"{t_notes}\n\n{obsidian_link}".strip() if t_notes else obsidian_link
                    things.update_task_notes(t_uuid, new_notes)
        except Exception as e:
            print(f"  [!] Failed to import tagged tasks: {e}")
            
    print("-" * 50)
    print("Sync complete!")

if __name__ == "__main__":
    main()
