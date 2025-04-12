# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Support for processing and storing Damage, Heal, and Death events from Warcraft Logs reports.
- New database models (`DamageEvent`, `HealEvent`, `DeathEvent`) and corresponding Pydantic schemas.
- Bulk CRUD operations for new event types.
- Logic in background processing to parse and store new event types.
- Functionality to automatically delete existing data when re-processing a report via the `/process-report/` endpoint, ensuring data completeness.
- API endpoint `GET /reports/` to list basic report information.
- API endpoint `GET /reports/{report_code}/` to retrieve detailed report information including fights and players.
- API endpoint `GET /reports/{report_code}/fights/{wcl_fight_id}/events/` to retrieve events for a specific fight, with optional `event_type` filtering.
- Corresponding Pydantic schemas (`ReportReadBasic`, `ReportReadDetailed`, `AnyEventRead`) and CRUD functions (`get_reports`, `get_detailed_report_by_code`, `get_fight_by_report_code_and_wcl_id`, `get_events_for_fight`).
- `delete_report` CRUD function to remove a report and its associated data before re-processing.
- Alembic migration for new event tables.

### Changed
- Reordered models in `models.py` to resolve relationship definition errors during Alembic migrations.
- Updated event processing loop in `main.py` to handle new event types and map relevant fields (including NPC targets).
- Updated `README.md` to reflect new features and database schema.
- Modified existing event processing loop in `main.py` to accommodate new event types.
- Updated `get_detailed_report_by_code` CRUD function to use eager loading for fights and players.

### Removed
- Redundant/unused API endpoints (`/reports/{report_code}/detailed`, `/reports/{report_code}/fights/{fight_id}/stats`).

### Fixed
- `NameError` during Alembic migration generation caused by model definition order.
- `AttributeError` when re-processing reports due to missing `crud.delete_report` function.
