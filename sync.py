import os
import sys
import json
import datetime
import urllib.parse
from things_api import ThingsAPI
from obsidian_api import ObsidianAPI

METADATA_FILE = "sync_metadata.json"

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

def load_metadata():
    metadata_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), METADATA_FILE)
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to read metadata file: {e}. Starting fresh.")
        return {}

def save_metadata(metadata):
    metadata_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), METADATA_FILE)
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error: Failed to save metadata file: {e}")

def main():
    config = load_config()
    metadata = load_metadata()
    
    vault_path = config["obsidian_vault_path"]
    logs_relative = config["daily_logs_relative_path"]
    db_path = config["things_db_path"]
    sync_days = config.get("sync_days", 7)
    
    # Extract Obsidian vault name from path
    vault_name = os.path.basename(os.path.normpath(vault_path))
    
    print("Initializing sync (Obsidian Read-Only Mode)...")
    print(f"Obsidian Vault: {vault_path} (Name: {vault_name})")
    print(f"Things DB: {db_path}")
    print(f"Sync Window: Last {sync_days} days")
    print("-" * 50)
    
    try:
        things = ThingsAPI(db_path)
        obsidian = ObsidianAPI(vault_path, logs_relative)
    except Exception as e:
        print(f"Failed to initialize APIs: {e}")
        sys.exit(1)
        
    today = datetime.date.today()
    metadata_changed = False
    
    # Sync tasks from Obsidian Daily Logs -> Things
    for i in range(sync_days):
        target_date = today - datetime.timedelta(days=i)
        date_str = target_date.strftime("%Y%m%d")
        filepath = obsidian.get_daily_log_path(date_str)
        
        if not os.path.exists(filepath):
            continue
            
        print(f"Scanning log: {date_str}.md")
        tasks = obsidian.parse_daily_log(filepath)
        
        if date_str not in metadata:
            metadata[date_str] = {}
            metadata_changed = True
            
        for task in tasks:
            title = task["title"]
            completed = task["completed"]
            task_hash = task["hash"]
            legacy_uuid = task["legacy_uuid"]
            
            # Lookup UUID from metadata database first, fallback to legacy inline UUID
            uuid = metadata[date_str].get(task_hash) or legacy_uuid
            
            # If the legacy inline UUID was found but not in metadata database, save it
            if legacy_uuid and task_hash not in metadata[date_str]:
                metadata[date_str][task_hash] = legacy_uuid
                metadata_changed = True
                uuid = legacy_uuid
                
            # Case A: Task has no Things UUID mapped -> Create it in Things
            if not uuid:
                # Create obsidian link for Things Notes
                rel_filepath = os.path.join(logs_relative, f"{date_str}.md")
                encoded_path = urllib.parse.quote(rel_filepath)
                obsidian_link = f"obsidian://open?vault={urllib.parse.quote(vault_name)}&file={encoded_path}"
                
                print(f"  [+] Creating task in Things: '{title}'")
                try:
                    new_uuid = things.create_task(title, notes=obsidian_link)
                    
                    # Update metadata mapping locally
                    metadata[date_str][task_hash] = new_uuid
                    metadata_changed = True
                    
                    # If it was already completed in Obsidian, mark it completed in Things too
                    if completed:
                        print(f"  [~] Marking task as completed in Things: '{title}'")
                        things.update_task_status(new_uuid, 'completed')
                except Exception as e:
                    print(f"  [!] Failed to create task in Things: {e}")
            
            # Case B: Task is already mapped to a Things UUID -> Status Sync (Obsidian -> Things)
            else:
                try:
                    things_task = things.get_task_by_uuid(uuid)
                    if not things_task:
                        print(f"  [!] Task with UUID {uuid} not found in Things DB (deleted?). Skipping.")
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
                        # Things is completed, but Obsidian is Read-only. Log and skip.
                        pass
                except Exception as e:
                    print(f"  [!] Error checking status for task '{title}' ({uuid}): {e}")
                    
    # Save metadata mapping file if changed
    if metadata_changed:
        print("[*] Saving metadata updates to sync_metadata.json...")
        save_metadata(metadata)
        
    print("-" * 50)
    print("Sync complete!")

if __name__ == "__main__":
    main()
