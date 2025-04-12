from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import models
import schemas
import logging
from typing import Optional

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
