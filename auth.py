import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from settings import SECRET_KEY # Imports the secret we secured earlier!

ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)

def create_access_token(data: dict):
    to_encode = data.copy()
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.now(timezone.utc) + timedelta(hours=8)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials is None:
        print("❌ Auth failure: missing Authorization header")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")

    token = credentials.credentials
    if not token or not isinstance(token, str):
        print("❌ Auth failure: empty or invalid token type")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

    token = token.strip()
    print(f"🔐 Auth header received. Token length={len(token)}")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            print("❌ Auth failure: token missing subject")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token formatting")
        return {"user_id": user_id, "role": payload.get("role")}
    except jwt.ExpiredSignatureError as e:
        print(f"❌ Auth failure: expired token ({e})")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired. Please log in again.")
    except jwt.InvalidTokenError as e:
        print(f"❌ Auth failure: invalid token ({e})")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

async def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access Denied: Admin privileges required")
    return current_user