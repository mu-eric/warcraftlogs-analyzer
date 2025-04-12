from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, UniqueConstraint, Boolean, Float
from sqlalchemy.orm import relationship
from database import Base


# === Event Models (Define First) ===

class PlayerCastEvent(Base):
    __tablename__ = "player_cast_events"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    fight_id = Column(Integer, ForeignKey("fights.id"), nullable=False, index=True) # Events belong to fights
    timestamp_ms = Column(Integer, nullable=False, index=True) # Milliseconds relative to report start
    ability_game_id = Column(Integer, nullable=False, index=True)

    source_player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    # Target might be null (e.g., self-cast, AoE with no primary target in event)
    target_player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)

    # Relationships
    report = relationship("Report", back_populates="cast_events")
    fight = relationship("Fight", back_populates="cast_events")
    source_player = relationship("Player", foreign_keys=[source_player_id], back_populates="casts_source")
    target_player = relationship("Player", foreign_keys=[target_player_id], back_populates="casts_target")


class BuffEvent(Base):
    __tablename__ = "buff_events"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    fight_id = Column(Integer, ForeignKey("fights.id"), nullable=False, index=True) # Events belong to fights
    timestamp_ms = Column(Integer, nullable=False, index=True) # Milliseconds relative to report start
    # Type examples: 'applybuff', 'removebuff', 'applydebuff', 'removedebuff'
    event_type = Column(String, nullable=False, index=True) 
    ability_game_id = Column(Integer, nullable=False, index=True) # The ID of the buff/debuff

    # Source might be null (e.g., aura application/removal)
    source_player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)
    target_player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True) # Who the buff/debuff is on

    # Relationships
    report = relationship("Report", back_populates="buff_events")
    fight = relationship("Fight", back_populates="buff_events")
    source_player = relationship("Player", foreign_keys=[source_player_id], back_populates="buff_events_source")
    target_player = relationship("Player", foreign_keys=[target_player_id], back_populates="buff_events_target")


class DamageEvent(Base):
    __tablename__ = "damage_events"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    fight_id = Column(Integer, ForeignKey("fights.id"), nullable=False, index=True)
    timestamp_ms = Column(BigInteger, nullable=False, index=True)
    event_type = Column(String, nullable=False, default="damage")
    source_player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True) # Assuming source is always a player
    target_player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True) # Target might be null if NPC
    target_npc_id = Column(Integer, nullable=True, index=True) # WCL ID for NPC target
    ability_game_id = Column(Integer, nullable=False, index=True)
    hit_type = Column(Integer, nullable=False) # WCL HitType enum
    amount = Column(Integer, nullable=False)
    mitigated = Column(Integer, nullable=True, default=0)
    absorbed = Column(Integer, nullable=True, default=0)
    overkill = Column(Integer, nullable=True, default=0)

    report = relationship("Report", back_populates="damage_events")
    fight = relationship("Fight", back_populates="damage_events")
    source_player = relationship("Player", foreign_keys=[source_player_id], back_populates="damage_events_source")
    target_player = relationship("Player", foreign_keys=[target_player_id], back_populates="damage_events_target")


class HealEvent(Base):
    __tablename__ = "heal_events"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    fight_id = Column(Integer, ForeignKey("fights.id"), nullable=False, index=True)
    timestamp_ms = Column(BigInteger, nullable=False, index=True)
    event_type = Column(String, nullable=False, default="heal")
    source_player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    target_player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)
    target_npc_id = Column(Integer, nullable=True, index=True)
    ability_game_id = Column(Integer, nullable=False, index=True)
    hit_type = Column(Integer, nullable=False) # WCL HitType enum (often 1 for heals)
    amount = Column(Integer, nullable=False)
    overheal = Column(Integer, nullable=True, default=0)
    absorbed = Column(Integer, nullable=True, default=0) # Sometimes heals are absorbed

    report = relationship("Report", back_populates="heal_events")
    fight = relationship("Fight", back_populates="heal_events")
    source_player = relationship("Player", foreign_keys=[source_player_id], back_populates="heal_events_source")
    target_player = relationship("Player", foreign_keys=[target_player_id], back_populates="heal_events_target")


class DeathEvent(Base):
    __tablename__ = "death_events"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    fight_id = Column(Integer, ForeignKey("fights.id"), nullable=False, index=True)
    timestamp_ms = Column(BigInteger, nullable=False, index=True)
    event_type = Column(String, nullable=False, default="death")
    target_player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)
    target_npc_id = Column(Integer, nullable=True, index=True)
    ability_game_id = Column(Integer, nullable=True, index=True) # Killing blow ability ID
    killing_blow_player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True) # Player delivering KB

    report = relationship("Report", back_populates="death_events")
    fight = relationship("Fight", back_populates="death_events")
    target_player = relationship("Player", foreign_keys=[target_player_id], back_populates="death_events")
    killing_blow_player = relationship("Player", foreign_keys=[killing_blow_player_id], back_populates="killing_blows")


# === Core Models ===

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    report_code = Column(String, unique=True, index=True, nullable=False)
    title = Column(String)
    start_time_ms = Column(BigInteger, nullable=False) # Changed from DateTime, using BigInteger for milliseconds
    end_time_ms = Column(BigInteger, nullable=False)   # Changed from DateTime
    zone_id = Column(Integer)
    zone_name = Column(String) # Added zone name for convenience

    # Relationship: One Report has many Fights
    fights = relationship("Fight", back_populates="report", cascade="all, delete-orphan")
    # Relationship: One Report involves many Players
    players = relationship("Player", back_populates="report", cascade="all, delete-orphan")
    # Relationships to events (optional, but can be useful for report-wide event queries)
    cast_events = relationship("PlayerCastEvent", back_populates="report", cascade="all, delete-orphan")
    buff_events = relationship("BuffEvent", back_populates="report", cascade="all, delete-orphan")
    damage_events = relationship("DamageEvent", back_populates="report", cascade="all, delete-orphan") # Added
    heal_events = relationship("HealEvent", back_populates="report", cascade="all, delete-orphan")     # Added
    death_events = relationship("DeathEvent", back_populates="report", cascade="all, delete-orphan")    # Added


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    wcl_actor_id = Column(Integer, index=True, nullable=False) # WCL's ID for this actor in this specific report
    name = Column(String, index=True, nullable=False)
    server = Column(String, nullable=True) # Server might still be null based on WCL data
    # Optional: Store class/spec if available from CombatantInfo
    # player_class = Column(String, nullable=True)
    # player_spec = Column(String, nullable=True)

    # Relationship: Player participated in a Report
    report = relationship("Report", back_populates="players")
    
    # Relationships to events where this player is the source
    casts_source = relationship("PlayerCastEvent", foreign_keys=[PlayerCastEvent.source_player_id], back_populates="source_player", cascade="all, delete-orphan")
    buff_events_source = relationship("BuffEvent", foreign_keys=[BuffEvent.source_player_id], back_populates="source_player", cascade="all, delete-orphan")
    damage_events_source = relationship("DamageEvent", foreign_keys=[DamageEvent.source_player_id], back_populates="source_player", cascade="all, delete-orphan") # Added
    heal_events_source = relationship("HealEvent", foreign_keys=[HealEvent.source_player_id], back_populates="source_player", cascade="all, delete-orphan")     # Added

    # Relationships to events where this player is the target
    casts_target = relationship("PlayerCastEvent", foreign_keys=[PlayerCastEvent.target_player_id], back_populates="target_player", cascade="all, delete-orphan")
    buff_events_target = relationship("BuffEvent", foreign_keys=[BuffEvent.target_player_id], back_populates="target_player", cascade="all, delete-orphan")
    damage_events_target = relationship("DamageEvent", foreign_keys=[DamageEvent.target_player_id], back_populates="target_player", cascade="all, delete-orphan") # Added
    heal_events_target = relationship("HealEvent", foreign_keys=[HealEvent.target_player_id], back_populates="target_player", cascade="all, delete-orphan")     # Added
    death_events = relationship("DeathEvent", foreign_keys=[DeathEvent.target_player_id], back_populates="target_player", cascade="all, delete-orphan")        # Added
    killing_blows = relationship("DeathEvent", foreign_keys=[DeathEvent.killing_blow_player_id], back_populates="killing_blow_player", cascade="all, delete-orphan") # Added

    # Ensure a player actor ID is unique within a single report
    __table_args__ = (UniqueConstraint('report_id', 'wcl_actor_id', name='uq_player_report_actor'),)


class Fight(Base):
    __tablename__ = "fights"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    wcl_fight_id = Column(Integer, index=True, nullable=False) # The ID from WCL API
    start_time_ms = Column(BigInteger, nullable=True)  # Added absolute start time
    end_time_ms = Column(BigInteger, nullable=True)    # Added absolute end time
    start_offset_ms = Column(BigInteger, nullable=False) # Renamed from start_time_offset, using BigInteger
    end_offset_ms = Column(BigInteger, nullable=False)   # Renamed from end_time_offset, using BigInteger
    name = Column(String, nullable=True)
    kill = Column(Boolean, nullable=True)                 # Added
    difficulty = Column(Integer, nullable=True)           # Added
    boss_percentage = Column(Float, nullable=True)        # Added
    average_item_level = Column(Float, nullable=True)     # Added

    # Relationship: Many Fights belong to one Report
    report = relationship("Report", back_populates="fights")
    
    # Relationship to events occurring during this fight
    cast_events = relationship("PlayerCastEvent", back_populates="fight", cascade="all, delete-orphan")
    buff_events = relationship("BuffEvent", back_populates="fight", cascade="all, delete-orphan")
    damage_events = relationship("DamageEvent", back_populates="fight", cascade="all, delete-orphan") # Added
    heal_events = relationship("HealEvent", back_populates="fight", cascade="all, delete-orphan")     # Added
    death_events = relationship("DeathEvent", back_populates="fight", cascade="all, delete-orphan")    # Added
