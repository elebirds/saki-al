from pydantic import BaseModel


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    must_change_password: bool
