# Warcraft Logs Analyzer

This project provides a FastAPI-based API to fetch, process, and store detailed player statistics (damage and healing) from Warcraft Logs reports on a per-fight basis.

## Features

*   Fetches report metadata and fight details from the Warcraft Logs (WCL) GraphQL API v2.
*   Fetches player damage and healing data for each boss fight in a report.
*   Stores report, fight, player, and per-fight statistics in a local SQLite database.
*   Provides API endpoints to process new reports and retrieve stored detailed report data.
*   Uses asynchronous operations (async/await) for efficient I/O.

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
    *   Fetches data from WCL, parses it, and stores it in the database.
    *   **Request Body:**
        ```json
        {
          "report_url": "https://www.warcraftlogs.com/reports/YourReportCode"
        }
        ```
    *   **Success Response (201 Created):**
        ```json
        {
          "message": "Report YourReportCode processed successfully. Stored data for X fights."
        }
        ```

*   **`GET /reports/{report_code}/detailed`**: 
    *   Retrieves detailed information for a previously processed report, including all fights and associated player statistics.
    *   **Path Parameter:** `report_code` (e.g., `4pGyK631TMWdCwVJ`)
    *   **Success Response (200 OK):** Returns a JSON object representing the detailed report structure (see `schemas.py` -> `ReportDetail` for the exact structure).
    *   **Error Response (404 Not Found):** If the report code is not found in the database.

## Database

The application uses SQLite by default (`database.db`). The database schema is defined in `models.py` using SQLAlchemy. The database is automatically created with the necessary tables when the application starts if the file doesn't exist.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.