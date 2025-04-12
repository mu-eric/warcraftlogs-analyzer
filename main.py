import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import crud
import models
import schemas
import wcl_service
from database import engine, get_db, init_db
import logging # Import logging
import os # Import os
import httpx # ADDED IMPORT
from pydantic import BaseModel # Ensure BaseModel is imported here
from typing import List, Optional, Dict

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

@app.post("/process-report/", status_code=status.HTTP_201_CREATED)
async def process_warcraft_log_report(
    request: schemas.ReportProcessRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Accepts a Warcraft Logs report URL, fetches data (mocked initially),
    and stores the report and player information in the database.
    """
    report_url = str(request.report_url) # Convert HttpUrl to string
    report_code = wcl_service.extract_report_code(report_url)

    if not report_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not extract report code from URL: {report_url}"
        )

    # 1. Check if report already exists
    db_report = await crud.get_report_by_code(db, report_code=report_code)
    if db_report:
        logger.info(f"Report {report_code} already exists in DB.")
        # If report exists, maybe fetch existing player stats or decide on update logic
        # For now, let's just return the existing report info
        # We might want to return associated player stats too
        # return db_report # Or potentially fetch and return players? Decide later.
        # Let's proceed to fetch/update player stats even if report exists
        pass # Continue processing even if report header exists

    logger.info("Fetching report data from WCL API...")
    try:
        # This now returns a dict: {"metadata": report_meta, "fight_data": {fight_id: fight_details}}
        processed_data = await wcl_service.fetch_report_data(report_code)
        logger.debug(f"MAIN: Received processed_data structure: {processed_data}") # Structure check

        if not processed_data or not processed_data.get("metadata") or processed_data.get("fight_data") is None: # Check fight_data exists, even if empty
            logger.error("Received incomplete data from WCL service. Missing 'metadata' or 'fight_data'.")
            raise HTTPException(status_code=404, detail="Report data incomplete or not found after processing.")
        
        report_metadata = processed_data["metadata"]
        fight_data_dict = processed_data["fight_data"]
        logger.debug(f"MAIN: Extracted metadata and {len(fight_data_dict)} fight entries.")

        logger.info(f"Report metadata fetched: {report_metadata.get('title', 'N/A')}")
        # Removed logging for aggregate player count, as it's now per fight

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Failed to fetch data from WCL API: {e.response.text}")
    except Exception as e:
        logger.exception("Error fetching report data from WCL.") # Use logger.exception to include stack trace
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred fetching data: {str(e)}")

    # --- Database Operations ---
    try:
        # Check again if report exists before trying to create
        db_report = await crud.get_report_by_code(db, report_code=report_code)
        if not db_report:
            logger.info(f"Report {report_code} not found in DB, creating new entry.")
            # Create Report Header
            report_to_create = schemas.ReportCreate(
                report_code=report_metadata["code"],
                title=report_metadata["title"],
                owner=report_metadata["owner"],
                start_time=report_metadata["startTime"],
                end_time=report_metadata["endTime"],
                zone_id=report_metadata["zone_id"],
                zone_name=report_metadata["zone_name"]
            )
            db_report = await crud.create_report(db=db, report=report_to_create)
            logger.info(f"Created report {db_report.report_code} with ID {db_report.id}")
            # Ensure db_report is the SQLAlchemy model instance for foreign key use
            # db_report = await crud.get_report_by_code(db, report_code=report_code) # Re-fetching might not be necessary if create_report returns the instance
        else:
             logger.info(f"Found existing report {report_code} with ID {db_report.id}. Updating if needed (not implemented yet). ")

        # Create a lookup map for encounterID from initial report data
        fight_id_to_encounter_id = {f['id']: f['encounterID'] for f in processed_data.get('metadata', {}).get('fights', [])}

        # --- Process Per-Fight Data (SAVE TO DB) --- 
        logger.info(f"Processing {len(fight_data_dict)} fights for report {report_code}...")
 
        for fight_id, fight_details in fight_data_dict.items():
            fight_name = fight_details.get("name", f"Fight {fight_id}")
            wcl_fight_id = int(fight_id) # fight_id from WCL is the key
            boss_id = fight_id_to_encounter_id.get(fight_id) # Map encounterID here
            logger.debug(f"MAIN: Processing Fight WCL ID: {wcl_fight_id}, Name: {fight_name}")

            # Create Fight record in DB
            fight_to_create = schemas.FightCreate(
                report_id=db_report.id,
                wcl_fight_id=wcl_fight_id,
                name=fight_name,
                boss_id=boss_id # Map encounterID here
            )
            db_fight = await crud.create_fight(db=db, fight=fight_to_create)

            damage_table = fight_details.get("damageTable")
            healing_table = fight_details.get("healingTable")

            damage_stats = _parse_table_entries(damage_table)
            healing_stats = _parse_table_entries(healing_table)

            # Combine damage and healing per player for this fight
            all_player_ids = set(damage_stats.keys()) | set(healing_stats.keys())

            for player_id in all_player_ids:
                dmg_info = damage_stats.get(player_id, {})
                heal_info = healing_stats.get(player_id, {})
                
                player_name = dmg_info.get("name") or heal_info.get("name") or "Unknown"
                player_server = dmg_info.get("server") or heal_info.get("server") # Take first non-None server
                damage_done = dmg_info.get("total", 0.0)
                healing_done = heal_info.get("total", 0.0)
                
                # Get or Create Player record for this report
                # Note: WCL player_id might differ from our DB player.id
                # We use name + report_id as the unique key for our Player model
                db_player = await crud.get_or_create_player(
                    db=db, 
                    report_id=db_report.id, 
                    player_name=player_name, 
                    player_server=player_server
                )

                # Create PlayerFightStats record
                stats_to_create = schemas.PlayerFightStatsCreate(
                    player_id=db_player.id, 
                    fight_id=db_fight.id, 
                    damage_done=damage_done, 
                    healing_done=healing_done
                )
                await crud.create_player_fight_stats(db=db, stats=stats_to_create)
                logger.debug(f"  Saved stats for Player ID {db_player.id} ({player_name}) in Fight ID {db_fight.id}")
             
            logger.info(f"Finished saving stats for fight {db_fight.id} ('{fight_name}'). Processed {len(all_player_ids)} players.")

        logger.info(f"Successfully processed and stored data for report {report_code}.")

        # Explicitly reload the report *without* players for now, as the relationship is changing
        logger.info(f"Re-fetching report {db_report.id} header before returning...")
        from sqlalchemy.orm import selectinload
        from sqlalchemy.future import select
        result = await db.execute(
            select(models.Report)
            .options(selectinload(models.Report.fights).selectinload(models.Fight.stats)) # Use .stats
            .options(selectinload(models.Report.players)) # Also load the players associated with the report
            .filter(models.Report.id == db_report.id)
        )
        final_report_to_return = result.scalars().first()

        if not final_report_to_return:
             # Should not happen, but handle defensively
             print(f"Error: Failed to re-fetch report {db_report.id} after creation.")
             raise HTTPException(status_code=500, detail="Failed to retrieve created report details")

        logger.info(f"Returning report {final_report_to_return.report_code} with {len(final_report_to_return.players)} players.")
        await db.commit() # Commit the transaction after successful processing
        return {"message": f"Report {report_code} processed successfully. Stored data for {len(fight_data_dict)} fights."} 

    except Exception as e:
        # Rollback changes if anything went wrong during processing/saving
        # Note: commit happens within CRUD functions, consider transaction management for multi-step operations
        print(f"Error processing or saving report data: {e}")
        # Attempt to delete the potentially partially created report if an error occurs later
        if 'db_report' in locals() and db_report.id:
             try:
                 await db.delete(db_report)
                 await db.commit()
                 print(f"Rolled back creation of report ID {db_report.id}")
             except Exception as del_e:
                 print(f"Failed to rollback report creation: {del_e}")
        
        await db.rollback() # Rollback on any other unexpected error
        logger.error(f"Unexpected error processing report {report_code}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {e}")

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
    boss_name: Optional[str] = Query(None, description="Optional boss name to filter by (e.g., 'Kurog Grimtotem')"),
    db: AsyncSession = Depends(get_db)
):
    """Calculates aggregated damage AND healing for defined player groups in a report,
    broken down by player.

    - **report_code**: The unique code of the Warcraft Logs report.
    - **Request Body**: A JSON object mapping group names to lists of player names.
      Example: `{"group1": ["PlayerA", "PlayerB"], "group2": ["PlayerC"]}`
    - **boss_name** (Query Parameter): Optional. The exact name of a boss/encounter to filter the calculation.
      If omitted, stats across all fights in the report are aggregated.
      Example: `?boss_name=Terros` or `?boss_name=Kurog%20Grimtotem` (URL encoded)
    """
    logger.info(f"Received request to aggregate stats for report {report_code}, groups: {group_def.groups}, boss_name: {boss_name}")

    # Call the updated CRUD function
    group_stats_data = await crud.aggregate_stats_by_group(
        db=db,
        report_code=report_code,
        groups=group_def.groups,
        boss_name=boss_name
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
