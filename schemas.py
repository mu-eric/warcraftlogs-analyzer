from pydantic import BaseModel, HttpUrl, ConfigDict
from typing import List, Optional, Dict, Set
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

# --- Aggregation Schemas ---
class PlayerGroupStats(BaseModel):
    """Detailed stats for a player within a group aggregation."""
    player_name: str
    boss_names: List[str] # List of unique boss names encountered
    total_damage: float
    total_healing: float
    model_config = ConfigDict(from_attributes=True) # If needed later

class GroupDefinitionRequest(BaseModel):
    """Defines groups of players for aggregation.
    Key: Group name (e.g., 'group1')
    Value: List of player names (e.g., ['PlayerA', 'PlayerB'])
    """
    groups: Dict[str, List[str]]

class GroupStatsResponse(BaseModel):
    """Shows aggregated stats per group, broken down by player."""
    # Key: Group name
    # Value: List of player stats within that group
    group_stats: Dict[str, List[PlayerGroupStats]]

# --- API Input Schema ---
class ReportProcessRequest(BaseModel):
    report_url: HttpUrl

# Update forward references
Fight.model_rebuild()
Player.model_rebuild()
PlayerFightStats.model_rebuild()
Report.model_rebuild()
