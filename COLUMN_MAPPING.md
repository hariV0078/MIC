# Column Mapping Documentation

This document describes how the actual CSV/XLSX columns are mapped to the validation system's expected format.

## Column Mappings

| Actual CSV Column | Mapped To | Notes |
|-------------------|-----------|-------|
| `activity_name` | `Title` | Event title |
| `Objective` | `Objectives` | Event objectives |
| `benefit_learning` | `Learning Outcomes` | Learning outcomes |
| `event_theme` | `Theme` | Event theme |
| `event_type` | `Event Type` | Type of event (used for level determination) |
| `activity_duration` | `Duration` | Duration in hours (converted to "Xh" format) |
| `student_participants` + `faculty_participants` | `Participants` | Sum of student and faculty participants |
| `from_date` | `Event Date` | Event start date |
| `financial_year` | `Year Type` | Financial or Academic year |
| `session_type` | `Event Mode` | Online or Offline |
| `report` | `PDF Path` | PDF report path (with Azure Blob Storage base URL) |
| `photo1`, `photo2` | `Image Paths` | Comma-separated image paths (with Azure Blob Storage base URL) |
| `event_driven` | (used for path resolution) | Determines Azure Blob Storage base path |

## Level Determination

Level is automatically determined based on:
1. **Event Type** - Must match one of the event types for the level
2. **Duration** - Must fall within the duration range for the level

### Level Definitions

| Level | Event Types | Duration Range | Description |
|-------|-------------|----------------|-------------|
| **Level 1** | Expert Talk, Mentoring Session, Exposure Visit | 2 to 4 contact hours | Less than half a day |
| **Level 2** | Seminar, Workshop, Conference, Exposure Visit, Panel Discussion, Roundtable Discussion, Networking Event | 5 to 8 contact hours | One Full day |
| **Level 3** | Boot Camp, Workshop, Exhibition/ Startup Showcase, Demo Day, Competition, Hackathons, Conference | 9 to 18 contact hours | More than one day |
| **Level 4** | Challenge, Tech/ E-Fest, Hackathon, Competition, Workshop, Boot Camp, Exhibition/ Startup Showcase | Greater than 18 contact hours | More than 2 days |

### Level Validation

The system validates that:
- The event type matches one of the types for the determined level
- The duration falls within the expected range for that level

If either condition fails, the validation fails with an appropriate error message.

## Azure Blob Storage Path Resolution

PDF and image paths are resolved based on the `event_driven` field:

| event_driven | Base Path |
|--------------|-----------|
| 1 | `https://miciicsta01.blob.core.windows.net/miciiccontainer1/` |
| 2 | `https://miciicsta01.blob.core.windows.net/miciiccontainer1/` |
| 3 | `https://miciicsta01.blob.core.windows.net/miciiccontainer1/uploads/institutes` |
| 4 | `https://miciicsta01.blob.core.windows.net/miciiccontainer1/uploads/institutes` |

### Path Construction

- If the path in CSV is already a full URL (starts with `http`), it's used as-is
- If the path is relative, it's combined with the base path:
  - Base: `https://miciicsta01.blob.core.windows.net/miciiccontainer1/`
  - Relative: `reports/event1.pdf`
  - Result: `https://miciicsta01.blob.core.windows.net/miciiccontainer1/reports/event1.pdf`

## Example Mapping

### Input CSV Row:
```csv
activity_name,Objective,benefit_learning,event_theme,event_type,activity_duration,student_participants,faculty_participants,from_date,financial_year,session_type,report,photo1,photo2,event_driven
"AI Workshop","Learn AI basics","Understand ML concepts","AI","Workshop",6.0,25,5,"2024-03-15","2024-25","Offline","reports/ai_workshop.pdf","photos/photo1.jpg","photos/photo2.jpg",2
```

### Mapped Data:
```python
{
    "Title": "AI Workshop",
    "Objectives": "Learn AI basics",
    "Learning Outcomes": "Understand ML concepts",
    "Theme": "AI",
    "Event Type": "Workshop",
    "Duration": "6.0h",
    "Participants": "30",  # 25 + 5
    "Event Date": "2024-03-15",
    "Year Type": "2024-25",
    "Event Mode": "Offline",
    "Level": "2",  # Determined: Workshop with 6h duration = Level 2
    "PDF Path": "https://miciicsta01.blob.core.windows.net/miciiccontainer1/reports/ai_workshop.pdf",
    "Image Paths": "https://miciicsta01.blob.core.windows.net/miciiccontainer1/photos/photo1.jpg,https://miciicsta01.blob.core.windows.net/miciiccontainer1/photos/photo2.jpg"
}
```

## Notes

- All mappings preserve the original CSV row data for output
- Missing or empty values are handled gracefully (empty strings or defaults)
- Level determination is automatic but can be overridden if `expected_level` is provided in the CSV
- Azure Blob Storage URLs are currently logged but not downloaded (PDF/image extraction from URLs requires additional implementation)

