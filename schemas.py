from pydantic import BaseModel, HttpUrl, ConfigDict
from typing import List, Optional
from datetime import datetime

# Forward declaration for relationship typing
class Fight:
    pass
class PlayerFightStats:
    pass
class Player:
    pass
class Report:
    pass


# --- PlayerFightStats Schemas ---
class PlayerFightStatsBase(BaseModel):
    player_id: int
    fight_id: int
    damage_done: Optional[float] = None
    healing_done: Optional[float] = None

class PlayerFightStatsCreate(PlayerFightStatsBase):
    pass

class PlayerFightStats(PlayerFightStatsBase):
    id: int
    # Relationship fields could be added if needed for responses, e.g.:
    # player: Player 
    # fight: Fight

    class Config:
        orm_mode = True

# --- Fight Schemas ---
class FightBase(BaseModel):
    report_id: int
    wcl_fight_id: int
    name: Optional[str] = None
    boss_id: Optional[int] = None

class FightCreate(FightBase):
    pass

class Fight(FightBase):
    id: int
    stats: List[PlayerFightStats] = [] # Rename to stats

    class Config:
        orm_mode = True

# --- Player Schemas ---
class PlayerBase(BaseModel):
    name: str
    server: Optional[str] = None
    # Aggregate stats removed
    # damage_done: Optional[float] = 0.0
    # healing_done: Optional[float] = 0.0

class PlayerCreate(PlayerBase):
    # report_id will be handled by the CRUD function logic
    pass

class Player(PlayerBase):
    id: int
    report_id: int
    fight_stats: List[PlayerFightStats] = [] # Stats for this player across fights

    class Config:
        orm_mode = True # For SQLAlchemy compatibility (use from_orm)

# --- Report Schemas (Define Base first) ---
class ReportBase(BaseModel):
    report_code: str
    title: Optional[str] = None
    owner: Optional[str] = None
    start_time: datetime
    end_time: datetime
    zone_id: Optional[int] = None
    zone_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ReportCreate(ReportBase):
    pass

class Report(ReportBase):
    id: int
    fights: List[Fight] = [] # Changed from players to fights
    players: List[Player] = [] # Keeping the list of players involved in the report

    class Config:
        orm_mode = True # For SQLAlchemy compatibility (use from_orm)

# --- Detailed Schemas for GET Endpoint (Define after dependencies) ---

# Include basic player info directly in the stats detail
class PlayerFightStatsDetail(PlayerFightStatsBase):
    id: int
    player: PlayerBase # Nested player info (using PlayerBase to avoid circular refs if Player included lists)
    model_config = ConfigDict(from_attributes=True)

class FightDetail(FightBase):
    id: int
    stats: List[PlayerFightStatsDetail] # List of detailed stats including player info
    model_config = ConfigDict(from_attributes=True)

class ReportDetail(ReportBase): # Now inherits from the defined ReportBase
    id: int
    fights: List[FightDetail] # List of detailed fights
    model_config = ConfigDict(from_attributes=True)

# --- API Input Schema ---
class ReportProcessRequest(BaseModel):
    report_url: HttpUrl

# Update forward references
Fight.update_forward_refs()
Player.update_forward_refs()
PlayerFightStats.update_forward_refs()
Report.update_forward_refs()
