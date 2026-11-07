from bot.handlers.common import router as common_router
from bot.handlers.pack_creation import router as pack_creation_router
from bot.handlers.pack_management import router as pack_management_router
from bot.handlers.pack_import import router as pack_import_router
from bot.handlers.sticker_upload import router as sticker_upload_router
from bot.handlers.settings import router as settings_router

routers = [
    common_router,
    pack_creation_router,
    pack_management_router,
    pack_import_router,
    settings_router,
    sticker_upload_router,  # Put sticker_upload last so it catches general media
]

__all__ = ["routers"]
