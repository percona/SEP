"""Define auth utility functions."""

from app.core.auth.models import BaseUser
from app.core.config import settings
from app.core.utils import import_var


def get_user_model() -> type[BaseUser]:
    """Retrieve the user model class as defined in the settings.

    This function dynamically imports and returns the user model specified in
    the `settings.AUTH_USER_MODEL` configuration. If no custom user model is
    specified, it returns the `BaseUser` model by default.

    Returns
    -------
    Type[BaseUser]
        The user model class, should be a subclass of `BaseUser`.

    Raises
    ------
    ImportError
        If the module specified in `settings.AUTH_USER_MODEL` cannot be imported.
    AttributeError
        If the model class specified in `settings.AUTH_USER_MODEL` cannot be found
        in the imported module.

    """
    if settings.AUTH_USER_MODEL:
        return import_var(settings.AUTH_USER_MODEL)
    return BaseUser
