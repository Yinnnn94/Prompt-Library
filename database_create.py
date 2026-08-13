import os
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timezone
import dotenv

dotenv.load_dotenv(dotenv_path=".env", override=True)
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "prompt_library")

SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(SQLALCHEMY_DATABASE_URI)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    prompts = relationship('Prompt', back_populates='category')

    def __repr__(self):
        return f"Category('{self.name}')"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    oid = Column(String(100), unique=True, nullable=False)
    upn = Column(String(100), unique=True, nullable=False)
    is_admin = Column(Boolean, default=False)
    prompts = relationship('Prompt', back_populates='author')

    def __repr__(self):
        return f"User('{self.upn}')"


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String(500), nullable=True)
    is_shared = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    category = relationship('Category', back_populates='prompts')
    author = relationship('User', back_populates='prompts')

    def __repr__(self):
        return f"Prompt('{self.title}', Category:{self.category.name if self.category else 'N/A'}, Approved:{self.is_approved})"

    def get_tags(self):
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',')]

    def set_tags(self, tag_list):
        self.tags = ','.join(tag_list) if tag_list else None



Base.metadata.create_all(bind=engine)