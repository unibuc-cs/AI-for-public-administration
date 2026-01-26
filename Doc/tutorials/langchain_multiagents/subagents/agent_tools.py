# ============================================================================
# Step 1: Define low-level API tools (stubbed)
# ============================================================================


from langchain.tools import tool

@tool
def create_calendar_event(
    title: str,
    start_time: str,       # ISO format: "2024-01-15T14:00:00"
    end_time: str,         # ISO format: "2024-01-15T15:00:00"
    attendees: list[str],  # email addresses
    location: str = ""
) -> str:
    """Create a calendar event. Requires exact ISO datetime format."""
    # Stub: In practice, this would call Google Calendar API, Outlook API, etc.
    return f"Event created: {title} from {start_time} to {end_time} with {len(attendees)} attendees"


@tool
def send_email(
    to: list[str],  # email addresses
    subject: str,
    body: str,
    cc: list[str] = []
) -> str:
    """Send an email via email API. Requires properly formatted addresses."""
    # Stub: In practice, this would call SendGrid, Gmail API, etc.
    return f"Email sent to {', '.join(to)} - Subject: {subject}"


@tool
def get_available_time_slots(
    attendees: list[str],
    date: str,  # ISO format: "2024-01-15"
    duration_minutes: int
) -> list[str]:
    """Check calendar availability for given attendees on a specific date."""
    # Stub: In practice, this would query calendar APIs
    return ["09:00", "14:00", "16:00"]

@tool
def read_inbox(
    folder: str = "inbox",
    unread_only: bool = True,
    max_emails: int = 5
) -> list[dict]:
    """Read emails from inbox. Returns a list of email summaries."""
    # Stub: In practice, this would call Gmail API, Outlook API, etc.
    return [{"from": "X", "subject": "Y", "snippet": "Z"} for _ in range(max_emails)]

@tool
def add_todo_item(
    task: str,
    due_date: str = ""  # ISO format: "2024-01-20"
) -> str:
    """Add a to-do item to the task manager."""
    # Stub: In practice, this would call Todoist API, Microsoft To Do API, etc.
    return f"To-do item added: {task} with due date {due_date}"

def get_todo_list(
    filter: str = "all"  # options: "all", "completed", "pending"
) -> list[dict]:
    """Retrieve to-do list items based on filter."""
    # Stub: In practice, this would call Todoist API, Microsoft To Do API, etc.
    return [{"task": "Task 1", "status": "pending"}, {"task": "Task 2", "status": "completed"}]