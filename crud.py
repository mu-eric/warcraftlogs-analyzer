from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.dialects.sqlite import insert # Use specific dialect for ON CONFLICT
from sqlalchemy import delete # Import delete statement
from sqlalchemy.orm import selectinload # Import for eager loading

import models
import schemas
import logging
from typing import Optional, Dict, List
from sqlalchemy import func, select, and_, insert

logger = logging.getLogger(__name__)

async def get_report_by_code(db: AsyncSession, report_code: str):
    """Fetch a report by its unique code."""
    result = await db.execute(select(models.Report).filter(models.Report.report_code == report_code))
    return result.scalars().first()

async def create_report(db: AsyncSession, report: schemas.ReportCreate):
    """Create a new report in the database."""
    db_report = models.Report(**report.model_dump())
    db.add(db_report)
    await db.flush()
    await db.refresh(db_report)
    logger.debug(f"Report {db_report.report_code} added to session with ID {db_report.id}")
    return db_report

async def get_or_create_player(db: AsyncSession, report_id: int, player_create_data: schemas.PlayerCreate) -> models.Player:
    """Gets a player by WCL actor ID for a specific report, or creates one if not found."""
    # Check if player already exists for this report using WCL actor ID
    stmt = select(models.Player).filter_by(report_id=report_id, wcl_actor_id=player_create_data.wcl_actor_id)
    result = await db.execute(stmt)
    db_player = result.scalars().first()

    if db_player:
        logger.debug(f"CRUD: Found existing player '{db_player.name}' (WCL ID: {player_create_data.wcl_actor_id}) for report ID {report_id}.")
        # Optionally update server/name if it has changed?
        # For now, just return the existing player.
        return db_player
    else:
        logger.debug(f"CRUD: Creating new player '{player_create_data.name}' (WCL ID: {player_create_data.wcl_actor_id}) for report ID {report_id}.")
        db_player = models.Player(**player_create_data.model_dump(), report_id=report_id)
        db.add(db_player)
        await db.flush()
        await db.refresh(db_player)
        logger.debug(f"Player {db_player.name} added to session with ID {db_player.id}")
        return db_player

async def create_fight(db: AsyncSession, fight: schemas.FightCreate, report_id: int) -> models.Fight:
    """Creates a new Fight record in the database.
    Requires the associated report_id to be passed explicitly.
    """
    fight_data = fight.model_dump()
    fight_data['report_id'] = report_id # Add report_id to the data for model creation
    db_fight = models.Fight(**fight_data)
    db.add(db_fight)
    await db.flush() # Use flush to get the ID before commit
    await db.refresh(db_fight)
    logger.debug(f"CRUD: Created Fight ID {db_fight.id} (WCL ID: {db_fight.wcl_fight_id}) for Report ID {db_fight.report_id}.")
    return db_fight

async def create_player_cast_event(db: AsyncSession, event: schemas.PlayerCastEventCreate) -> models.PlayerCastEvent:
    """Creates a new PlayerCastEvent record."""
    # Potential checks: Ensure source/target player_id and fight_id exist?
    # Or rely on DB foreign key constraints.
    db_event = models.PlayerCastEvent(**event.model_dump())
    db.add(db_event)
    # No flush/refresh needed here if we don't need the ID immediately after creation
    # await db.flush()
    # await db.refresh(db_event)
    # logger.debug(f"CRUD: Added PlayerCastEvent for ability {db_event.ability_game_id} at {db_event.timestamp_ms}")
    return db_event

async def create_buff_event(db: AsyncSession, event: schemas.BuffEventCreate) -> models.BuffEvent:
    """Creates a new BuffEvent record."""
    db_event = models.BuffEvent(**event.model_dump())
    db.add(db_event)
    # No flush/refresh needed here
    # logger.debug(f"CRUD: Added BuffEvent {db_event.event_type} for ability {db_event.ability_game_id} at {db_event.timestamp_ms}")
    return db_event

# --- Bulk Create Functions --- 

async def create_player_cast_events_bulk(db: AsyncSession, report_id: int, events: List[schemas.PlayerCastEventCreate]):
    """Bulk creates PlayerCastEvent records, associating them with the given report_id."""
    if not events:
        logger.debug("CRUD: No player cast events provided for bulk creation.")
        return

    event_dicts = []
    for event_schema in events:
        event_data = event_schema.model_dump()
        event_data['report_id'] = report_id # Add report_id
        event_dicts.append(event_data)

    try:
        await db.execute(insert(models.PlayerCastEvent), event_dicts)
        logger.info(f"CRUD: Attempted to bulk insert {len(event_dicts)} player cast events for Report ID {report_id}.")
    except Exception as e:
        logger.error(f"CRUD: Error during bulk insert of player cast events for Report ID {report_id}: {e}", exc_info=True)
        await db.rollback()
        raise

async def create_buff_events_bulk(db: AsyncSession, report_id: int, events: list[schemas.BuffEventCreate]):
    """Bulk creates BuffEvent records, associating them with the given report_id."""
    if not events:
        logger.debug("CRUD: No buff events provided for bulk creation.")
        return

    event_dicts = []
    for event_schema in events:
        event_data = event_schema.model_dump()
        event_data['report_id'] = report_id # Add report_id
        event_dicts.append(event_data)

    try:
        await db.execute(insert(models.BuffEvent), event_dicts)
        # No need to flush/refresh in bulk insert unless specifically required
        logger.info(f"CRUD: Attempted to bulk insert {len(event_dicts)} buff events for Report ID {report_id}.")
    except Exception as e:
        logger.error(f"CRUD: Error during bulk insert of buff events for Report ID {report_id}: {e}", exc_info=True)
        await db.rollback() # Rollback on bulk insert error
        raise # Re-raise the exception so the background task knows it failed

# === Damage Event CRUD ===

async def create_damage_events_bulk(db: AsyncSession, report_id: int, events: List[schemas.DamageEventCreate]):
    """Bulk creates DamageEvent records."""
    if not events:
        logger.debug("CRUD: No damage events provided for bulk creation.")
        return

    event_dicts = []
    for event_schema in events:
        event_data = event_schema.model_dump()
        event_data['report_id'] = report_id
        event_dicts.append(event_data)

    try:
        await db.execute(insert(models.DamageEvent), event_dicts)
        logger.info(f"CRUD: Attempted to bulk insert {len(event_dicts)} damage events for Report ID {report_id}.")
    except Exception as e:
        logger.error(f"CRUD: Error during bulk insert of damage events for Report ID {report_id}: {e}", exc_info=True)
        await db.rollback()
        raise

# === Heal Event CRUD ===

async def create_heal_events_bulk(db: AsyncSession, report_id: int, events: List[schemas.HealEventCreate]):
    """Bulk creates HealEvent records."""
    if not events:
        logger.debug("CRUD: No heal events provided for bulk creation.")
        return

    event_dicts = []
    for event_schema in events:
        event_data = event_schema.model_dump()
        event_data['report_id'] = report_id
        event_dicts.append(event_data)

    try:
        await db.execute(insert(models.HealEvent), event_dicts)
        logger.info(f"CRUD: Attempted to bulk insert {len(event_dicts)} heal events for Report ID {report_id}.")
    except Exception as e:
        logger.error(f"CRUD: Error during bulk insert of heal events for Report ID {report_id}: {e}", exc_info=True)
        await db.rollback()
        raise

# === Death Event CRUD ===

async def create_death_events_bulk(db: AsyncSession, report_id: int, events: List[schemas.DeathEventCreate]):
    """Bulk creates DeathEvent records."""
    if not events:
        logger.debug("CRUD: No death events provided for bulk creation.")
        return

    event_dicts = []
    for event_schema in events:
        event_data = event_schema.model_dump()
        event_data['report_id'] = report_id
        event_dicts.append(event_data)

    try:
        await db.execute(insert(models.DeathEvent), event_dicts)
        logger.info(f"CRUD: Attempted to bulk insert {len(event_dicts)} death events for Report ID {report_id}.")
    except Exception as e:
        logger.error(f"CRUD: Error during bulk insert of death events for Report ID {report_id}: {e}", exc_info=True)
        await db.rollback()
        raise

# === Aggregation / Complex Queries ===

async def get_detailed_report_by_code(db: AsyncSession, report_code: str) -> Optional[models.Report]:
    """Fetches a report by code, eagerly loading fights and players."""
    logger.info(f"CRUD: Fetching detailed report for code: {report_code}")
    stmt = (
        select(models.Report)
        .where(models.Report.report_code == report_code)
        .options(
            selectinload(models.Report.fights),
            selectinload(models.Report.players)
        )
    )
    result = await db.execute(stmt)
    report = result.scalars().first()
    if report:
        logger.info(f"CRUD: Found report {report_code}. Fights: {len(report.fights)}, Players: {len(report.players)}")
    else:
        logger.warning(f"CRUD: Report not found with code: {report_code}")
    return report

async def get_fight_by_report_code_and_wcl_id(db: AsyncSession, report_code: str, wcl_fight_id: int) -> Optional[models.Fight]:
    """Retrieves a specific fight using report_code and wcl_fight_id."""
    logger.info(f"CRUD: Fetching fight for report_code: {report_code}, wcl_fight_id: {wcl_fight_id}")
    stmt = (
        select(models.Fight)
        .join(models.Report, models.Fight.report_id == models.Report.id)
        .where(
            models.Report.report_code == report_code,
            models.Fight.wcl_fight_id == wcl_fight_id
        )
    )
    result = await db.execute(stmt)
    fight = result.scalars().first()
    if not fight:
         logger.warning(f"CRUD: Fight not found for report {report_code}, wcl_fight_id {wcl_fight_id}")
    return fight


async def get_events_for_fight(db: AsyncSession, fight_id: int, event_types: Optional[List[str]] = None) -> List[models.Base]:
    """
    Retrieves events of specified types for a given fight_id.
    If event_types is None or empty, fetch all types.
    Results are sorted by timestamp.
    """
    logger.info(f"CRUD: Fetching events for fight_id: {fight_id}, types: {event_types}")
    all_events = []

    event_model_map = {
        "cast": models.PlayerCastEvent,
        "buff": models.BuffEvent,
        "damage": models.DamageEvent,
        "heal": models.HealEvent,
        "death": models.DeathEvent,
    }

    # Determine which types to fetch
    types_to_fetch = event_types if event_types else list(event_model_map.keys())

    for event_type_str in types_to_fetch:
        normalized_type = event_type_str.strip().lower()
        model = event_model_map.get(normalized_type)
        if model:
            # Ensure the model has a timestamp attribute for sorting later
            if not hasattr(model, 'timestamp_ms'):
                logger.error(f"CRUD: Model {model.__name__} lacks timestamp_ms attribute, cannot sort.")
                continue # Skip models without timestamp

            stmt = select(model).where(model.fight_id == fight_id)
            result = await db.execute(stmt)
            events = result.scalars().all()
            all_events.extend(events)
            logger.debug(f"CRUD: Fetched {len(events)} '{normalized_type}' events for fight_id {fight_id}")
        else:
            logger.warning(f"CRUD: Unknown or invalid event type requested: {event_type_str}")

    # Sort all collected events by timestamp
    try:
        all_events.sort(key=lambda event: getattr(event, 'timestamp_ms', float('inf')))
    except AttributeError as e:
        logger.error(f"CRUD: Error sorting events by timestamp: {e}")

    logger.info(f"CRUD: Total events fetched for fight_id {fight_id}: {len(all_events)}")
    return all_events


async def delete_report(db: AsyncSession, report_code: str):
    """Deletes a report and its cascaded data by report_code."""
    stmt = select(models.Report).where(models.Report.report_code == report_code)
    result = await db.execute(stmt)
    report_to_delete = result.scalars().first()

    if report_to_delete:
        logger.info(f"CRUD: Deleting report with code {report_code} (ID: {report_to_delete.id})")
        await db.delete(report_to_delete)
        # Commit happens in the calling function (_process_report_background) after deletion
        logger.info(f"CRUD: Report {report_code} marked for deletion.")
    else:
        logger.warning(f"CRUD: Attempted to delete non-existent report with code {report_code}")

async def delete_report_by_code(db: AsyncSession, report_code: str):
    """Deletes a report and its associated data (Players, Fights, Events via cascade) by report code."""
    logger.info(f"Attempting to delete report with code: {report_code}")
    # First, find the report ID
    report_result = await db.execute(select(models.Report.id).filter(models.Report.report_code == report_code))
    report_id = report_result.scalars().first()

    if not report_id:
        logger.warning(f"Report with code {report_code} not found for deletion.")
        return False

    try:
        # Cascades should handle deleting events linked to players/fights
        # Explicitly delete Players associated with the report
        # Note: If Players could belong to multiple reports, this logic would need changing.
        # Based on current model (Player.report_id), they belong to one report.
        logger.debug(f"Deleting players associated with report ID {report_id}")
        await db.execute(delete(models.Player).where(models.Player.report_id == report_id))
        
        # Explicitly delete Fights associated with the report
        logger.debug(f"Deleting fights associated with report ID {report_id}")
        await db.execute(delete(models.Fight).where(models.Fight.report_id == report_id))

        # Delete the PlayerFightStats associated with the fights being deleted (REMOVED)
        # logger.debug(f"Deleting player fight stats associated with report ID {report_id}")
        # await db.execute(
        #     delete(models.PlayerFightStats)
        #     .where(models.PlayerFightStats.fight_id.in_(
        #         select(models.Fight.id).where(models.Fight.report_id == report_id)
        #     ))
        # )

        # Finally, delete the Report itself
        logger.debug(f"Deleting report record with ID {report_id}")
        await db.execute(delete(models.Report).where(models.Report.id == report_id))

        await db.commit()
        logger.info(f"Successfully deleted report {report_code} and associated data.")
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting report {report_code}: {e}", exc_info=True)
        return False

async def aggregate_stats_by_group(
    db: AsyncSession,
    report_code: str,
    groups: Dict[str, List[str]],
    boss_names: Optional[List[str]] = None
) -> Dict[str, List[schemas.PlayerGroupStats]]:
    """Calculates detailed damage and healing stats for players within predefined groups.
       (NOTE: STUBBED OUT - Requires reimplementation based on event data)
    """
    logger.warning("aggregate_stats_by_group is not implemented for event-based data yet.")
    # raise NotImplementedError("Aggregation from event data is not yet implemented.")
    # Return empty structure for now to avoid breaking API contract if called
    return {group_name: [] for group_name in groups}

async def get_reports(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[models.Report]:
    """Retrieves a list of reports, with pagination."""
    result = await db.execute(select(models.Report).offset(skip).limit(limit))
    return result.scalars().all()

# === Fight CRUD ===
