from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    report_code = Column(String, unique=True, index=True, nullable=False)
    title = Column(String)
    owner = Column(String)
    start_time = Column(DateTime(timezone=True)) # Timestamps from WCL are usually Unix epoch milliseconds
    end_time = Column(DateTime(timezone=True))
    zone_id = Column(Integer)
    zone_name = Column(String) # Added zone name for convenience

    # Relationship: One Report has many Fights
    fights = relationship("Fight", back_populates="report", cascade="all, delete-orphan")
    # Relationship: One Report can involve many Players (indirectly through fights, but keeping direct link might be useful)
    # Let's keep a list of players who participated in the report overall
    players = relationship("Player", back_populates="report") 

class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    # Link player back to the overall report they appeared in
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    name = Column(String, index=True, nullable=False)
    server = Column(String, nullable=True) # Server might still be null based on WCL data
    # Aggregate stats are removed, now stored per fight
    # damage_done = Column(Float)
    # healing_done = Column(Float)

    # Relationship: Player participated in a Report
    report = relationship("Report", back_populates="players")
    # Relationship: One Player has stats in many Fights
    fight_stats = relationship("PlayerFightStats", back_populates="player", cascade="all, delete-orphan")


class Fight(Base):
    __tablename__ = "fights"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    wcl_fight_id = Column(Integer, index=True, nullable=False) # The ID from WCL API
    name = Column(String) # e.g., "Kurog Grimtotem"
    boss_id = Column(Integer) # WCL boss ID (0 for trash)
    # Optional: Add start/end times for fights if needed
    # start_time = Column(Integer)
    # end_time = Column(Integer)

    # Relationship: Many Fights belong to one Report
    report = relationship("Report", back_populates="fights")
    # Relationship to PlayerFightStats (one-to-many)
    stats = relationship("PlayerFightStats", back_populates="fight", cascade="all, delete-orphan")


class PlayerFightStats(Base):
    __tablename__ = "player_fight_stats"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    fight_id = Column(Integer, ForeignKey("fights.id"), nullable=False)
    
    damage_done = Column(Float, default=0.0)
    healing_done = Column(Float, default=0.0)

    # Relationship back to Player (many-to-one)
    player = relationship("Player", back_populates="fight_stats")
    # Relationship back to Fight (many-to-one)
    fight = relationship("Fight", back_populates="stats")
