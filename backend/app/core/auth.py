from robyn import Request
from robyn.authentication import AuthenticationHandler, BearerGetter, Identity

from app.core.config import HUB_TOKEN

class TokenAuthHandler(AuthenticationHandler):
    def __init__(self):
        super().__init__(token_getter=BearerGetter())

    async def authenticate(self, request: Request) -> Identity | None:
        token = self.token_getter.get_token(request)
        if token == HUB_TOKEN:
            return Identity(claims={})
        
        return None

def check_ws_token(query_params: dict) -> bool:
    """Websocket routes don't go through auth_required, so callers check the
    ?token= query param themselves on connect"""
    return query_params.get("token") == HUB_TOKEN