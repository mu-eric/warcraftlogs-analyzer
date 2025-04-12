from pydantic import BaseModel, HttpUrl, ConfigDict, Field
from typing import List, Optional, Dict, Set, Union
from datetime import datetime

# Forward declaration for relationship typing
class Fight:
    pass
class PlayerCastEvent:
    pass
class BuffEvent:
    pass
class Player:
    pass
class Report:
    pass
class DamageEvent:
    pass
class HealEvent:
    pass
class DeathEvent:
    pass


# --- PlayerBase (used in event relationships) ---
class PlayerBase(BaseModel):
    id: int
    name: str
    server: Optional[str] = None
    wcl_actor_id: int
    model_config = ConfigDict(from_attributes=True)


# --- PlayerCastEvent Schemas ---
class PlayerCastEventBase(BaseModel):
    fight_id: int
    timestamp_ms: int
    ability_game_id: int
    source_player_id: int
    target_player_id: Optional[int] = None

class PlayerCastEventCreate(PlayerCastEventBase):
    pass

class PlayerCastEvent(PlayerCastEventBase):
    id: int
    report_id: int
    source_player: PlayerBase
    target_player: Optional[PlayerBase] = None
    model_config = ConfigDict(from_attributes=True)


# --- BuffEvent Schemas ---
class BuffEventBase(BaseModel):
    fight_id: int
    timestamp_ms: int
    event_type: str
    ability_game_id: int
    source_player_id: Optional[int] = None
    target_player_id: int
    buff_stack: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class BuffEventCreate(BuffEventBase):
    pass

class BuffEvent(BuffEventBase):
    id: int
    report_id: int # Keep report_id here for reading/returning data
    source_player: Optional[PlayerBase] = None
    target_player: PlayerBase
    model_config = ConfigDict(from_attributes=True)


# --- DamageEvent Schemas ---
class DamageEventBase(BaseModel):
    fight_id: int
    timestamp_ms: int
    event_type: str = "damage" # Set default type
    source_player_id: int
    target_player_id: Optional[int] = None # Target might not be a player
    target_npc_id: Optional[int] = None # Track NPC target
    ability_game_id: int
    hit_type: int # Refer to WCL documentation for HitType enum
    amount: int
    mitigated: Optional[int] = 0
    absorbed: Optional[int] = 0
    overkill: Optional[int] = 0
    model_config = ConfigDict(from_attributes=True)

class DamageEventCreate(DamageEventBase):
    pass

class DamageEvent(DamageEventBase):
    id: int
    report_id: int # Keep report_id here for reading/returning data
    source_player: PlayerBase
    # target_player: Optional[PlayerBase] = None # Can add if needed
    model_config = ConfigDict(from_attributes=True)


# --- HealEvent Schemas ---
class HealEventBase(BaseModel):
    fight_id: int
    timestamp_ms: int
    event_type: str = "heal" # Set default type
    source_player_id: int
    target_player_id: Optional[int] = None # Target might not be a player
    target_npc_id: Optional[int] = None # Track NPC target
    ability_game_id: int
    hit_type: int # Refer to WCL documentation for HitType enum
    amount: int
    overheal: Optional[int] = 0
    absorbed: Optional[int] = 0
    model_config = ConfigDict(from_attributes=True)

class HealEventCreate(HealEventBase):
    pass

class HealEvent(HealEventBase):
    id: int
    report_id: int # Keep report_id here for reading/returning data
    source_player: PlayerBase
    # target_player: Optional[PlayerBase] = None # Can add if needed
    model_config = ConfigDict(from_attributes=True)


# --- DeathEvent Schemas ---
class DeathEventBase(BaseModel):
    fight_id: int
    timestamp_ms: int
    event_type: str = "death" # Set default type
    target_player_id: Optional[int] = None # Target might not be a player
    target_npc_id: Optional[int] = None # Track NPC target
    ability_game_id: Optional[int] = None # Killing blow ability
    killing_blow_player_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class DeathEventCreate(DeathEventBase):
    pass

class DeathEvent(DeathEventBase):
    id: int
    report_id: int # Keep report_id here for reading/returning data
    # target_player: Optional[PlayerBase] = None # Can add if needed
    # killing_blow_player: Optional[PlayerBase] = None # Can add if needed
    model_config = ConfigDict(from_attributes=True)


# --- Fight Schemas ---
class FightBase(BaseModel):
    wcl_fight_id: int
    start_time_ms: Optional[int] = None
    end_time_ms: Optional[int] = None
    start_offset_ms: int
    end_offset_ms: int
    name: Optional[str] = None
    kill: Optional[bool] = None
    difficulty: Optional[int] = None
    boss_percentage: Optional[float] = None
    average_item_level: Optional[float] = None
    model_config = ConfigDict(from_attributes=True)

class FightCreate(FightBase):
    pass

class Fight(FightBase):
    id: int
    report_id: int
    cast_events: List[PlayerCastEvent] = []
    buff_events: List[BuffEvent] = []
    damage_events: List[DamageEvent] = []
    heal_events: List[HealEvent] = []
    death_events: List[DeathEvent] = []
    model_config = ConfigDict(from_attributes=True)


# --- Player Schemas ---
class PlayerCreate(BaseModel):
    name: str
    server: Optional[str] = None
    wcl_actor_id: int

class Player(PlayerBase):
    report_id: int
    casts_source: List[PlayerCastEvent] = []
    buff_events_source: List[BuffEvent] = []
    casts_target: List[PlayerCastEvent] = []
    buff_events_target: List[BuffEvent] = []
    damage_events_source: List[DamageEvent] = []
    damage_events_target: List[DamageEvent] = []
    heal_events_source: List[HealEvent] = []
    heal_events_target: List[HealEvent] = []
    death_events: List[DeathEvent] = []


# --- Report Schemas --- 
class ReportBase(BaseModel):
    report_code: str = Field(..., index=True)
    title: Optional[str] = None
    owner: Optional[str] = None
    start_time_ms: Optional[int] = None
    end_time_ms: Optional[int] = None
    zone_id: Optional[int] = None

class ReportCreate(ReportBase):
    pass # Inherits all fields from Base

class ReportReadBasic(ReportBase): # New schema for list view
    id: int

    class Config:
        orm_mode = True # For SQLAlchemy model compatibility

class ReportReadDetailed(ReportReadBasic): # New schema for detailed view
    fights: List[FightBase] = []
    players: List[PlayerBase] = []

    class Config:
        orm_mode = True

class Report(ReportBase):
    id: int
    fights: List[Fight] = [] 
    players: List[Player] = []
    cast_events: List[PlayerCastEvent] = []
    buff_events: List[BuffEvent] = []
    damage_events: List[DamageEvent] = []
    heal_events: List[HealEvent] = []
    death_events: List[DeathEvent] = []


# --- Detailed Schemas for GET Endpoint (Adjusted) ---

class FightDetail(FightBase):
    id: int
    report_id: int
    model_config = ConfigDict(from_attributes=True)

class PlayerDetail(PlayerBase):
    id: int
    report_id: int
    model_config = ConfigDict(from_attributes=True)

class ReportDetail(ReportBase):
    id: int
    fights: List[FightDetail] 
    players: List[PlayerBase] 
    model_config = ConfigDict(from_attributes=True)


# --- Aggregation Schemas (Review needed based on event analysis) ---
class PlayerGroupStats(BaseModel):
    player_name: str
    boss_names: List[str] 
    total_damage: float 
    total_healing: float
    model_config = ConfigDict(from_attributes=True)

class GroupDefinitionRequest(BaseModel):
    groups: Dict[str, List[str]]

class GroupStatsResponse(BaseModel):
    group_stats: Dict[str, List[PlayerGroupStats]]


# --- API Input Schema --- 
class ReportProcessRequest(BaseModel):
    report_url: HttpUrl

# --- Union Type for Any Event --- #

class PlayerCastEventRead(PlayerCastEventBase):
    id: int

    class Config:
        orm_mode = True

class BuffEventRead(BuffEventBase):
    id: int

    class Config:
        orm_mode = True

class DamageEventRead(DamageEventBase):
    id: int

    class Config:
        orm_mode = True

class HealEventRead(HealEventBase):
    id: int

    class Config:
        orm_mode = True

class DeathEventRead(DeathEventBase):
    id: int

    class Config:
        orm_mode = True

AnyEventRead = Union[
    PlayerCastEventRead,
    BuffEventRead,
    DamageEventRead,
    HealEventRead,
    DeathEventRead
]


# Update forward references
Report.model_rebuild()
Fight.model_rebuild()
Player.model_rebuild()
ReportDetail.model_rebuild() 
FightDetail.model_rebuild()
PlayerDetail.model_rebuild()
DamageEvent.model_rebuild()
HealEvent.model_rebuild()
DeathEvent.model_rebuild()
