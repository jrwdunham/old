# Copyright 2016 Joel Dunham
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""SyntacticCategory model"""

from sqlalchemy import Column, Sequence
from sqlalchemy.types import Integer, Unicode, UnicodeText, DateTime
from onlinelinguisticdatabase.model.meta import Base, now, uuid_unicode

class SyntacticCategory(Base):

    __tablename__ = 'syntacticcategory'

    def __init__(self, **kwargs):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

    def __repr__(self):
        return '<SyntacticCategory (%s)>' % self.id

    id = Column(Integer, Sequence('syntacticcategory_seq_id', optional=True), primary_key=True)
    UUID = Column(Unicode(36), default=uuid_unicode)
    name = Column(Unicode(255))
    type = Column(Unicode(60))
    description = Column(UnicodeText)
    datetime_modified = Column(DateTime, default=now)

    def get_dict(self):
        return {
            'id': self.id,
            'UUID': self.UUID,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'datetime_modified': self.datetime_modified
        }
