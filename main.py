import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import crud
import models
import schemas
import wcl_service
from database import engine, get_db, init_db, AsyncSessionLocal # Import AsyncSessionLocal
import logging # Import logging
import os # Import os
import httpx # ADDED IMPORT
from pydantic import BaseModel # Ensure BaseModel is imported here
from typing import List, Optional, Dict
from datetime import datetime, timezone # Add datetime, timezone
from fastapi.background import BackgroundTasks # Import BackgroundTasks

# logger instance creation
logger = logging.getLogger(__name__)

# Ensure WCL environment variables are set (example)
if not os.getenv("WCL_CLIENT_ID") or not os.getenv("WCL_CLIENT_SECRET"):
    logger.warning("WCL_CLIENT_ID or WCL_CLIENT_SECRET environment variables are not set.")
    # Depending on strictness, you might want to raise an exception or exit here
    # raise EnvironmentError("Missing WCL API credentials in environment variables.")

# Create database tables on startup
app = FastAPI(title="Warcraft Logs Analyzer")


def _parse_table_entries(table_data: dict) -> dict:
    """Parses entries from a WCL table (damage/healing) and returns player stats.

    Args:
        table_data: The dictionary representing the 'damageTable' or 'healingTable' JSON blob.

    Returns:
        A dictionary mapping player ID to their stats: 
        { player_id: {'name': str, 'server': str | None, 'total': float} }
    """
    player_stats = {}
    if not table_data or not isinstance(table_data, dict):
        logger.warning("_parse_table_entries: Received invalid table_data input.")
        return player_stats

    entries = table_data.get('data', {}).get('entries', [])
    if not isinstance(entries, list):
        logger.warning(f"_parse_table_entries: Expected 'entries' to be a list, got {type(entries)}.")
        return player_stats

    logger.debug(f"_parse_table_entries: Parsing {len(entries)} entries.")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            logger.warning(f"_parse_table_entries: Skipping entry {i+1}, not a dictionary.")
            continue
            
        player_id = entry.get("id")
        if player_id is None:
            logger.warning(f"_parse_table_entries: Skipping entry {i+1} due to missing player ID.")
            continue

        total_value = entry.get("total")
        try:
            parsed_total = float(total_value) if total_value is not None else 0.0
        except (ValueError, TypeError):
            logger.warning(f"_parse_table_entries: Could not convert total '{total_value}' to float for player ID {player_id}. Setting to 0.0.")
            parsed_total = 0.0

        player_stats[player_id] = {
            "name": entry.get("name", "Unknown Name"),
            "server": entry.get("server"), # Can be None
            "total": parsed_total
        }
    
    logger.debug(f"_parse_table_entries: Parsed stats for {len(player_stats)} players.")
    return player_stats


@app.on_event("startup")
async def on_startup():
    """Initialize the database when the application starts."""
    print("Initializing database...")
    await init_db()
    print("Database initialized.")


class ProcessReportResponse(BaseModel):
    message: str


async def _process_report_background(report_url: str):
    """Background task to fetch, process, and store report data."""
    logger.info(f"Starting background processing for report URL: {report_url}")
    report_code = report_url.split('/')[-1]
    # Use AsyncSessionLocal directly for background tasks
    async with AsyncSessionLocal() as db: # Use AsyncSessionLocal directly
        try:
            # Step 1: Fetch processed data structure from WCL Service
            logger.info(f"Fetching and processing report data for {report_code} via WCL Service...")
            # Expected structure: {"metadata": {...}, "player_details_raw": {...}, "fight_data": {fight_id: {...}}}
            report_data = await wcl_service.fetch_report_data(report_code)
            if not report_data:
                logger.error(f"WCL Service failed to return data for {report_code}.")
                return # Stop processing

            # Extract components from the returned structure
            report_metadata = report_data.get("metadata")
            fight_data_dict = report_data.get("fight_data") # Dict: {fight_id: {name, damageTable, healingTable}}

            # --- Overwrite Logic --- 
            logger.info(f"Ensuring any existing data for report {report_code} is removed before processing...")
            await crud.delete_report_by_code(db, report_code)
            # --- End Overwrite Logic ---

            # Step 2: Create Report record using extracted metadata
            logger.info(f"Creating new report record for {report_code}...")
            if not report_metadata or not report_metadata.get("code"):
                 logger.error(f"Missing critical 'metadata' or report code in data from WCL service for {report_code}")
                 raise ValueError(f"Missing critical metadata from WCL service for {report_code}")

            # Perform timestamp conversion here
            start_time_ms = report_metadata.get("startTime")
            end_time_ms = report_metadata.get("endTime")
            start_time_dt = datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc) if start_time_ms else None
            end_time_dt = datetime.fromtimestamp(end_time_ms / 1000, tz=timezone.utc) if end_time_ms else None
            if not start_time_dt or not end_time_dt:
                 logger.error(f"Missing or invalid startTime/endTime in metadata for {report_code}")
                 raise ValueError(f"Missing or invalid startTime/endTime for {report_code}")

            report_create = schemas.ReportCreate(
                report_code=report_metadata["code"],
                title=report_metadata.get("title", "Untitled Report"),
                owner=report_metadata.get("owner", "Unknown Owner"),
                start_time=start_time_dt,
                end_time=end_time_dt,
                zone_id=report_metadata.get("zone_id"),
                zone_name=report_metadata.get("zone_name", "Unknown Zone")
            )
            db_report = await crud.create_report(db=db, report=report_create)
            logger.info(f"Created report {db_report.report_code} with ID {db_report.id}")

            # Step 4: Process Fights using the pre-fetched fight_data
            if not fight_data_dict:
                 logger.warning(f"No fight data (tables) returned by WCL service for report {report_code}")
            else:
                logger.info(f"Processing {len(fight_data_dict)} fights with pre-fetched tables...")
                
                # Get original fights list from metadata for encounter IDs
                original_fights_list = report_metadata.get("fights", [])
                fight_id_to_encounter_id = {f['id']: f['encounterID'] for f in original_fights_list if isinstance(f, dict)}

                for fight_id_str, fight_details in fight_data_dict.items():
                    try:
                        wcl_fight_id = int(fight_id_str) # fight_id from WCL is the key
                    except (ValueError, TypeError):
                        logger.warning(f"Skipping fight data with invalid key '{fight_id_str}' in report {report_code}")
                        continue
                        
                    fight_name = fight_details.get("name", f"Fight {wcl_fight_id}")
                    boss_id = fight_id_to_encounter_id.get(wcl_fight_id) # Get encounterID from original list
                    logger.debug(f"Processing Fight WCL ID: {wcl_fight_id}, Name: {fight_name}, Boss ID: {boss_id}")

                    # Create Fight record in DB
                    fight_create = schemas.FightCreate(
                        report_id=db_report.id,
                        wcl_fight_id=wcl_fight_id,
                        name=fight_name,
                        boss_id=boss_id 
                    )
                    db_fight = await crud.create_fight(db=db, fight=fight_create)
                    logger.debug(f"Created fight record with ID {db_fight.id}")

                    # Parse the damage/healing tables provided in fight_details
                    damage_table = fight_details.get("damageTable")
                    healing_table = fight_details.get("healingTable")

                    # Use the existing helper function to parse entries
                    damage_stats = _parse_table_entries(damage_table) # Returns {wcl_player_id: {name, server, total}}
                    healing_stats = _parse_table_entries(healing_table)

                    # Combine damage and healing per player for this fight
                    # Use WCL player IDs from table parser as keys
                    all_wcl_player_ids = set(damage_stats.keys()) | set(healing_stats.keys())
                    logger.debug(f"Found {len(all_wcl_player_ids)} unique players in tables for fight {wcl_fight_id}")

                    for wcl_player_id in all_wcl_player_ids:
                        dmg_info = damage_stats.get(wcl_player_id, {})
                        heal_info = healing_stats.get(wcl_player_id, {})
                        
                        # Prioritize name/server from damage table, fallback to healing
                        player_name = dmg_info.get("name") or heal_info.get("name")
                        player_server = dmg_info.get("server") or heal_info.get("server") 
                        damage_done = dmg_info.get("total", 0.0)
                        healing_done = heal_info.get("total", 0.0)

                        if not player_name:
                            logger.warning(f"Could not determine player name for WCL ID {wcl_player_id} in fight {wcl_fight_id}. Skipping stats.")
                            continue
                        
                        # Get or Create Player record in our DB, linking to this report
                        # Player model is unique by (report_id, name)
                        db_player = await crud.get_or_create_player(
                            db=db, 
                            report_id=db_report.id, 
                            player_name=player_name, 
                            player_server=player_server
                        )

                        # Create PlayerFightStats record
                        stats_create = schemas.PlayerFightStatsCreate(
                            player_id=db_player.id, # Use our internal DB player ID
                            fight_id=db_fight.id, 
                            damage_done=damage_done, 
                            healing_done=healing_done
                        )
                        await crud.create_player_fight_stats(db=db, stats=stats_create)
                        # logger.debug(f"  Saved stats for Player DB ID {db_player.id} ({player_name}) in Fight ID {db_fight.id}")
                 
                    logger.info(f"Finished saving stats for fight {db_fight.id} ('{fight_name}'). Processed {len(all_wcl_player_ids)} players.")

            # Step 5: Commit the transaction
            await db.commit()
            logger.info(f"Successfully processed and stored data for report {report_code}")

        except Exception as e:
            logger.error(f"Error processing report {report_code} in background: {e}", exc_info=True)
            await db.rollback() # Rollback on any error


@app.post("/process-report/", status_code=status.HTTP_202_ACCEPTED, response_model=ProcessReportResponse)
async def process_warcraft_log_report(
    request: schemas.ReportProcessRequest,
    background_tasks: BackgroundTasks # Keep BackgroundTasks
):
    """
    Accepts a Warcraft Logs report URL and schedules background processing.
    Validates the URL and ensures a report code can be extracted.
    The actual fetching, deletion, and storing happens in the background.
    Returns immediately with a confirmation message.
    """
    report_url_str = str(request.report_url) # Convert HttpUrl to string for background task
    report_code = wcl_service.extract_report_code(report_url_str)

    if not report_code:
        logger.error(f"Could not extract report code from URL: {report_url_str}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not extract report code from URL: {report_url_str}"
        )

    logger.info(f"Received request to process report: {report_code} from URL: {report_url_str}")

    # Schedule the background task
    background_tasks.add_task(_process_report_background, report_url_str)
    logger.info(f"Background task scheduled for report {report_code}")

    # Return immediately
    return ProcessReportResponse(message=f"Report processing for {report_code} started in the background.")


@app.get("/reports/{report_code}/detailed", response_model=schemas.ReportDetail)
async def read_detailed_report(report_code: str, db: AsyncSession = Depends(get_db)):
    """Retrieves a detailed report including all fights and player stats."""
    db_report = await crud.get_detailed_report_by_code(db, report_code=report_code)
    if db_report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return db_report

@app.post("/reports/{report_code}/aggregate-stats", response_model=schemas.GroupStatsResponse)
async def get_aggregated_stats(
    report_code: str,
    group_def: schemas.GroupDefinitionRequest,
    boss_names: Optional[List[str]] = Query(None, description="Optional list of boss names to filter by (e.g., 'Kurog Grimtotem', 'Terros'). Repeat the parameter for multiple names: ?boss_names=Kurog&boss_names=Terros"),
    db: AsyncSession = Depends(get_db)
):
    """Calculates aggregated damage AND healing for defined player groups in a report,
    broken down by player.

    - **report_code**: The unique code of the Warcraft Logs report.
    - **Request Body**: A JSON object mapping group names to lists of player names.
      Example: `{"group1": ["PlayerA", "PlayerB"], "group2": ["PlayerC"]}`
    - **boss_names** (Query Parameter): Optional. A list of exact boss/encounter names to filter the calculation.
      If omitted, stats across all fights in the report are aggregated.
      Example: `?boss_names=Terros&boss_names=Kurog%20Grimtotem` (URL encoded)
    """
    logger.info(f"Received request to aggregate stats for report {report_code}, groups: {group_def.groups}, boss_names: {boss_names}")

    # Call the updated CRUD function
    group_stats_data = await crud.aggregate_stats_by_group(
        db=db,
        report_code=report_code,
        groups=group_def.groups,
        boss_names=boss_names
    )

    # Return using the updated response schema
    return schemas.GroupStatsResponse(group_stats=group_stats_data)

# Add a simple root endpoint for testing
@app.get("/")
async def read_root():
    return {"message": "Welcome to the Warcraft Logs Analyzer API"}

# If running this script directly (for debugging, not recommended for production)
if __name__ == "__main__":
    import uvicorn
    print("Starting Uvicorn server...")
    # You would typically run this with: uvicorn main:app --reload --port 8000
    # Running directly requires uvicorn to be installed globally or in the venv
    uvicorn.run(app, host="0.0.0.0", port=8000)
