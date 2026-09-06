from ulid import ULID

from servicekit import BaseRepository, SqliteDatabaseBuilder

from .conftest import DemoData, TestEntity


class TestBaseRepository:
    """Tests for the BaseRepository class."""

    async def test_save_and_find_by_id(self) -> None:
        """Test saving an entity and finding it by ID."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create and save entity
            config = TestEntity(name="test_config", data=DemoData(x=1, y=2, z=3, tags=["test"]))
            saved = await repo.save(config)
            await repo.commit()

            # Find by ID
            found = await repo.find_by_id(saved.id)
            assert found is not None
            assert found.id == saved.id
            assert found.name == "test_config"
            assert isinstance(found.data, DemoData)
            assert found.data.x == 1
            assert found.data.y == 2
            assert found.data.z == 3
            assert found.data.tags == ["test"]

        await db.dispose()

    async def test_save_all(self) -> None:
        """Test saving multiple entities."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create multiple entities
            configs = [
                TestEntity(name="config1", data=DemoData(x=1, y=1, z=1, tags=[])),
                TestEntity(name="config2", data=DemoData(x=2, y=2, z=2, tags=[])),
                TestEntity(name="config3", data=DemoData(x=3, y=3, z=3, tags=[])),
            ]

            await repo.save_all(configs)
            await repo.commit()

            # Verify all saved
            all_configs = await repo.find_all()
            assert len(all_configs) == 3

        await db.dispose()

    async def test_find_all(self) -> None:
        """Test finding all entities."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Save some entities
            configs = [TestEntity(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(5)]
            await repo.save_all(configs)
            await repo.commit()

            # Find all
            all_configs = await repo.find_all()
            assert len(all_configs) == 5
            assert all(isinstance(c, TestEntity) for c in all_configs)

        await db.dispose()

    async def test_find_all_by_id(self) -> None:
        """Test finding multiple entities by their IDs."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create and save entities
            configs = [TestEntity(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(5)]
            await repo.save_all(configs)
            await repo.commit()

            # Refresh to get IDs
            await repo.refresh_many(configs)

            # Find by specific IDs
            target_ids = [configs[0].id, configs[2].id, configs[4].id]
            found = await repo.find_all_by_id(target_ids)

            assert len(found) == 3
            assert all(c.id in target_ids for c in found)

        await db.dispose()

    async def test_find_all_by_id_empty_list(self) -> None:
        """Test finding entities with an empty ID list."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            found = await repo.find_all_by_id([])
            assert found == []

        await db.dispose()

    async def test_count(self) -> None:
        """Test counting entities."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Initially empty
            assert await repo.count() == 0

            # Add some entities
            configs = [TestEntity(name=f"config{i}", data=DemoData(x=0, y=0, z=0, tags=[])) for i in range(3)]
            await repo.save_all(configs)
            await repo.commit()

            # Count should be 3
            assert await repo.count() == 3

        await db.dispose()

    async def test_exists_by_id(self) -> None:
        """Test checking if an entity exists by ID."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create and save entity
            config = TestEntity(name="test", data=DemoData(x=0, y=0, z=0, tags=[]))
            await repo.save(config)
            await repo.commit()
            await repo.refresh_many([config])

            # Should exist
            assert await repo.exists_by_id(config.id) is True

            # Random ULID should not exist
            random_id = ULID()
            assert await repo.exists_by_id(random_id) is False

        await db.dispose()

    async def test_delete(self) -> None:
        """Test deleting a single entity."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create and save entity
            config = TestEntity(name="to_delete", data=DemoData(x=0, y=0, z=0, tags=[]))
            await repo.save(config)
            await repo.commit()
            await repo.refresh_many([config])

            # Delete it
            await repo.delete(config)
            await repo.commit()

            # Should no longer exist
            assert await repo.exists_by_id(config.id) is False
            assert await repo.count() == 0

        await db.dispose()

    async def test_delete_by_id(self) -> None:
        """Test deleting a single entity by ID."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create and save entity
            config = TestEntity(name="to_delete_by_id", data=DemoData(x=0, y=0, z=0, tags=[]))
            await repo.save(config)
            await repo.commit()
            await repo.refresh_many([config])

            # Delete by ID
            await repo.delete_by_id(config.id)
            await repo.commit()

            # Should no longer exist
            assert await repo.exists_by_id(config.id) is False
            assert await repo.count() == 0

        await db.dispose()

    async def test_delete_all(self) -> None:
        """Test deleting all entities."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create some entities
            configs = [TestEntity(name=f"config{i}", data=DemoData(x=0, y=0, z=0, tags=[])) for i in range(5)]
            await repo.save_all(configs)
            await repo.commit()

            assert await repo.count() == 5

            # Delete all
            await repo.delete_all()
            await repo.commit()

            assert await repo.count() == 0

        await db.dispose()

    async def test_delete_all_by_id(self) -> None:
        """Test deleting multiple entities by their IDs."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create entities
            configs = [TestEntity(name=f"config{i}", data=DemoData(x=0, y=0, z=0, tags=[])) for i in range(5)]
            await repo.save_all(configs)
            await repo.commit()
            await repo.refresh_many(configs)

            # Delete specific ones
            to_delete = [configs[1].id, configs[3].id]
            await repo.delete_all_by_id(to_delete)
            await repo.commit()

            # Should have 3 remaining
            assert await repo.count() == 3

            # Deleted ones should not exist
            assert await repo.exists_by_id(configs[1].id) is False
            assert await repo.exists_by_id(configs[3].id) is False

            # Others should still exist
            assert await repo.exists_by_id(configs[0].id) is True
            assert await repo.exists_by_id(configs[2].id) is True
            assert await repo.exists_by_id(configs[4].id) is True

        await db.dispose()

    async def test_delete_all_by_id_empty_list(self) -> None:
        """Test deleting with an empty ID list."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create some entities
            configs = [TestEntity(name=f"config{i}", data=DemoData(x=0, y=0, z=0, tags=[])) for i in range(3)]
            await repo.save_all(configs)
            await repo.commit()

            # Delete with empty list should do nothing
            await repo.delete_all_by_id([])
            await repo.commit()

            assert await repo.count() == 3

        await db.dispose()

    async def test_refresh_many(self) -> None:
        """Test refreshing multiple entities."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create entities
            configs = [TestEntity(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(3)]
            await repo.save_all(configs)
            await repo.commit()

            # Refresh them
            await repo.refresh_many(configs)

            # All should have IDs now
            assert all(c.id is not None for c in configs)
            assert all(c.created_at is not None for c in configs)

        await db.dispose()

    async def test_commit(self) -> None:
        """Test committing changes."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            # Create entity but don't commit
            config = TestEntity(name="test", data=DemoData(x=0, y=0, z=0, tags=[]))
            await repo.save(config)

            # Count in another session should be 0 (not committed)
            async with db.session() as session2:
                repo2 = BaseRepository[TestEntity, ULID](session2, TestEntity)
                assert await repo2.count() == 0

            # Now commit
            await repo.commit()

            # Count in another session should be 1
            async with db.session() as session3:
                repo3 = BaseRepository[TestEntity, ULID](session3, TestEntity)
                assert await repo3.count() == 1

        await db.dispose()

    async def test_find_all_is_ordered_by_id(self) -> None:
        """Test that listing entities returns them ordered by ID."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            ids = sorted(ULID() for _ in range(5))
            for entity_id in reversed(ids):
                await repo.save(TestEntity(id=entity_id, name="entity", data=DemoData(x=1, y=1, z=1, tags=[])))
            await repo.commit()

            assert [entity.id for entity in await repo.find_all()] == ids

        await db.dispose()

    async def test_find_all_paginated_is_ordered_by_id(self) -> None:
        """Test that paginated pages follow ID order without overlapping."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            ids = sorted(ULID() for _ in range(5))
            for entity_id in reversed(ids):
                await repo.save(TestEntity(id=entity_id, name="entity", data=DemoData(x=1, y=1, z=1, tags=[])))
            await repo.commit()

            first_page = await repo.find_all_paginated(0, 2)
            second_page = await repo.find_all_paginated(2, 2)

            assert [entity.id for entity in first_page] == ids[:2]
            assert [entity.id for entity in second_page] == ids[2:4]

        await db.dispose()

    async def test_flush_makes_pending_entity_visible_before_commit(self) -> None:
        """Test that flush() persists pending changes within the transaction."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = BaseRepository[TestEntity, ULID](session, TestEntity)

            entity = TestEntity(name="pending", data=DemoData(x=1, y=1, z=1, tags=[]))
            await repo.save(entity)
            await repo.flush()

            assert await repo.count() == 1

            await repo.rollback()

            assert await repo.count() == 0

        await db.dispose()
