from sqlalchemy import Column, Integer, String, Boolean,Date, ForeignKey
from sqlalchemy.orm import relationship

from db.base_class import Base


class FpContext(Base):
	id = Column(Integer,primary_key = True, index=True)
	path = Column(String,nullable= False)
	path_crc32 = Column(Integer,nullable= False)
	date_posted = Column(Date)
	status = Column(String) 
	fp_duration = Column(Integer)
	fp_data = Column(String)
	is_active = Column(Boolean(),default=True)
	is_valid = Column(Boolean(),default=True)