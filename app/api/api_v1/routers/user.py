from fastapi import APIRouter

router = APIRouter()

@router.post("/users/")
async def create_user(user: UserCreate):
    pass

@router.get("/users/{user_id}")
async def get_user(user_id: int):
    pass

@router.put("/users/{user_id}")
async def update_user(user_id: int, user: UserUpdate):
    pass

@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    pass
