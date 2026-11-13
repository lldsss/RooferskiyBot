from pathlib import Path
from sqlalchemy import JSON, String
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.mutable import MutableDict, MutableList

from bot.config import OBJECTS, STANDARD_ITEMS, LEVELS
from database.storage import database_url

# Улучшенная конфигурация движка
engine = create_async_engine(
    url=database_url(Path(__file__).resolve().parent.parent),
    echo=False,  # Отключаем логирование для производительности
    connect_args={'timeout': 30},
    pool_pre_ping=True  # Проверка соединения перед использованием
)

async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'

    tg_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default='')
    xp: Mapped[int] = mapped_column(default=0)
    last_roof_time: Mapped[float] = mapped_column(default=0.0)
    level: Mapped[int] = mapped_column(default=0)
    cd_lvl: Mapped[int] = mapped_column(default=0)
    prim_lvl: Mapped[float] = mapped_column(default=0.0)
    object_status: Mapped[bool] = mapped_column(default=False)
    items: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    cd_items: Mapped[int] = mapped_column(default=0)
    prim_items: Mapped[float] = mapped_column(default=0.0)
    lvl_items: Mapped[int] = mapped_column(default=0)


class Chat(Base):
    __tablename__ = 'chats'
    tg_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default='')


class Channel(Base):
    __tablename__ = 'channels'
    tg_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default='')
    link: Mapped[str] = mapped_column(String(500), default='')


class Event(Base):
    __tablename__ = 'events'  # Более правильное название во множественном числе
    name: Mapped[str] = mapped_column(String(255), primary_key=True, default='Ивент')
    description: Mapped[str] = mapped_column(String(1000), default='')
    cd_event: Mapped[int] = mapped_column(default=0)
    prim_event: Mapped[float] = mapped_column(default=0.0)
    lvl_event: Mapped[int] = mapped_column(default=0)
    activated: Mapped[bool] = mapped_column(default=False)


class Level(Base):
    __tablename__ = 'levels'
    level: Mapped[int] = mapped_column(primary_key=True)
    xp: Mapped[int] = mapped_column(default=0)
    object: Mapped[str] = mapped_column(String(255), default='')


class Item(Base):
    __tablename__ = 'items'
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), default='')
    description: Mapped[str] = mapped_column(String(255), default='')
    price: Mapped[int] = mapped_column(default=0)
    available_until: Mapped[float] = mapped_column(default=0.0)
    duration: Mapped[int] = mapped_column(default=86400)
    enabled: Mapped[bool] = mapped_column(default=True)
    limit: Mapped[int] = mapped_column(default=0)  # Если 0, то безлимит
    cd: Mapped[int] = mapped_column(default=0)
    prim: Mapped[float] = mapped_column(default=0)
    lvl: Mapped[int] = mapped_column(default=0)


class Code(Base):
    __tablename__ = 'codes'
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    limit: Mapped[int] = mapped_column(default=1)
    activations: Mapped[int] = mapped_column(default=0)
    xp: Mapped[int] = mapped_column(default=0)
    users: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)


class Payment(Base):
    __tablename__ = 'payments'
    charge_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column()
    item_key: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column()


class Object(Base):
    __tablename__ = 'objects'
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    floors: Mapped[int] = mapped_column(default=1)
    prim: Mapped[float] = mapped_column(default=0.5)
    last_level: Mapped[int] = mapped_column(default=1000)
    image: Mapped[str] = mapped_column(String(500), default='')


async def seed(model, entries):
    """Добавляет недостающие справочные записи, сохраняя изменения администратора."""
    async with async_session() as session:
        from sqlalchemy.dialects.sqlite import insert
        for entry in entries:
            await session.execute(insert(model).values(**entry).on_conflict_do_nothing())
        await session.commit()


async def add_objects():
    # Rename existing rows before seeding so upgrades do not duplicate objects.
    from sqlalchemy import update
    async with async_session() as session:
        for number in range(1, 5):
            old_name, new_name = f'панельку-{number}', f'Панелька-{number}'
            old = await session.get(Object, old_name)
            if old:
                if await session.get(Object, new_name):
                    await session.delete(old)
                else:
                    old.name = new_name
            await session.execute(update(Level).where(Level.object == old_name).values(object=new_name))
        await session.commit()
    await seed(Object, OBJECTS)


async def add_items():
    await seed(Item, STANDARD_ITEMS)


async def add_levels():
    await seed(Level, LEVELS)


# Инициализируем и запускаем базу данных
async def base_run():
    """Инициализация базы данных с начальными данными"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Совместимое обновление старой SQLite-базы без удаления предметов.
        from sqlalchemy import text
        columns = {row[1] for row in (await conn.execute(text('PRAGMA table_info(items)')))}
        for name, definition in {'available_until': 'FLOAT NOT NULL DEFAULT 0',
                                 'duration': 'INTEGER NOT NULL DEFAULT 86400',
                                 'enabled': 'BOOLEAN NOT NULL DEFAULT 1'}.items():
            if name not in columns:
                await conn.execute(text(f'ALTER TABLE items ADD COLUMN {name} {definition}'))

    # Добавляем начальные данные если их нет
    async with async_session() as session:
        from sqlalchemy import select

        # Создаем дефолтный ивент если его нет
        if not await session.scalar(select(Event)):
            session.add(Event(
                name="Ивент",
                description="Обычный ивент",
                cd_event=0,
                prim_event=0.0,
                lvl_event=0,
                activated=False
            ))

        await session.commit()

