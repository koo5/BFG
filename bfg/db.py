from typing import List
from typing import Optional
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class Base(DeclarativeBase):
	pass
class Snapshot(Base):
	__tablename__ = "snapshots"
	uuid: Mapped[str] = mapped_column(primary_key=True)
	parent_uuid: Mapped[Optional[str]] = mapped_column()
	received_uuid: Mapped[Optional[str]] = mapped_column()
	host: Mapped[Optional[str]] = mapped_column()
	path: Mapped[str] = mapped_column()


def get_engine():

	host = 'hours.internal'
	db = 'bfg'
	table = 'snapshots'
	user = 'bfg'
	password = 'bfg'

	#return psycopg2.connect(f"dbname={db} user={user} host={host} password={password}")

	conn_str = f"postgresql+psycopg2://{user}:{password}@{host}/{db}"
	engine = create_engine(conn_str, echo=True)
	Base.metadata.create_all(engine)
	return engine

engine = get_engine()


def session():
	session = Session(engine)
	return session

