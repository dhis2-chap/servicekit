import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from servicekit import SqliteDatabaseBuilder
from servicekit.exceptions import ConflictError

from .conftest import (
    DemoData,
    TestChildEntityIn,
    TestChildEntityManager,
    TestChildEntityRepository,
    TestEntity,
    TestEntityIn,
    TestEntityManager,
    TestEntityOut,
    TestEntityRepository,
)


class TestBaseManager:
    """Tests for the TestEntityManager class."""

    async def test_save_with_input_schema(self) -> None:
        """Test saving an entity using input schema."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create input schema
            config_in = TestEntityIn(name="test_config", data=DemoData(x=1, y=2, z=3, tags=["test"]))

            # Save and get output schema
            result = await manager.save(config_in)

            assert isinstance(result, TestEntityOut)
            assert result.id is not None
            assert result.name == "test_config"
            assert result.data is not None
            assert isinstance(result.data, DemoData)
            assert result.data.x == 1
            assert result.data.y == 2
            assert result.data.z == 3
            assert result.data.tags == ["test"]

        await db.dispose()

    async def test_save_with_id_none_removes_id(self) -> None:
        """Test that save() removes id field when it's None."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create input schema with id=None (default)
            config_in = TestEntityIn(id=None, name="test", data=DemoData(x=1, y=2, z=3, tags=[]))

            result = await manager.save(config_in)

            # Should have a generated ID
            assert result.id is not None
            assert isinstance(result.id, ULID)

        await db.dispose()

    async def test_save_preserves_explicit_id(self) -> None:
        """Test that save() keeps a provided non-null ID intact."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            explicit_id = ULID()
            config_in = TestEntityIn(
                id=explicit_id,
                name="explicit_id_config",
                data=DemoData(x=5, y=5, z=5, tags=["explicit"]),
            )

            result = await manager.save(config_in)

            assert result.id == explicit_id
            assert result.name == "explicit_id_config"

        await db.dispose()

    async def test_save_all(self) -> None:
        """Test saving multiple entities using input schemas."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create multiple input schemas
            configs_in = [
                TestEntityIn(name=f"config{i}", data=DemoData(x=i, y=i * 2, z=i * 3, tags=[f"tag{i}"]))
                for i in range(3)
            ]

            # Save all
            results = await manager.save_all(configs_in)

            assert len(results) == 3
            assert all(isinstance(r, TestEntityOut) for r in results)
            assert all(r.id is not None for r in results)
            assert results[0].name == "config0"
            assert results[1].name == "config1"
            assert results[2].name == "config2"

        await db.dispose()

    async def test_delete_by_id(self) -> None:
        """Test deleting an entity by ID."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create and save entity
            config_in = TestEntityIn(name="to_delete", data=DemoData(x=1, y=2, z=3, tags=[]))
            result = await manager.save(config_in)

            # Verify it exists
            assert await manager.count() == 1

            # Delete it
            assert result.id is not None
            await manager.delete_by_id(result.id)

            # Verify it's gone
            assert await manager.count() == 0

        await db.dispose()

    async def test_delete_all(self) -> None:
        """Test deleting all entities."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create multiple entities
            configs_in = [TestEntityIn(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(5)]
            await manager.save_all(configs_in)

            # Verify they exist
            assert await manager.count() == 5

            # Delete all
            await manager.delete_all()

            # Verify all gone
            assert await manager.count() == 0

        await db.dispose()

    async def test_delete_many_by_ids(self) -> None:
        """Test deleting multiple entities by their IDs."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entities
            configs_in = [TestEntityIn(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(5)]
            results = await manager.save_all(configs_in)

            # Delete some by ID
            assert results[1].id is not None
            assert results[3].id is not None
            to_delete = [results[1].id, results[3].id]
            await manager.delete_all_by_id(to_delete)

            # Should have 3 remaining
            assert await manager.count() == 3

        await db.dispose()

    async def test_delete_all_by_id_empty_list(self) -> None:
        """Test that delete_all_by_id with empty list does nothing."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entities
            configs_in = [TestEntityIn(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(3)]
            await manager.save_all(configs_in)

            # Delete with empty list
            await manager.delete_all_by_id([])

            # All should still exist
            assert await manager.count() == 3

        await db.dispose()

    async def test_count(self) -> None:
        """Test counting entities through manager."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Initially empty
            assert await manager.count() == 0

            # Add entities
            configs_in = [TestEntityIn(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(7)]
            await manager.save_all(configs_in)

            # Count should be 7
            assert await manager.count() == 7

        await db.dispose()

    async def test_output_schema_validation(self) -> None:
        """Test that output schemas are properly validated from ORM models."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entity with complex data
            config_in = TestEntityIn(
                name="validation_test",
                data=DemoData(x=10, y=20, z=30, tags=["production", "critical", "v2.0"]),
            )

            result = await manager.save(config_in)

            # Verify output schema is correct
            assert isinstance(result, TestEntityOut)
            assert isinstance(result.id, ULID)
            assert result.name == "validation_test"
            assert result.data is not None
            assert isinstance(result.data, DemoData)
            assert result.data.x == 10
            assert result.data.y == 20
            assert result.data.z == 30
            assert result.data.tags == ["production", "critical", "v2.0"]

        await db.dispose()

    async def test_save_all_returns_list_of_output_schemas(self) -> None:
        """Test that save_all returns a list of output schemas."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            configs_in = [
                TestEntityIn(name="config1", data=DemoData(x=1, y=1, z=1, tags=["a"])),
                TestEntityIn(name="config2", data=DemoData(x=2, y=2, z=2, tags=["b"])),
            ]

            results = await manager.save_all(configs_in)

            assert isinstance(results, list)
            assert len(results) == 2
            assert all(isinstance(r, TestEntityOut) for r in results)
            assert all(r.id is not None for r in results)

        await db.dispose()

    async def test_manager_commits_after_save(self) -> None:
        """Test that manager commits changes after save."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            config_in = TestEntityIn(name="committed", data=DemoData(x=1, y=2, z=3, tags=[]))
            await manager.save(config_in)

            # Check in a new session that it was committed
            async with db.session() as session2:
                repo2 = TestEntityRepository(session2)
                manager2 = TestEntityManager(repo2)
                assert await manager2.count() == 1

        await db.dispose()

    async def test_manager_commits_after_delete(self) -> None:
        """Test that manager commits changes after delete."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        # Save in one session
        async with db.session() as session1:
            repo1 = TestEntityRepository(session1)
            manager1 = TestEntityManager(repo1)
            config_in = TestEntityIn(name="to_delete", data=DemoData(x=1, y=2, z=3, tags=[]))
            result = await manager1.save(config_in)
            assert result.id is not None
            saved_id = result.id

        # Delete in another session
        async with db.session() as session2:
            repo2 = TestEntityRepository(session2)
            manager2 = TestEntityManager(repo2)
            await manager2.delete_by_id(saved_id)

            # Verify in yet another session
            async with db.session() as session3:
                repo3 = TestEntityRepository(session3)
                manager3 = TestEntityManager(repo3)
                assert await manager3.count() == 0

        await db.dispose()

    async def test_find_by_id(self) -> None:
        """Test finding an entity by ID through manager."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entity
            config_in = TestEntityIn(name="findable", data=DemoData(x=10, y=20, z=30, tags=["test"]))
            saved = await manager.save(config_in)

            # Find by ID
            assert saved.id is not None
            found = await manager.find_by_id(saved.id)

            assert found is not None
            assert isinstance(found, TestEntityOut)
            assert found.id == saved.id
            assert found.name == "findable"
            assert found.data is not None
            assert found.data.x == 10

            # Non-existent ID should return None
            random_id = ULID()
            not_found = await manager.find_by_id(random_id)
            assert not_found is None

        await db.dispose()

    async def test_find_all(self) -> None:
        """Test finding all entities through manager."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entities
            configs_in = [
                TestEntityIn(name=f"config{i}", data=DemoData(x=i, y=i * 2, z=i * 3, tags=[f"tag{i}"]))
                for i in range(5)
            ]
            await manager.save_all(configs_in)

            # Find all
            all_configs = await manager.find_all()

            assert len(all_configs) == 5
            assert all(isinstance(c, TestEntityOut) for c in all_configs)
            assert all(c.id is not None for c in all_configs)

        await db.dispose()

    async def test_find_all_by_id(self) -> None:
        """Test finding multiple entities by IDs through manager."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entities
            configs_in = [TestEntityIn(name=f"config{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(5)]
            results = await manager.save_all(configs_in)

            # Find by specific IDs
            assert results[0].id is not None
            assert results[2].id is not None
            assert results[4].id is not None
            target_ids = [results[0].id, results[2].id, results[4].id]
            found = await manager.find_all_by_id(target_ids)

            assert len(found) == 3
            assert all(isinstance(c, TestEntityOut) for c in found)
            assert all(c.id in target_ids for c in found)

        await db.dispose()

    async def test_exists_by_id(self) -> None:
        """Test checking if entity exists by ID through manager."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entity
            config_in = TestEntityIn(name="exists_test", data=DemoData(x=1, y=2, z=3, tags=[]))
            saved = await manager.save(config_in)

            # Should exist
            assert saved.id is not None
            assert await manager.exists_by_id(saved.id) is True

            # Random ID should not exist
            random_id = ULID()
            assert await manager.exists_by_id(random_id) is False

        await db.dispose()

    async def test_output_schema_includes_timestamps(self) -> None:
        """Test that output schemas include created_at and updated_at timestamps."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            # Create entity
            config_in = TestEntityIn(name="timestamp_test", data=DemoData(x=1, y=2, z=3, tags=[]))
            result = await manager.save(config_in)

            # Verify timestamps exist
            assert result.created_at is not None
            assert result.updated_at is not None
            assert result.id is not None

        await db.dispose()

    async def test_create_rejects_existing_id(self) -> None:
        """Test that create() refuses to overwrite an existing entity."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            explicit_id = ULID()
            await manager.create(TestEntityIn(id=explicit_id, name="original", data=DemoData(x=1, y=1, z=1, tags=[])))

            with pytest.raises(ConflictError):
                await manager.create(
                    TestEntityIn(id=explicit_id, name="replacement", data=DemoData(x=2, y=2, z=2, tags=[]))
                )

            stored = await manager.find_by_id(explicit_id)
            assert stored is not None
            assert stored.name == "original"
            assert await manager.count() == 1

        await db.dispose()

    async def test_create_maps_integrity_error_to_conflict(self) -> None:
        """Test that a concurrent duplicate insert is still reported as a duplicate id."""

        class BlindRepository(TestEntityRepository):
            """Repository that misses the entity on the pre-check, as a concurrent insert would."""

            def __init__(self, session: AsyncSession) -> None:
                """Track how many existence checks have been made."""
                super().__init__(session)
                self.exists_calls = 0

            async def exists_by_id(self, id: ULID) -> bool:
                """Report the entity as missing on the pre-check only."""
                self.exists_calls += 1
                if self.exists_calls == 1:
                    return False
                return await super().exists_by_id(id)

        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        explicit_id = ULID()

        async with db.session() as session:
            manager = TestEntityManager(TestEntityRepository(session))
            await manager.create(TestEntityIn(id=explicit_id, name="first", data=DemoData(x=1, y=1, z=1, tags=[])))

        async with db.session() as session:
            manager = TestEntityManager(BlindRepository(session))

            with pytest.raises(ConflictError) as exc_info:
                await manager.create(TestEntityIn(id=explicit_id, name="second", data=DemoData(x=2, y=2, z=2, tags=[])))

            assert exc_info.value.detail == f"Entity with id {explicit_id} already exists"
            assert await manager.count() == 1

        await db.dispose()

    async def test_create_maps_foreign_key_violation_to_generic_conflict(self) -> None:
        """Test that a foreign key violation is not reported as a duplicate id."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            manager = TestChildEntityManager(TestChildEntityRepository(session))

            with pytest.raises(ConflictError) as exc_info:
                await manager.create(TestChildEntityIn(name="orphan", parent_id=str(ULID())))

            error = exc_info.value
            assert error.detail == "Entity violates a database constraint"
            assert "None" not in error.detail
            assert "already exists" not in error.detail
            assert "INSERT" not in error.detail
            assert error.extensions == {"constraint": "foreign_key"}

        await db.dispose()

    async def test_create_without_id_maps_constraint_violation_generically(self) -> None:
        """Test that an integrity error on a generated id never mentions an id of None."""

        class NullNameRepository(TestEntityRepository):
            """Repository that blanks a required column to force a NOT NULL violation."""

            async def save(self, entity: TestEntity) -> TestEntity:
                """Clear the required name column before flushing."""
                entity.name = None  # type: ignore[assignment]
                return await super().save(entity)

        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            manager = TestEntityManager(NullNameRepository(session))

            with pytest.raises(ConflictError) as exc_info:
                await manager.create(TestEntityIn(name="anonymous", data=DemoData(x=1, y=1, z=1, tags=[])))

            error = exc_info.value
            assert error.detail == "Entity violates a database constraint"
            assert "None" not in error.detail
            assert error.extensions == {"constraint": "not_null"}

        await db.dispose()

    async def test_save_still_upserts(self) -> None:
        """Test that save() keeps upsert semantics for an existing ID."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            explicit_id = ULID()
            await manager.save(TestEntityIn(id=explicit_id, name="original", data=DemoData(x=1, y=1, z=1, tags=[])))
            updated = await manager.save(
                TestEntityIn(id=explicit_id, name="updated", data=DemoData(x=2, y=2, z=2, tags=[]))
            )

            assert updated.id == explicit_id
            assert updated.name == "updated"
            assert await manager.count() == 1

        await db.dispose()

    async def test_save_with_explicit_null_clears_field(self) -> None:
        """Test that an explicit null clears a nullable field on update."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            saved = await manager.save(
                TestEntityIn(name="entity", description="present", data=DemoData(x=1, y=1, z=1, tags=[]))
            )
            assert saved.description == "present"

            cleared = await manager.save(
                TestEntityIn(id=saved.id, name="entity", description=None, data=DemoData(x=1, y=1, z=1, tags=[]))
            )

            assert cleared.description is None

        await db.dispose()

    async def test_save_without_field_keeps_value(self) -> None:
        """Test that an omitted field is left untouched on update."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            saved = await manager.save(
                TestEntityIn(name="entity", description="present", data=DemoData(x=1, y=1, z=1, tags=[]))
            )

            updated = await manager.save(
                TestEntityIn(id=saved.id, name="renamed", data=DemoData(x=1, y=1, z=1, tags=[]))
            )

            assert updated.name == "renamed"
            assert updated.description == "present"

        await db.dispose()

    async def test_save_all_with_explicit_null_clears_field(self) -> None:
        """Test that save_all applies an explicit null to a nullable field."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            saved = await manager.save(
                TestEntityIn(name="entity", description="present", data=DemoData(x=1, y=1, z=1, tags=[]))
            )

            results = await manager.save_all(
                [
                    TestEntityIn(id=saved.id, name="entity", description=None, data=DemoData(x=1, y=1, z=1, tags=[])),
                ]
            )

            assert results[0].description is None

        await db.dispose()

    async def test_save_all_without_field_keeps_value(self) -> None:
        """Test that save_all leaves omitted fields untouched."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            saved = await manager.save(
                TestEntityIn(name="entity", description="present", data=DemoData(x=1, y=1, z=1, tags=[]))
            )

            results = await manager.save_all(
                [TestEntityIn(id=saved.id, name="renamed", data=DemoData(x=1, y=1, z=1, tags=[]))]
            )

            assert results[0].name == "renamed"
            assert results[0].description == "present"

        await db.dispose()

    async def test_save_all_hooks_see_earlier_entities(self) -> None:
        """Test that a pre_save hook can query entities inserted earlier in the same batch."""

        class RecordingManager(TestEntityManager):
            """Manager whose pre_save hook looks up the previously inserted entity."""

            def __init__(self, repository: TestEntityRepository) -> None:
                """Initialize the manager with an empty lookup record."""
                super().__init__(repository)
                self.previous_id: ULID | None = None
                self.found_previous: list[bool] = []

            async def pre_save(self, entity: TestEntity, data: TestEntityIn) -> None:
                """Record whether the previous batch entity is already visible."""
                if self.previous_id is not None:
                    self.found_previous.append(await self.repo.find_by_id(self.previous_id) is not None)
                self.previous_id = entity.id

        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            manager = RecordingManager(TestEntityRepository(session))

            await manager.save_all(
                [TestEntityIn(id=ULID(), name=f"entity{i}", data=DemoData(x=i, y=i, z=i, tags=[])) for i in range(3)]
            )

            assert manager.found_previous == [True, True]

        await db.dispose()

    async def test_save_all_with_duplicate_id_keeps_last_values(self) -> None:
        """Test that a batch containing the same ID twice ends with one row holding the later values."""
        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            repo = TestEntityRepository(session)
            manager = TestEntityManager(repo)

            explicit_id = ULID()
            results = await manager.save_all(
                [
                    TestEntityIn(id=explicit_id, name="first", data=DemoData(x=1, y=1, z=1, tags=[])),
                    TestEntityIn(id=explicit_id, name="second", data=DemoData(x=2, y=2, z=2, tags=[])),
                ]
            )

            assert await manager.count() == 1
            assert results[-1].name == "second"
            stored = await manager.find_by_id(explicit_id)
            assert stored is not None
            assert stored.name == "second"

        await db.dispose()

    async def test_save_all_rolls_back_when_an_item_fails(self) -> None:
        """Test that a failure on the last item leaves no rows from the batch."""

        class FailingManager(TestEntityManager):
            """Manager whose pre_save hook rejects a specific entity."""

            async def pre_save(self, entity: TestEntity, data: TestEntityIn) -> None:
                """Reject the entity named 'boom'."""
                if entity.name == "boom":
                    raise RuntimeError("hook failure")

        db = SqliteDatabaseBuilder.in_memory().build()
        await db.init()

        async with db.session() as session:
            manager = FailingManager(TestEntityRepository(session))

            with pytest.raises(RuntimeError):
                await manager.save_all(
                    [
                        TestEntityIn(name="ok", data=DemoData(x=1, y=1, z=1, tags=[])),
                        TestEntityIn(name="boom", data=DemoData(x=2, y=2, z=2, tags=[])),
                    ]
                )

        async with db.session() as session:
            verification_manager = TestEntityManager(TestEntityRepository(session))
            assert await verification_manager.count() == 0

        await db.dispose()
