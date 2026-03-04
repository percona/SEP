"""Define tests for the app.tasks.db.engine module."""

from sqlalchemy.orm import sessionmaker

from app.tasks.db.engine import get_async_session_maker


class TestGetAsyncSessionMaker:
    """Test the get_async_session_maker function."""

    def test_returns_sessionmaker(self):
        """Assert get_async_session_maker returns a sessionmaker instance."""
        result = get_async_session_maker()
        assert isinstance(result, sessionmaker)

    def test_returns_new_instance_each_call(self):
        """Assert each call returns a distinct session maker instance."""
        maker_a = get_async_session_maker()
        maker_b = get_async_session_maker()
        assert maker_a is not maker_b
