def register_balance_handlers(*args, **kwargs):
    """Register balance handlers without eagerly importing the whole package.

    Shared payment copy is used by localization while payment tests replace a
    few CRUD modules. Keeping package initialization lazy also breaks that
    otherwise unnecessary localization → handler → CRUD import cycle.
    """
    from .main import register_balance_handlers as register

    return register(*args, **kwargs)


__all__ = ['register_balance_handlers']
