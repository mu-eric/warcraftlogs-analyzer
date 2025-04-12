from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import models
import schemas
import logging
from typing import Optional, Dict, List
from sqlalchemy.orm import selectinload
from sqlalchemy import func, select, and_, delete
from sqlalchemy import func, select, and_

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

async def get_or_create_player(db: AsyncSession, report_id: int, player_name: str, player_server: Optional[str]) -> models.Player:
    """Gets a player by name for a specific report, or creates one if not found."""
    # Check if player already exists for this report
    stmt = select(models.Player).filter_by(report_id=report_id, name=player_name)
    result = await db.execute(stmt)
    db_player = result.scalars().first()

    if db_player:
        logger.debug(f"CRUD: Found existing player '{player_name}' for report ID {report_id}.")
        # Optionally update server if it was None and now has a value?
        # if db_player.server is None and player_server is not None:
        #     db_player.server = player_server
        #     await db.commit()
        #     await db.refresh(db_player)
        return db_player
    else:
        logger.debug(f"CRUD: Creating new player '{player_name}' for report ID {report_id}.")
        # Use the PlayerCreate schema structure (without stats) if needed for validation,
        # but directly create the model here.
        player_data = schemas.PlayerCreate(name=player_name, server=player_server)
        db_player = models.Player(**player_data.model_dump(), report_id=report_id)
        db.add(db_player)
        await db.flush()
        await db.refresh(db_player)
        logger.debug(f"Player {db_player.name} added to session with ID {db_player.id}")
        return db_player

async def create_fight(db: AsyncSession, fight: schemas.FightCreate) -> models.Fight:
    """Creates a new Fight record in the database."""
    db_fight = models.Fight(**fight.model_dump())
    db.add(db_fight)
    await db.flush()
    await db.refresh(db_fight)
    logger.debug(f"CRUD: Created Fight ID {db_fight.id} (WCL ID: {db_fight.wcl_fight_id}) for Report ID {db_fight.report_id}.")
    return db_fight

async def create_player_fight_stats(db: AsyncSession, stats: schemas.PlayerFightStatsCreate) -> models.PlayerFightStats:
    """Creates a new PlayerFightStats record linking a player and a fight."""
    # Potential check: Ensure player_id and fight_id exist?
    # Or rely on DB foreign key constraints.
    db_stats = models.PlayerFightStats(**stats.model_dump())
    db.add(db_stats)
    await db.flush()
    await db.refresh(db_stats)
    logger.debug(f"CRUD: Created PlayerFightStats ID {db_stats.id} for Player ID {db_stats.player_id} in Fight ID {db_stats.fight_id}.")
    return db_stats

async def get_detailed_report_by_code(db: AsyncSession, report_code: str) -> Optional[models.Report]:
    """Fetches a report by code, eagerly loading fights, their stats, and associated players."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(models.Report)
        .where(models.Report.report_code == report_code)
        .options(
            selectinload(models.Report.fights)
            .selectinload(models.Fight.stats)
            .selectinload(models.PlayerFightStats.player)
        )
    )
    return result.scalars().first()

async def delete_report_by_code(db: AsyncSession, report_code: str):
    """Deletes a report and its associated data (Players, Fights, PlayerFightStats) by report code."""
    logger.info(f"Attempting to delete report and associated data for code: {report_code}")
    # First, find the report to ensure it exists and get its ID
    report = await get_report_by_code(db, report_code)
    if report:
        report_id = report.id
        # Delete associated Player records first due to direct ForeignKey
        # Use synchronize_session=False for potentially better performance with async
        delete_players_stmt = delete(models.Player).where(models.Player.report_id == report_id)
        await db.execute(delete_players_stmt)
        logger.debug(f"Deleted Player records associated with report_id {report_id}")

        # Now delete the report. Cascades should handle Fights and PlayerFightStats.
        await db.delete(report)
        await db.flush() # Ensure deletion is processed before potentially creating new
        logger.info(f"Successfully deleted report {report_code} (ID: {report_id}) and cascaded data.")
        return True
    else:
        logger.warning(f"Report code {report_code} not found for deletion.")
        return False

# --- Aggregation CRUD ---
async def aggregate_stats_by_group(
    db: AsyncSession,
    report_code: str,
    groups: Dict[str, List[str]],
    boss_names: Optional[List[str]] = None
) -> Dict[str, List[schemas.PlayerGroupStats]]:
    """Calculates detailed damage and healing stats for players within predefined groups
       in a report, optionally filtered by a list of specific boss names.
    """
    report = await get_report_by_code(db, report_code)
    if not report:
        logger.warning(f"Aggregation requested for non-existent report: {report_code}")
        return {}

    # Consolidate all unique player names across all groups for a single query
    all_player_names = set(p for names in groups.values() for p in names)
    if not all_player_names:
        return {group_name: [] for group_name in groups} # Return empty lists for all groups

    # Build the base query to fetch individual fight stats for relevant players
    query = (
        select(
            models.Player.name,
            models.Fight.name.label("boss_name"), # Use label for clarity
            models.PlayerFightStats.damage_done,
            models.PlayerFightStats.healing_done
        )
        .join(models.PlayerFightStats, models.Player.id == models.PlayerFightStats.player_id)
        .join(models.Fight, models.PlayerFightStats.fight_id == models.Fight.id)
        .where(
            and_( # Use 'and_' for multiple conditions
                models.Fight.report_id == report.id,
                models.Player.name.in_(all_player_names)
            )
        )
    )

    # --- Modified Filter Logic ---
    if boss_names: # Check if the list is provided and non-empty
        # Filter by Fight.name being in the provided list
        query = query.where(models.Fight.name.in_(boss_names))
        logger.debug(f"Filtering aggregation by boss names: {boss_names}")
    # --- End Modified Filter Logic ---

    # Execute the query to get raw per-fight stats for all relevant players
    result = await db.execute(query)
    player_fight_data = result.all() # Fetch all rows (player_name, boss_name, damage, healing)

    # Process the raw data in Python to aggregate per player
    player_aggregated_stats: Dict[str, Dict] = {} # { player_name: {'damage': float, 'healing': float, 'bosses': set} }

    for player_name, boss_name, damage, healing in player_fight_data:
        if player_name not in player_aggregated_stats:
            player_aggregated_stats[player_name] = {
                "total_damage": 0.0,
                "total_healing": 0.0,
                "boss_names": set() # Use a set to store unique boss names
            }
        player_aggregated_stats[player_name]["total_damage"] += damage or 0.0
        player_aggregated_stats[player_name]["total_healing"] += healing or 0.0
        if boss_name: # Avoid adding None if fight name is null
             player_aggregated_stats[player_name]["boss_names"].add(boss_name)

    # Structure the results according to the input groups
    final_group_stats: Dict[str, List[schemas.PlayerGroupStats]] = {group_name: [] for group_name in groups}

    for group_name, group_player_names in groups.items():
        for player_name in group_player_names:
            if player_name in player_aggregated_stats:
                stats = player_aggregated_stats[player_name]
                final_group_stats[group_name].append(
                    schemas.PlayerGroupStats(
                        player_name=player_name,
                        # Convert set to sorted list for consistent output
                        boss_names=sorted(list(stats["boss_names"])),
                        total_damage=stats["total_damage"],
                        total_healing=stats["total_healing"]
                    )
                )
            # else: Player was in the group definition but had no stats in the filtered fights (or report)

    logger.debug(f"Aggregated stats for report {report_code} (Bosses: {boss_names or 'All'}): {final_group_stats}")
    return final_group_stats
