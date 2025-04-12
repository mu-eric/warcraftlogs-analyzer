# Warcraft Logs Analyzer

This project provides a FastAPI-based API to fetch, process, and store detailed event data (casts, buffs, damage, heal, death) from Warcraft Logs reports.

## Features

*   Fetches report metadata, fight details, and player information from the Warcraft Logs (WCL) GraphQL API v2.
*   Fetches detailed event data (casts, buffs, damage, heal, death) for each boss fight in a report.
*   Stores report, fight, player, and event data in a local SQLite database using SQLAlchemy.
*   Provides an API endpoint (`/process-report/`) to trigger the processing of new reports.
*   Handles re-processing of existing reports by clearing old data first to ensure completeness.
*   Uses asynchronous operations (async/await) for efficient I/O.
*   Uses Alembic for database schema migrations.

## Technology Stack

*   **Programming Language**: Python 3.11+
*   **Web Framework**: FastAPI
*   **Database ORM**: SQLAlchemy (with `aiosqlite` for async SQLite)
*   **Data Validation**: Pydantic
*   **API Client**: httpx
*   **Dependency Management**: uv (or pip)
*   **Environment Variables**: python-dotenv

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/mu-eric/warcraftlogs-analyzer.git
    cd warcraftlogs-analyzer
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install dependencies:**
    *   **Using uv (if installed):**
        ```bash
        uv pip install -r requirements.txt 
        # Or if reading directly from pyproject.toml:
        # uv pip install -p python3.13 .
        ```
    *   **Using pip:**
        ```bash
        pip install -r requirements.txt
        ```
        *(Note: You might need to generate `requirements.txt` from `pyproject.toml` first if it doesn't exist: `pip freeze > requirements.txt` or use a tool like `pip-tools`)*

## Environment Variables

Create a `.env` file in the project root directory and add the following variables:

```dotenv
# Warcraft Logs API v2 Credentials
WCL_CLIENT_ID=your_wcl_client_id
WCL_CLIENT_SECRET=your_wcl_client_secret

# Database URL (default is SQLite in the project root)
DATABASE_URL=sqlite+aiosqlite:///./database.db
```

*   Obtain your WCL Client ID and Secret from the [Warcraft Logs API documentation](https://www.warcraftlogs.com/api/docs/).
*   The `DATABASE_URL` defaults to a local SQLite file named `database.db`. You can change this if needed (e.g., for PostgreSQL).

## Running the Application

1.  **Start the FastAPI server:**
    ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```
    The `--reload` flag automatically restarts the server when code changes are detected.

2.  **Access the API:**
    *   The API will be available at `http://127.0.0.1:8000` (or `http://localhost:8000`).
    *   Interactive API documentation (Swagger UI) is available at `http://127.0.0.1:8000/docs`.
    *   Alternative API documentation (ReDoc) is available at `http://127.0.0.1:8000/redoc`.

## API Usage

*   **`POST /process-report/`**:
    *   Processes a given Warcraft Logs report URL.
    *   Fetches data from WCL, parses it, and stores report details, fights, players, and events (casts, buffs, damage, heal, death) in the database.
    *   If the report already exists in the database, its existing data (including fights, players, and all events) will be deleted before re-processing to ensure data integrity and completeness.
    *   **Request Body:**
        ```json
        {
          "report_url": "https://www.warcraftlogs.com/reports/YourReportCode"
        }
        ```
    *   **Success Response (202 Accepted):** Indicates the background processing task has started.
        ```json
        {
          "message": "Report processing initiated for YourReportCode. Check logs for details."
        }
        ```
    *   **Error Response (e.g., 400 Bad Request):** If the URL is invalid or the report code cannot be extracted.

*   **`GET /reports/`**:
    *   Retrieves a list of processed reports with basic information.
    *   Supports pagination using `skip` and `limit` query parameters.
    *   **Response Body:**
        ```json
        [
          {
            "id": 1,
            "report_code": "YourReportCode",
            "title": "YourReportTitle",
            "owner": "YourOwnerName",
            "start_time_ms": 1633072800000,
            "end_time_ms": 1633072800000,
            "zone_id": 1001,
            "zone_name": "YourZoneName"
          },
          ...
        ]
        ```

*   **`GET /reports/{report_code}/`**:
    *   Retrieves detailed information for a specific report, including lists of its fights and players.
    *   **Path Parameter:** `report_code` (e.g., `NpRcxdFjnL49QmhM`)
    *   **Success Response (200 OK):** Returns a JSON object with report details, nested fights, and nested players.
        ```json
        {
          "id": 1,
          "report_code": "NpRcxdFjnL49QmhM",
          "title": "Some Raid Title",
          "owner": "OwnerName",
          "start_time_ms": 1633072800000,
          "end_time_ms": 1633076400000,
          "zone_id": 1001,
          "fights": [
            { "id": 1, "wcl_fight_id": 1, "name": "Boss 1", "kill": true, ... },
            { "id": 2, "wcl_fight_id": 2, "name": "Trash", "kill": false, ... },
            ...
          ],
          "players": [
            { "id": 1, "wcl_actor_id": 101, "name": "Player One", "class_name": "Warrior", ... },
            { "id": 2, "wcl_actor_id": 102, "name": "Player Two", "class_name": "Mage", ... },
            ...
          ]
        }
        ```
    *   **Error Response (404 Not Found):** If the report code is not found.

*   **`GET /reports/{report_code}/fights/{wcl_fight_id}/events/`**:
    *   Retrieves a list of specific events for a given fight within a report.
    *   **Path Parameters:** `report_code`, `wcl_fight_id`
    *   **Query Parameter:** `event_type` (optional, comma-separated, e.g., `damage,heal`, `cast`, `death`). If omitted, potentially returns all event types (consider performance implications).
    *   **Success Response (200 OK):** Returns a list of event objects matching the criteria.
        ```json
        // Example for event_type=damage
        [
          { "id": 101, "fight_id": 1, "timestamp_ms": 1633072950123, "event_type": "damage", "source_player_id": 1, "target_npc_id": 501, "ability_game_id": 12345, "amount": 5000, ... },
          { "id": 105, "fight_id": 1, "timestamp_ms": 1633072952456, "event_type": "damage", "source_player_id": 2, "target_npc_id": 501, "ability_game_id": 67890, "amount": 7500, ... },
          ...
        ]
        ```
    *   **Error Response (404 Not Found):** If the report code or fight ID is not found.

## Database

The application uses SQLite by default (`database.db`). The database schema is defined in `models.py` using SQLAlchemy and includes tables for `reports`, `fights`, `players`, `player_cast_events`, `buff_events`, `damage_events`, `heal_events`, and `death_events`. Database migrations are managed using Alembic. Run `alembic upgrade head` to apply migrations.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.