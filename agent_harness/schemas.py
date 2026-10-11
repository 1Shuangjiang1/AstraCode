VALID_MSG_TYPES = ["message", "broadcast", "shutdown_request", "shutdown_response", "plan_approval_response"]


def schema(name, description, properties=None, required=None):
    result = {"name": name, "description": description,
              "input_schema": {"type": "object", "properties": properties or {}}}
    if required:
        result["input_schema"]["required"] = required
    return result


FILE_TOOLS = [
    schema("set_working_directory", "Select the active working directory. In chat workspace mode, call this before using file or shell tools. Directory changes are permission checked.",
           {"path": {"type": "string"}}, ["path"]),
    schema("bash", "Run a non-interactive PowerShell command on Windows. Prefer the dedicated file tools for CRUD and existence checks. Commands must terminate; do not start watchers, servers, or interactive programs unless explicitly requested.", {"command": {"type": "string"}}, ["command"]),
    schema("read_file", "Read file contents.", {"path": {"type": "string"}, "limit": {"type": "integer"}}, ["path"]),
    schema("list_directory", "List files and directories at a workspace-relative path.",
           {"path": {"type": "string", "default": "."}}),
    schema("path_exists", "Check whether a workspace-relative path exists without treating absence as an error.",
           {"path": {"type": "string"}}, ["path"]),
    schema("write_file", "Write content to file.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    schema("edit_file", "Replace one unique exact text occurrence.",
           {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
           ["path", "old_text", "new_text"]),
    schema("delete_file", "Delete one workspace file. This is idempotent: an already absent file is a successful result.",
           {"path": {"type": "string"}}, ["path"]),
]

TEAMMATE_TOOLS = FILE_TOOLS + [
    schema("send_message", "Send message.", {"to": {"type": "string"}, "content": {"type": "string"}}, ["to", "content"]),
    schema("idle", "Signal no more work."),
    schema("claim_task", "Claim task by ID.", {"task_id": {"type": "integer"}}, ["task_id"]),
]

TOOLS = FILE_TOOLS + [
    schema("TodoWrite", "Update task tracking list.", {"items": {"type": "array", "items": {"type": "object",
        "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                       "activeForm": {"type": "string"}}, "required": ["content", "status", "activeForm"]}}}, ["items"]),
    schema("task", "Spawn a subagent.", {"prompt": {"type": "string"}, "agent_type": {"type": "string", "enum": ["Explore", "general-purpose"]}}, ["prompt"]),
    schema("load_skill", "Load specialized knowledge.", {"name": {"type": "string"}}, ["name"]),
    schema("compress", "Compress conversation context."),
    schema("background_run", "Run a command in background.", {"command": {"type": "string"}, "timeout": {"type": "integer"}}, ["command"]),
    schema("check_background", "Check background status.", {"task_id": {"type": "string"}}),
    schema("task_create", "Create persistent task.", {"subject": {"type": "string"}, "description": {"type": "string"}}, ["subject"]),
    schema("task_get", "Get task details.", {"task_id": {"type": "integer"}}, ["task_id"]),
    schema("task_update", "Update task.", {"task_id": {"type": "integer"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]},
        "add_blocked_by": {"type": "array", "items": {"type": "integer"}},
        "remove_blocked_by": {"type": "array", "items": {"type": "integer"}}}, ["task_id"]),
    schema("task_list", "List all tasks."),
    schema("spawn_teammate", "Spawn autonomous teammate.", {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, ["name", "role", "prompt"]),
    schema("list_teammates", "List teammates."),
    schema("send_message", "Send teammate message.", {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": VALID_MSG_TYPES}}, ["to", "content"]),
    schema("read_inbox", "Read and drain lead inbox."),
    schema("broadcast", "Send to all teammates.", {"content": {"type": "string"}}, ["content"]),
    schema("shutdown_request", "Request teammate shutdown.", {"teammate": {"type": "string"}}, ["teammate"]),
    schema("plan_approval", "Approve or reject a teammate plan.", {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, ["request_id", "approve"]),
    schema("idle", "Enter idle state."),
    schema("claim_task", "Claim task.", {"task_id": {"type": "integer"}}, ["task_id"]),
]
