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


async def _process_report_background(report_code: str, db: AsyncSession):
    logger.info(f"Background processing started for report {report_code}")
    try:
        # === Pre-processing: Check and delete existing report data ===
        existing_report = await crud.get_report_by_code(db, report_code=report_code)
        if existing_report:
            logger.warning(f"Report {report_code} already exists. Deleting existing data before re-processing...")
            await crud.delete_report(db, report_code=report_code) # Cascade delete should handle related items
            await db.commit() # Commit the deletion
            logger.info(f"Existing data for report {report_code} deleted.")
        # =============================================================

        report_data = await wcl_service.fetch_report_data(report_code)
        if not report_data:
            logger.error(f"Failed to fetch report data for {report_code}")
            return

        metadata = report_data.get("metadata", {})
        fights_data = report_data.get("fights", [])
        master_data = report_data.get("master_data", {})
        events_data = report_data.get("events", {})
        all_events_raw = events_data.get("data", []) # Get the list from the nested 'data' key

        logger.info(f"Data fetched for {report_code}. Processing metadata, {len(fights_data)} fights, and {len(all_events_raw)} events.")

        # 1. Get or Create Report
        db_report = await crud.get_report_by_code(db, report_code=report_code)
        if not db_report:
            report_in = schemas.ReportCreate(
                report_code=metadata.get("report_code"),
                title=metadata.get("title"),
                start_time_ms=metadata.get("start_time_ms"),
                end_time_ms=metadata.get("end_time_ms"),
                zone_id=metadata.get("zone_id"),
                zone_name=metadata.get("zone_name")
            )
            db_report = await crud.create_report(db=db, report=report_in)
            logger.info(f"Created new report entry for {report_code} with ID {db_report.id}")
        else:
            logger.info(f"Found existing report entry for {report_code} with ID {db_report.id}")

        # 2. Process and store fights, creating a lookup map
        fight_lookup = {}
        for fight_raw in fights_data:
            fight_in = schemas.FightCreate(**fight_raw)
            db_fight = await crud.create_fight(db=db, fight=fight_in, report_id=db_report.id) # Pass report_id
            fight_lookup[db_fight.wcl_fight_id] = db_fight # Map WCL Fight ID to DB Fight object
            logger.debug(f"Processed fight WCL ID {db_fight.wcl_fight_id}, DB ID {db_fight.id}")

        # 3. Process players from master_data, creating a lookup map
        player_lookup = {}
        master_actors = master_data.get("actors", [])
        logger.info(f"Processing {len(master_actors)} players from master data.")
        for actor in master_actors:
            player_in = schemas.PlayerCreate(
                wcl_actor_id=actor.get("id"),
                name=actor.get("name"),
                class_name=actor.get("subType"), # Assuming subType is the class name
                server=actor.get("server")
            )
            # Use get_or_create, passing report_id and correct keyword
            db_player = await crud.get_or_create_player(
                db=db, 
                report_id=db_report.id, # Pass the report ID
                player_create_data=player_in # Use the correct keyword argument
            )
            player_lookup[db_player.wcl_actor_id] = db_player # Map WCL Actor ID to DB Player object
            logger.debug(f"Processed player WCL ID {db_player.wcl_actor_id}, DB ID {db_player.id}")

        # 4. Process Events (efficiently)
        logger.info(f"Processing {len(all_events_raw)} raw events...")
        cast_events_to_create = []
        buff_events_to_create = []
        damage_events_to_create = [] # Added
        heal_events_to_create = []   # Added
        death_events_to_create = []  # Added

        for event in all_events_raw:
            event_type = event.get("type")
            timestamp_ms = event.get("timestamp")
            wcl_fight_id = event.get("fight")
            ability_game_id = event.get("abilityGameID")
            source_wcl_id = event.get("sourceID")
            target_wcl_id = event.get("targetID")
            target_npc_wcl_id = event.get("targetNPCID") # For non-player targets

            # Get the corresponding DB fight object using the WCL fight ID
            db_fight = fight_lookup.get(wcl_fight_id)
            if not db_fight:
                # logger.warning(f"Skipping event: Could not find fight with WCL ID {wcl_fight_id}")
                continue # Skip event if its fight wasn't found/processed

            # Map WCL source/target Actor IDs to DB Player IDs
            # Source might be None for some events (e.g., environment)
            source_player = player_lookup.get(source_wcl_id) if source_wcl_id else None
            source_player_id = source_player.id if source_player else None

            target_player = player_lookup.get(target_wcl_id) if target_wcl_id else None
            target_player_id = target_player.id if target_player else None

            # Basic validation
            if timestamp_ms is None or ability_game_id is None:
                 # logger.warning(f"Skipping event due to missing timestamp or ability ID: {event}")
                 continue

            # --- Event Type Specific Processing ---
            if event_type == "cast":
                if not source_player_id:
                    # logger.warning(f"Skipping cast event: Missing source player ID for WCL ID {source_wcl_id}. Event: {event}")
                    continue # Casts must have a source player

                cast_event_in = schemas.PlayerCastEventCreate(
                    fight_id=db_fight.id,
                    timestamp_ms=timestamp_ms,
                    event_type=event_type,
                    ability_game_id=ability_game_id,
                    source_player_id=source_player_id, # Use DB player ID
                    target_player_id=target_player_id  # Use DB player ID (can be None)
                )
                cast_events_to_create.append(cast_event_in)

            elif event_type in ["applybuff", "removebuff", "applydebuff", "removedebuff", "applybuffstack", "removebuffstack"]:
                if not target_player_id:
                    # logger.warning(f"Skipping buff event: Missing target player ID for WCL ID {target_wcl_id}. Event: {event}")
                    continue # Buffs must have a target player

                buff_event_in = schemas.BuffEventCreate(
                    fight_id=db_fight.id,
                    timestamp_ms=timestamp_ms,
                    event_type=event_type,
                    ability_game_id=ability_game_id,
                    source_player_id=source_player_id, # Use DB player ID (can be None)
                    target_player_id=target_player_id, # Use DB player ID
                    buff_stack=event.get("stack", 0) # Assuming 'stack' exists for buffs
                )
                buff_events_to_create.append(buff_event_in)

            elif event_type == "damage":
                if not source_player_id:
                    # logger.warning(f"Skipping damage event: Missing source player ID for WCL ID {source_wcl_id}. Event: {event}")
                    continue # Damage must have a source player in our model
                if not target_player_id and not target_npc_wcl_id:
                    # logger.warning(f"Skipping damage event: Missing target player/NPC ID. Event: {event}")
                    continue # Damage must have a target (player or NPC)

                damage_event_in = schemas.DamageEventCreate(
                    fight_id=db_fight.id,
                    timestamp_ms=timestamp_ms,
                    source_player_id=source_player_id,
                    target_player_id=target_player_id, # Can be None if target is NPC
                    target_npc_id=target_npc_wcl_id if not target_player_id else None, # Only set if target isn't a player
                    ability_game_id=ability_game_id,
                    hit_type=event.get("hitType", 0), # Default to 0 if missing
                    amount=event.get("amount", 0),
                    mitigated=event.get("mitigated", 0),
                    absorbed=event.get("absorbed", 0),
                    overkill=event.get("overkill", 0)
                )
                damage_events_to_create.append(damage_event_in)

            elif event_type == "heal":
                if not source_player_id:
                    # logger.warning(f"Skipping heal event: Missing source player ID for WCL ID {source_wcl_id}. Event: {event}")
                    continue # Heal must have a source player
                if not target_player_id and not target_npc_wcl_id:
                    # logger.warning(f"Skipping heal event: Missing target player/NPC ID. Event: {event}")
                    continue # Heal must have a target (player or NPC)

                heal_event_in = schemas.HealEventCreate(
                    fight_id=db_fight.id,
                    timestamp_ms=timestamp_ms,
                    source_player_id=source_player_id,
                    target_player_id=target_player_id, # Can be None if target is NPC
                    target_npc_id=target_npc_wcl_id if not target_player_id else None, # Only set if target isn't a player
                    ability_game_id=ability_game_id,
                    hit_type=event.get("hitType", 1), # Often 1 for heal
                    amount=event.get("amount", 0),
                    overheal=event.get("overheal", 0),
                    absorbed=event.get("absorbed", 0)
                )
                heal_events_to_create.append(heal_event_in)

            elif event_type == "death":
                if not target_player_id and not target_npc_wcl_id:
                    # logger.warning(f"Skipping death event: Missing target player/NPC ID. Event: {event}")
                    continue # Death must have a target (player or NPC)

                killing_blow_wcl_id = event.get("killingBlowActor")
                killing_blow_player = player_lookup.get(killing_blow_wcl_id) if killing_blow_wcl_id else None
                killing_blow_player_id = killing_blow_player.id if killing_blow_player else None

                death_event_in = schemas.DeathEventCreate(
                    fight_id=db_fight.id,
                    timestamp_ms=timestamp_ms,
                    target_player_id=target_player_id,
                    target_npc_id=target_npc_wcl_id if not target_player_id else None,
                    ability_game_id=event.get("abilityGameID"), # KB Ability ID might be different from event ability ID
                    killing_blow_player_id=killing_blow_player_id
                )
                death_events_to_create.append(death_event_in)

            # Add other event types as needed

        # 5. Bulk create events (much faster than individual inserts) (ensure await)
        logger.info(f"Bulk creating {len(cast_events_to_create)} cast events...")
        if cast_events_to_create:
            await crud.create_player_cast_events_bulk(db, report_id=db_report.id, events=cast_events_to_create) # Pass report_id

        logger.info(f"Bulk creating {len(buff_events_to_create)} buff events...")
        if buff_events_to_create:
            await crud.create_buff_events_bulk(db, report_id=db_report.id, events=buff_events_to_create) # Pass report_id

        logger.info(f"Bulk creating {len(damage_events_to_create)} damage events...")
        if damage_events_to_create:
            await crud.create_damage_events_bulk(db, report_id=db_report.id, events=damage_events_to_create) # Call new CRUD

        logger.info(f"Bulk creating {len(heal_events_to_create)} heal events...")
        if heal_events_to_create:
            await crud.create_heal_events_bulk(db, report_id=db_report.id, events=heal_events_to_create) # Call new CRUD

        logger.info(f"Bulk creating {len(death_events_to_create)} death events...")
        if death_events_to_create:
            await crud.create_death_events_bulk(db, report_id=db_report.id, events=death_events_to_create) # Call new CRUD

        # 6. Commit the entire transaction for the report (ensure await)
        await db.commit() # ensure await

    except Exception as e:
        logger.exception(f"Error processing report {report_code} in background: {e}")
        await db.rollback() # Rollback on any error during processing
    finally:
        # The db session is managed by the dependency injection, so we don't close it here.
        # If using SessionLocal directly, ensure db.close() is called.
        pass


@app.post("/process-report/", status_code=202)
async def process_report_endpoint(request: schemas.ReportProcessRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Accepts a WCL report URL, triggers background processing, and returns immediately.
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
    background_tasks.add_task(_process_report_background, report_code, db)
    logger.info(f"Background task scheduled for report {report_code}")

    # Return immediately
    return ProcessReportResponse(message=f"Report processing for {report_code} started in the background.")


@app.get("/reports/", response_model=List[schemas.ReportReadBasic])
async def list_reports(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves a list of processed reports with basic information.
    Supports pagination using skip and limit query parameters.
    """
    reports = await crud.get_reports(db=db, skip=skip, limit=limit)
    return reports


@app.get("/reports/{report_code}/", response_model=schemas.ReportReadDetailed)
async def get_report_details(
    report_code: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves detailed information for a specific report, including lists
    of its associated fights and players.
    """
    db_report = await crud.get_detailed_report_by_code(db, report_code=report_code)
    if db_report is None:
        raise HTTPException(status_code=404, detail=f"Report with code {report_code} not found")
    return db_report


@app.get("/reports/{report_code}/fights/{wcl_fight_id}/events/", response_model=List[schemas.AnyEventRead])
async def get_fight_events(
    report_code: str,
    wcl_fight_id: int,
    event_types: Optional[str] = Query(None, description="Comma-separated list of event types (e.g., 'damage,heal')", alias="event_type"),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves events for a specific fight within a report.

    - **report_code**: The WCL report code (e.g., NpRcxdFjnL49QmhM).
    - **wcl_fight_id**: The WCL fight ID within the report.
    - **event_type** (query param): Optional. Comma-separated string of event types to filter by
      (e.g., `damage,heal`, `cast`, `death`). If omitted, all event types for the fight are returned.
    """
    # Find the internal fight ID first
    fight = await crud.get_fight_by_report_code_and_wcl_id(db, report_code=report_code, wcl_fight_id=wcl_fight_id)
    if fight is None:
        raise HTTPException(
            status_code=404,
            detail=f"Fight with WCL ID {wcl_fight_id} not found in report {report_code}"
        )

    # Parse event types if provided
    parsed_event_types = None
    if event_types:
        parsed_event_types = [et.strip().lower() for et in event_types.split(',') if et.strip()]
        if not parsed_event_types:
             parsed_event_types = None # Handle case of empty string or just commas

    # Fetch events using the internal fight ID
    events = await crud.get_events_for_fight(db, fight_id=fight.id, event_types=parsed_event_types)

    # Note: FastAPI handles the serialization based on the Union response_model
    return events


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
