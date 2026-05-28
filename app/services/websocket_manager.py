from typing import Set
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_attendance(
        self,
        name: str,
        timestamp: str,
        user_id: int,
        action: str,
        student_code: str | None = None,
    ):
        message = {
            "type": "attendance",
            "data": {
                "user_id": user_id,
                "name": name,
                "student_code": student_code,
                "timestamp": timestamp,
                "action": action,
            }
        }
        await self.broadcast(message)


manager = ConnectionManager()
